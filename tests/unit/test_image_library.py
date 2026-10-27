"""Library image search, token integrity, and SSRF regression checks."""

import base64
import io

import pytest
from PIL import Image

from homebox_companion.core import image_library as lib


def _example(**updates):
    obj = {
        "image_url": "https://images.example.org/product.jpg",
        "thumbnail_url": "https://images.example.org/preview.jpg",
        "source_url": "https://example.org/product",
        "license": "cc0",
        "attribution": "Example photographer",
    }
    obj.update(updates)
    return obj


def test_signed_image_result_cannot_be_tampered_with():
    token = lib._sign_result(_example())
    assert lib.verify_result(token)["image_url"] == "https://images.example.org/product.jpg"
    raw = bytearray(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    raw[5] ^= 1
    forged = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    with pytest.raises(lib.ImageLibraryError, match="Invalid"):
        lib.verify_result(forged)


def test_private_urls_are_rejected_including_encoded_hosts():
    blocked = [
        "http://example.com/photo.jpg",
        "https://127.0.0.1/image.png",
        "https://10.0.0.4/photo.png",
        "https://[::1]/a.png",
        "https://localhost/photo.jpg",
        "https://router.local/images.png",
        "https://images.example.com:8443/p.png",
        "https://evil.example@localhost/a.jpg",
    ]
    assert all(not lib._valid_public_url(x) for x in blocked)
    assert lib._valid_public_url("https://www.example.com/image.jpg")


def test_download_rejects_private_ip_with_verified_token():
    token = lib._sign_result(_example(image_url="https://192.168.0.10/test.jpg"))
    with pytest.raises(lib.ImageLibraryError):
        lib.verify_result(token)


@pytest.mark.asyncio
async def test_search_result_response_has_signed_photo_and_source(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "images": [
                    {
                        "title": "Polymaker dryer",
                        "imageUrl": "https://example.org/full.jpg",
                        "thumbnailUrl": "https://example.org/thumb.jpg",
                        "link": "https://example.org/page",
                        "domain": "example.org",
                        "position": 1,
                    }
                ]
            }

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, headers, json):
            assert url == "https://google.serper.dev/images"
            assert headers["X-API-KEY"] == "test-provider-key"
            assert json["num"] == 18
            return FakeResponse()

    monkeypatch.setattr(lib, "get_google_key", lambda: "test-provider-key")
    monkeypatch.setattr(lib.httpx, "AsyncClient", FakeClient)
    lib._RESULTS.clear()
    result = await lib.search_images("Polymaker PolyDryer", "google")
    assert len(result["results"]) == 1
    item = result["results"][0]
    assert item["title"] == "Polymaker dryer"
    assert item["source_url"] == "https://example.org/page"
    assert lib.verify_result(item["id"])["image_url"] == "https://example.org/full.jpg"


def test_web_download_is_reencoded_to_safe_jpeg():
    buf = io.BytesIO()
    Image.new("RGBA", (32, 24), (200, 100, 50, 120)).save(buf, format="PNG")
    jpg = lib._to_jpeg(buf.getvalue())
    assert jpg[:3] == bytes((255, 216, 255))
    with Image.open(io.BytesIO(jpg)) as photo:
        assert photo.format == "JPEG"
        assert photo.size == (32, 24)
        assert photo.mode == "RGB"
