"""Authenticated library-image search and attachment import endpoints."""

from io import BytesIO
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from homebox_companion import HomeboxGateway
from homebox_companion.core.image_library import (
    ImageLibraryError,
    download_selected_image,
    get_ebay_listing_photos,
    has_serpapi_key,
    save_serpapi_key,
    search_images,
)

from ..dependencies import get_gateway, require_auth
from ..services.image_processing import run_image_processing

router = APIRouter(prefix="/library-images", dependencies=[Depends(require_auth)])


class ProviderKeyRequest(BaseModel):
    key: str = Field(max_length=512)


class ImageAttachRequest(BaseModel):
    image_id: str = Field(min_length=5, max_length=12000)
    primary: bool = False


def _raise_library_error(exc: ImageLibraryError) -> HTTPException:
    message = str(exc)
    status = 409 if "key required" in message.lower() else 400
    if "unavailable" in message.lower():
        status = 502
    return HTTPException(status_code=status, detail=message)


@router.get("/config")
async def library_config() -> dict[str, bool]:
    return {"serpapi_configured": has_serpapi_key()}


@router.put("/config")
async def update_library_config(payload: ProviderKeyRequest) -> dict[str, bool]:
    try:
        save_serpapi_key(payload.key)
    except ImageLibraryError as exc:
        raise _raise_library_error(exc) from exc
    return {"serpapi_configured": has_serpapi_key()}


@router.get("/search")
async def library_search(
    q: str = Query(min_length=1, max_length=180),
    provider: str = Query(pattern="^(serpapi|ebay)$"),
) -> dict[str, Any]:
    try:
        return await search_images(q, provider)
    except ImageLibraryError as exc:
        raise _raise_library_error(exc) from exc


@router.get("/ebay-photos")
async def ebay_listing_photos(
    product_id: str = Query(pattern=r"^[0-9]{9,15}$"),
) -> dict[str, Any]:
    """User-triggered photo gallery for one eBay UK listing (extra SerpApi request)."""
    try:
        return await get_ebay_listing_photos(product_id)
    except ImageLibraryError as exc:
        raise _raise_library_error(exc) from exc


@router.get("/download")
async def library_download(image_id: str = Query(min_length=5, max_length=12000)) -> Response:
    try:
        image = await download_selected_image(image_id)
    except ImageLibraryError as exc:
        raise _raise_library_error(exc) from exc
    return Response(
        image,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/items")
async def search_existing_items(
    gateway: Annotated[HomeboxGateway, Depends(get_gateway)],
    q: str = Query(default="", max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=40, ge=1, le=50),
) -> dict[str, Any]:
    """Return one bounded Homebox page and its thumbnail references.

    Homebox may include location/container entities in its total; only regular
    inventory items are rendered, but paging follows Homebox's raw result set.
    """
    response = await gateway.list_items(query=q.strip() or None, page=page, page_size=page_size)
    raw_items = response.get("items", [])
    items = []
    for item in raw_items:
        typ = item.get("entityType") or {}
        if isinstance(typ, dict) and typ.get("isLocation") is True:
            continue
        items.append(
            {
                "id": item.get("id"),
                "name": item.get("name", ""),
                "description": item.get("description", ""),
                "manufacturer": item.get("manufacturer", ""),
                "model_number": item.get("modelNumber", ""),
                "thumbnail_id": item.get("thumbnailId") or item.get("imageId"),
            }
        )
    total = response.get("total")
    if not isinstance(total, int) or total < 0:
        total = (page - 1) * page_size + len(raw_items)
        has_more = len(raw_items) == page_size
    else:
        has_more = page * page_size < total and bool(raw_items)
    return {"items": items, "total": total, "page": page, "has_more": has_more}


def _make_library_preview(content: bytes) -> bytes:
    """Build a small inventory preview instead of sending original photographs to the browser."""
    if len(content) > 20 * 1024 * 1024:
        raise ValueError("Thumbnail source exceeds 20 MiB")
    with Image.open(BytesIO(content)) as source:
        if source.width * source.height > 24_000_000:
            raise ValueError("Image has too many pixels")
        source.seek(0)
        image = ImageOps.exif_transpose(source)
        image.thumbnail((320, 320), Image.Resampling.LANCZOS)
        if image.mode == "RGB":
            rgb = image
        elif image.mode in {"RGBA", "LA", "P"}:
            rgba = image.convert("RGBA")
            rgb = Image.new("RGB", rgba.size, "white")
            rgb.paste(rgba, mask=rgba.getchannel("A"))
        else:
            rgb = image.convert("RGB")
        buffer = BytesIO()
        rgb.save(buffer, format="JPEG", quality=78, optimize=True)
        return buffer.getvalue()


@router.get("/items/{item_id}/thumbnail")
async def existing_item_thumbnail(
    item_id: str,
    gateway: Annotated[HomeboxGateway, Depends(get_gateway)],
    attachment_id: str = Query(min_length=1, max_length=128),
) -> Response:
    """Authenticated preview of an existing Homebox primary photo.

    The selected attachment ID comes from the item-list response; access to its
    bytes remains scoped to the requesting Homebox user/collection.
    """
    try:
        content, _ = await gateway.get_attachment(item_id, attachment_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Item thumbnail not found.") from exc
    try:
        preview = await run_image_processing(_make_library_preview, content)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Unable to process item thumbnail.") from exc
    return Response(
        preview,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/items/{item_id}")
async def existing_item_detail(
    item_id: str,
    gateway: Annotated[HomeboxGateway, Depends(get_gateway)],
) -> dict[str, Any]:
    item = await gateway.get_item(item_id)
    return {
        "id": item.get("id"),
        "name": item.get("name", ""),
        "description": item.get("description", ""),
        "manufacturer": item.get("manufacturer", ""),
        "model_number": item.get("modelNumber", ""),
        "thumbnail_id": item.get("thumbnailId") or item.get("imageId"),
        "attachments": [
            {"id": x.get("id"), "type": x.get("type"), "primary": bool(x.get("primary"))}
            for x in item.get("attachments", [])
            if isinstance(x, dict)
        ],
    }


@router.post("/items/{item_id}/attach")
async def attach_image_to_existing_item(
    item_id: str,
    request: ImageAttachRequest,
    gateway: Annotated[HomeboxGateway, Depends(get_gateway)],
) -> dict[str, Any]:
    # Check the inventory record and the caller's access to it before fetching remote bytes.
    item = await gateway.get_item(item_id)
    if not item or item.get("id") != item_id:
        raise HTTPException(status_code=404, detail="Inventory item not found.")
    typ = item.get("entityType") or {}
    if isinstance(typ, dict) and typ.get("isLocation") is True:
        raise HTTPException(status_code=400, detail="Select an inventory item, not a location.")
    try:
        content = await download_selected_image(request.image_id)
    except ImageLibraryError as exc:
        raise _raise_library_error(exc) from exc
    await gateway.upload_attachment(
        item_id,
        content,
        "catalogue-photo.jpg",
        mime_type="image/jpeg",
        attachment_type="photo",
        primary=request.primary,
    )
    item = await gateway.get_item(item_id)
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "description": item.get("description", ""),
        "manufacturer": item.get("manufacturer", ""),
        "model_number": item.get("modelNumber", ""),
        "thumbnail_id": item.get("thumbnailId") or item.get("imageId"),
        "attachments": [
            {"id": x.get("id"), "type": x.get("type"), "primary": bool(x.get("primary"))}
            for x in item.get("attachments", [])
            if isinstance(x, dict)
        ],
    }
