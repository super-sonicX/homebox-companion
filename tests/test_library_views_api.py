"""Library pagination and safe, bounded Homebox primary-photo previews."""

from io import BytesIO
from typing import cast

import pytest
from fastapi import HTTPException
from PIL import Image

from homebox_companion import HomeboxGateway
from server.api.library_images import (
    _make_library_preview,
    existing_item_thumbnail,
    search_existing_items,
)


class FakeGateway:
    def __init__(self) -> None:
        self.calls = []
        self.images: dict[str, bytes] = {}

    async def list_items(self, **kwargs):
        self.calls.append(kwargs)
        page = kwargs["page"]
        first = (page - 1) * kwargs["page_size"]
        last = min(first + kwargs["page_size"], 83)
        return {
            "items": [
                {
                    "id": f"item-{idx}",
                    "name": f"Item {idx}",
                    "thumbnailId": f"thumb-{idx}" if idx % 2 else None,
                    "imageId": f"image-{idx}" if idx % 3 == 0 else None,
                    "entityType": {"isLocation": idx == 2},
                }
                for idx in range(first, last)
            ],
            "page": page,
            "pageSize": kwargs["page_size"],
            "total": 83,
        }

    async def get_attachment(self, item_id, attachment_id):
        self.calls.append((item_id, attachment_id))
        if attachment_id not in self.images:
            raise FileNotFoundError(attachment_id)
        return self.images[attachment_id], "image/png"


@pytest.mark.asyncio
async def test_pages_are_bounded_and_exclude_location_without_losing_pagination():
    gateway = FakeGateway()
    first = await search_existing_items(cast(HomeboxGateway, gateway), q="   tools   ", page=1, page_size=40)
    second = await search_existing_items(cast(HomeboxGateway, gateway), q="tools", page=2, page_size=40)
    third = await search_existing_items(cast(HomeboxGateway, gateway), q="tools", page=3, page_size=40)
    assert gateway.calls[0] == {"query": "tools", "page": 1, "page_size": 40}
    assert first["total"] == 83
    assert first["page"] == 1
    assert len(first["items"]) == 39  # excludes a location
    assert first["has_more"] is True
    assert first["items"][0]["thumbnail_id"] == "image-0"
    assert first["items"][2]["thumbnail_id"] == "thumb-3"
    assert len(second["items"]) == 40 and second["has_more"] is True
    assert len(third["items"]) == 3 and third["has_more"] is False


def _picture(width: int, height: int, colour: str, format: str = "PNG") -> bytes:
    image = Image.new("RGBA", (width, height), colour)
    buf = BytesIO()
    image.save(buf, format=format)
    return buf.getvalue()


def test_small_preview_is_real_jpeg_and_preserves_aspect_ratio():
    thumbnail = _make_library_preview(_picture(1200, 800, "#4488cc"))
    with Image.open(BytesIO(thumbnail)) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"
        assert image.size == (320, 213)
    assert len(thumbnail) < 35_000


def test_small_preview_rejects_empty_or_invalid_content():
    with pytest.raises((OSError, ValueError)):
        _make_library_preview(b"not an image")
    with pytest.raises(ValueError, match="20 MiB"):
        _make_library_preview(b"x" * (20 * 1024 * 1024 + 1))


@pytest.mark.asyncio
async def test_authenticated_preview_resizes_attachment_and_returns_browser_cache_header():
    gateway = FakeGateway()
    gateway.images["primary-photo"] = _picture(1000, 1000, "#995533")
    response = await existing_item_thumbnail("item-1", cast(HomeboxGateway, gateway), attachment_id="primary-photo")
    assert response.media_type == "image/jpeg"
    assert response.headers["cache-control"] == "private, max-age=300"
    assert gateway.calls == [("item-1", "primary-photo")]
    with Image.open(BytesIO(response.body)) as image:
        assert image.size == (320, 320)


@pytest.mark.asyncio
async def test_missing_attachment_returns_404_not_a_broken_page():
    with pytest.raises(HTTPException) as error:
        await existing_item_thumbnail("item-1", cast(HomeboxGateway, FakeGateway()), attachment_id="missing")
    assert error.value.status_code == 404
