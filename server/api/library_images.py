"""Authenticated library-image search and attachment import endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
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
) -> dict[str, Any]:
    response = await gateway.list_items(query=q.strip() or None, page_size=50, page=1)
    items = []
    for item in response.get("items", []):
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
    return {"items": items, "total": response.get("total", len(items))}


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
        "thumbnail_id": item.get("thumbnailId") or item.get("imageId"),
        "attachments": [
            {"id": x.get("id"), "type": x.get("type"), "primary": bool(x.get("primary"))}
            for x in item.get("attachments", [])
            if isinstance(x, dict)
        ],
    }
