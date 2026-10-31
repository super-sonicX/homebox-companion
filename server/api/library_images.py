"""Authenticated library-image search and attachment import endpoints."""

import re
from io import BytesIO
from typing import Annotated, Any, Literal

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
from homebox_companion.core.library_gallery_order import ordered_photo_ids, save_photo_order
from homebox_companion.homebox.relationships import item_update_payload

from ..dependencies import get_gateway, require_auth
from ..services.image_processing import run_image_processing

router = APIRouter(prefix="/library-images", dependencies=[Depends(require_auth)])


class ProviderKeyRequest(BaseModel):
    key: str = Field(max_length=512)


class ImageAttachRequest(BaseModel):
    image_id: str = Field(min_length=5, max_length=12000)
    primary: bool = False


class ItemDetailsUpdate(BaseModel):
    """Intentionally restricted set of writable fields to avoid changing placement/tags."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    quantity: float | None = Field(default=None, ge=0, le=100_000_000, allow_inf_nan=False)
    manufacturer: str | None = Field(default=None, max_length=255)
    model_number: str | None = Field(default=None, max_length=255)
    serial_number: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=10000)
    purchase_from: str | None = Field(default=None, max_length=255)
    purchase_price: float | None = Field(default=None, ge=0, le=100_000_000, allow_inf_nan=False)
    expected_updated_at: str | None = Field(default=None, max_length=100)


class PhotoOrderUpdate(BaseModel):
    ordered_ids: list[str] = Field(max_length=100)


def _photo_attachments(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Include all images regardless of personal-camera or catalogue origin."""
    result = []
    for entry in item.get("attachments") or []:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        attachment_type = str(entry.get("type") or "photo").lower()
        mime_type = str(entry.get("mimeType") or "").lower()
        if attachment_type not in ("photo", "image") and not mime_type.startswith("image/"):
            continue
        result.append(entry)
    return result


def _item_payload(item: dict[str, Any], gateway: HomeboxGateway) -> dict[str, Any]:
    images = _photo_attachments(item)
    ids = [str(img["id"]) for img in images]
    return {
        "id": item.get("id"),
        "name": item.get("name", ""),
        "description": item.get("description", ""),
        "quantity": item.get("quantity", 1),
        "manufacturer": item.get("manufacturer", ""),
        "model_number": item.get("modelNumber", ""),
        "serial_number": item.get("serialNumber", ""),
        "notes": item.get("notes", ""),
        "asset_id": item.get("assetId", ""),
        "purchase_from": item.get("purchaseFrom", ""),
        "purchase_price": item.get("purchasePrice"),
        "purchase_date": item.get("purchaseDate", ""),
        "warranty_expires": item.get("warrantyExpires", ""),
        "warranty_details": item.get("warrantyDetails", ""),
        "updated_at": item.get("updatedAt", ""),
        "location": (item.get("location") or {}).get("name", ""),
        "parent": (item.get("parent") or {}).get("name", ""),
        "tags": [str(t.get("name")) for t in (item.get("tags") or []) if isinstance(t, dict) and t.get("name")],
        "thumbnail_id": item.get("thumbnailId") or item.get("imageId"),
        "attachments": [
            {
                "id": str(x["id"]),
                "type": x.get("type", "photo"),
                "title": x.get("title", ""),
                "mime_type": x.get("mimeType", ""),
                "primary": bool(x.get("primary")) or x.get("id") == item.get("thumbnailId"),
            }
            for x in images
        ],
        "gallery_order": ordered_photo_ids(gateway.access, str(item.get("id")), ids),
        "gallery_order_scope": "companion",
    }


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


# Older Homebox releases accept orderBy but ignore orderDirection. A reversed
# page from the API is not a correctly sorted page, so reverse the complete
# result set before slicing it for these two legacy modes.
_LEGACY_SORT_PAGE_SIZE = 50
_LEGACY_MAX_SORT_ITEMS = 10_000


