"""Library pagination and safe, bounded Homebox primary-photo previews."""

from io import BytesIO
from typing import cast

import httpx
import pytest
from fastapi import HTTPException
from PIL import Image

from homebox_companion import HomeboxClient, HomeboxGateway
from server.api.library_images import (
    _make_library_preview,
    existing_item_thumbnail,
    search_existing_items,
)


class FakeGateway:
    def __init__(self) -> None:
        self.calls = []
        self.images: dict[str, bytes] = {}

    async def get_version(self):
        return "0.27.1"

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
    first = await search_existing_items(
        cast(HomeboxGateway, gateway), q="   tools   ", page=1, page_size=40, sort="newest"
    )
    second = await search_existing_items(cast(HomeboxGateway, gateway), q="tools", page=2, page_size=40, sort="newest")
    third = await search_existing_items(cast(HomeboxGateway, gateway), q="tools", page=3, page_size=40, sort="newest")
    assert gateway.calls[0] == {
        "query": "tools",
        "page": 1,
        "page_size": 40,
        "order_by": "createdAt",
        "order_direction": "desc",
    }
    assert first["total"] == 83
    assert first["page"] == 1
    assert len(first["items"]) == 39  # excludes a location
    assert first["has_more"] is True
    assert first["items"][0]["thumbnail_id"] == "image-0"
    assert first["items"][2]["thumbnail_id"] == "thumb-3"
    assert len(second["items"]) == 40 and second["has_more"] is True
    assert len(third["items"]) == 3 and third["has_more"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sort", "order_by", "direction"),
    [
        ("newest", "createdAt", "desc"),
        ("oldest", "createdAt", "asc"),
        ("name_asc", "name", "asc"),
        ("name_desc", "name", "desc"),
    ],
)
async def test_library_sort_is_forwarded_to_homebox_before_pagination(sort, order_by, direction):
    gateway = FakeGateway()
    page = await search_existing_items(cast(HomeboxGateway, gateway), q="", page=2, page_size=40, sort=sort)
    assert page["page"] == 2
    assert gateway.calls == [
        {
            "query": None,
            "page": 2,
            "page_size": 40,
            "order_by": order_by,
            "order_direction": direction,
        }
    ]


@pytest.mark.asyncio
async def test_homebox_transport_sends_sort_fields_to_entities_endpoint():
    requests = []

    def mock_entities(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"items": [], "total": 0, "page": 1})

    transport = httpx.MockTransport(mock_entities)
    async with HomeboxClient(base_url="http://homebox.example/api/v1", transport=transport) as client:
        await client.list_items("test-token", page=1, page_size=40, order_by="createdAt", order_direction="desc")

    assert len(requests) == 1
    assert requests[0].url.path.endswith("/entities")
    assert dict(requests[0].url.params) == {
        "page": "1",
        "pageSize": "40",
        "orderBy": "createdAt",
        "orderDirection": "desc",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sort", "reverse_order"),
    [
        ("oldest", True),
        ("name_desc", True),
        ("newest", False),
        ("name_asc", False),
    ],
)
async def test_homebox_026_legacy_reverse_sort_applies_before_pagination(sort, reverse_order):
    """Homebox 0.26.2 ignores orderDirection, so reverse its complete raw list."""

    class LegacyGateway:
        def __init__(self):
            self.calls: list[dict] = []
            self.raw = [
                {
                    "id": f"item-{index:03d}",
                    "name": f"Item {index:03d}",
                    "entityType": {"isLocation": index == 26},
                }
                for index in range(114)
            ]

        async def get_version(self):
            return "0.26.2"

        async def list_items(self, **kwargs):
            self.calls.append(kwargs)
            rows = self.raw
            # Mimic v0.26.2: fixed descending createdAt or ascending name.
            if kwargs["order_by"] == "createdAt":
                rows = list(reversed(rows))
            offset = (kwargs["page"] - 1) * kwargs["page_size"]
            return {"items": rows[offset : offset + kwargs["page_size"]], "total": len(rows)}

    gw = LegacyGateway()
    first = await search_existing_items(cast(HomeboxGateway, gw), q="", page=1, page_size=40, sort=sort)
    second = await search_existing_items(cast(HomeboxGateway, gw), q="", page=2, page_size=40, sort=sort)
    third = await search_existing_items(cast(HomeboxGateway, gw), q="", page=3, page_size=40, sort=sort)
    assert first["total"] == second["total"] == third["total"] == 114
    # All 114 raw rows, including the one location, are sorted before page slicing.
    all_ids = [item["id"] for response in (first, second, third) for item in response["items"]]
    if sort in ("newest", "name_desc"):
        expected = [f"item-{i:03d}" for i in range(113, -1, -1)]
    else:
        expected = [f"item-{i:03d}" for i in range(114)]
    expected.remove("item-026")
    assert all_ids == expected
    if reverse_order:
        assert all(call["page_size"] == 50 for call in gw.calls)
        assert len(gw.calls) == 9  # 3 legacy upstream pages per requested page
    else:
        assert [call["page"] for call in gw.calls] == [1, 2, 3]


@pytest.mark.asyncio
async def test_legacy_reverse_sort_rejects_unbounded_inventory():
    class ExcessiveGateway:
        async def get_version(self):
            return "0.26.2"

        async def list_items(self, **kwargs):
            return {"items": [{"id": "first", "name": "First"}], "total": 10_001}

    with pytest.raises(HTTPException) as exc:
        await search_existing_items(
            cast(HomeboxGateway, ExcessiveGateway()),
            q="",
            page=1,
            page_size=40,
            sort="oldest",
        )
    assert exc.value.status_code == 422


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