async def _requires_legacy_reverse_sort(gateway: HomeboxGateway, sort: str) -> bool:
    if sort not in ("oldest", "name_desc"):
        return False
    try:
        version = await gateway.get_version()
    except Exception as exc:
        # Authentication failures and unavailable servers should not be masked
        # by returning a misleading sort result.
        from homebox_companion import HomeboxAuthError
        from homebox_companion.core import HomeboxCompanionError

        if isinstance(exc, HomeboxAuthError):
            raise
        if not isinstance(exc, HomeboxCompanionError):
            raise
        version = None
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$", version or "")
    return not (match and tuple(map(int, match.groups())) >= (0, 27, 0))


async def _reverse_legacy_sort(
    gateway: HomeboxGateway,
    *,
    query: str | None,
    order_by: str,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """Reverse the complete 0.26.x result, not only the requested page.

    Legacy Homebox sorts createdAt newest-first and names A-Z, even when the
    opposite direction is requested. Retaining the backend's own collation,
    then reversing its ordered rows, avoids inconsistent pagination and does
    not require the summary response to expose createdAt.
    """
    all_items: list[dict[str, Any]] = []
    total = 0
    for legacy_page in range(1, _LEGACY_MAX_SORT_ITEMS // _LEGACY_SORT_PAGE_SIZE + 2):
        response = await gateway.list_items(
            query=query,
            page=legacy_page,
            page_size=_LEGACY_SORT_PAGE_SIZE,
            order_by=order_by,
        )
        batch = response.get("items") or []
        total_value = response.get("total")
        if isinstance(total_value, int) and total_value >= 0:
            total = total_value
            if total > _LEGACY_MAX_SORT_ITEMS:
                raise HTTPException(422, "Legacy Homebox sort exceeds the supported 10,000-entity limit.")
        if not batch:
            break
        all_items.extend(batch)
        if len(all_items) > _LEGACY_MAX_SORT_ITEMS:
            raise HTTPException(422, "Legacy Homebox sort exceeds the supported 10,000-entity limit.")
        if (total and len(all_items) >= total) or len(batch) < _LEGACY_SORT_PAGE_SIZE:
            break
    all_items.reverse()
    offset = (page - 1) * page_size
    return {
        "items": all_items[offset : offset + page_size],
        "total": total if total else len(all_items),
    }


@router.get("/items")
async def search_existing_items(
    gateway: Annotated[HomeboxGateway, Depends(get_gateway)],
    q: str = Query(default="", max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=40, ge=1, le=50),
    sort: Literal["newest", "oldest", "name_asc", "name_desc"] = Query(default="newest"),
) -> dict[str, Any]:
    """Return one bounded Homebox page and its thumbnail references.

    Homebox may include location/container entities in its total; only regular
    inventory items are rendered, but paging follows Homebox's raw result set.
    """
    order_by, direction = {
        "newest": ("createdAt", "desc"),
        "oldest": ("createdAt", "asc"),
        "name_asc": ("name", "asc"),
        "name_desc": ("name", "desc"),
    }[sort]
    query = q.strip() or None
    if await _requires_legacy_reverse_sort(gateway, sort):
        response = await _reverse_legacy_sort(
            gateway,
            query=query,
            order_by=order_by,
            page=page,
            page_size=page_size,
        )
    else:
        response = await gateway.list_items(
            query=query,
            page=page,
            page_size=page_size,
            order_by=order_by,
            order_direction=direction,
        )
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
    """Return full item fields and existing photo-gallery metadata."""
    item = await gateway.get_item(item_id)
    return _item_payload(item, gateway)


@router.put("/items/{item_id}/details")
async def edit_existing_item(
    item_id: str,
    request: ItemDetailsUpdate,
    gateway: Annotated[HomeboxGateway, Depends(get_gateway)],
) -> dict[str, Any]:
    """Update common fields with a full Homebox PUT that preserves relationships/custom fields."""
    changes = request.model_dump(exclude_unset=True, exclude={"expected_updated_at"})
    if not changes:
        raise HTTPException(status_code=422, detail="No fields were changed.")
    if "name" in changes and (not changes["name"] or not str(changes["name"]).strip()):
        raise HTTPException(status_code=422, detail="Item name cannot be empty.")
    original = await gateway.get_item(item_id)
    if original.get("id") != item_id:
        raise HTTPException(status_code=404, detail="Item not found.")
    if (
        request.expected_updated_at
        and original.get("updatedAt")
        and request.expected_updated_at != original["updatedAt"]
    ):
        raise HTTPException(status_code=409, detail="This item was edited elsewhere. Reload before saving.")
    current_type = original.get("entityType") or {}
    if isinstance(current_type, dict) and current_type.get("isLocation") is True:
        raise HTTPException(status_code=400, detail="This editor is for inventory items, not locations.")
    # Homebox PUT replaces an entire entity: retain parent, location override,
    # tags, warranties and user-defined fields rather than sending only the changed keys.
    body = item_update_payload(original)
    mapping = {
        "name": "name",
        "description": "description",
        "quantity": "quantity",
        "manufacturer": "manufacturer",
        "model_number": "modelNumber",
        "serial_number": "serialNumber",
        "notes": "notes",
        "purchase_from": "purchaseFrom",
        "purchase_price": "purchasePrice",
    }
    for key, value in changes.items():
        body[mapping[key]] = value
    await gateway.update_item(item_id, body)
    return _item_payload(await gateway.get_item(item_id), gateway)


def _image_or_404(item: dict[str, Any], attachment_id: str) -> dict[str, Any]:
    match = next((x for x in _photo_attachments(item) if str(x["id"]) == attachment_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="This photograph is not attached to the item.")
    return match


@router.put("/items/{item_id}/photos/order")
async def update_photo_order(
    item_id: str,
    request: PhotoOrderUpdate,
    gateway: Annotated[HomeboxGateway, Depends(get_gateway)],
) -> dict[str, Any]:
    """Store presentation order on Companion, since Homebox exposes no native order API."""
    item = await gateway.get_item(item_id)
    ids = [str(x["id"]) for x in _photo_attachments(item)]
    proposed = request.ordered_ids
    if len(proposed) != len(set(proposed)) or set(proposed) != set(ids):
        raise HTTPException(status_code=409, detail="The photographs have changed; reload before reordering.")
    save_photo_order(gateway.access, item_id, proposed)
    return _item_payload(item, gateway)


@router.put("/items/{item_id}/photos/{attachment_id}/primary")
async def set_existing_photo_primary(
    item_id: str,
    attachment_id: str,
    gateway: Annotated[HomeboxGateway, Depends(get_gateway)],
) -> dict[str, Any]:
    """Set an existing personal/catalogue photo as Homebox's primary image."""
    original = await gateway.get_item(item_id)
    image = _image_or_404(original, attachment_id)
    if image.get("primary") is not True:
        # Preserve existing caption/type because Homebox uses a PUT endpoint.
        changes = {"primary": True, "type": image.get("type") or "photo", "title": image.get("title") or ""}
        await gateway.update_attachment(item_id, attachment_id, changes)
    return _item_payload(await gateway.get_item(item_id), gateway)


@router.delete("/items/{item_id}/photos/{attachment_id}")
async def remove_existing_photo(
    item_id: str,
    attachment_id: str,
    gateway: Annotated[HomeboxGateway, Depends(get_gateway)],
) -> dict[str, Any]:
    """Remove ONLY the explicitly selected image; never delete the inventory item."""
    original = await gateway.get_item(item_id)
    _image_or_404(original, attachment_id)
    await gateway.delete_attachment(item_id, attachment_id)
    return _item_payload(await gateway.get_item(item_id), gateway)


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
    return _item_payload(item, gateway)
