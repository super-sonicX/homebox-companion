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


@pytest.mark.asyncio
async def test_serpapi_google_images_maps_search_results(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "images_results": [
                    {
                        "title": "Polymaker PolyDryer box",
                        "original": "https://polymaker.com/images/polydryer.png",
                        "thumbnail": "https://serpapi.com/searches/test/images/thumb.jpeg",
                        "link": "https://polymaker.com/product/polydryer/",
                        "source": "Polymaker",
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

        async def get(self, url, params):
            assert url == "https://serpapi.com/search.json"
            assert params["engine"] == "google_images_light"
            assert params["q"] == "Polymaker PolyDryer box"
            assert params["api_key"] == "mock-private-serpapi-key"
            return FakeResponse()

    monkeypatch.setattr(lib, "get_serpapi_key", lambda: "mock-private-serpapi-key")
    monkeypatch.setattr(lib.httpx, "AsyncClient", FakeClient)
    lib._RESULTS.clear()
    result = await lib.search_images("Polymaker PolyDryer box", "serpapi")
    assert len(result["results"]) == 1
    item = result["results"][0]
    assert item["source"] == "Polymaker"
    assert item["source_url"] == "https://polymaker.com/product/polydryer/"
    assert lib.verify_result(item["id"])["image_url"] == "https://polymaker.com/images/polydryer.png"
    assert "mock-private-serpapi-key" not in str(result)


@pytest.mark.asyncio
async def test_ebay_filter_searches_only_ebay_listing_results(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "images_results": [
                    {
                        "title": "Used dryer box",
                        "original": "https://i.ebayimg.com/images/g/aaaa/s-l1600.jpg",
                        "thumbnail": "https://serpapi.com/searches/test/images/ebay.jpeg",
                        "link": "https://www.ebay.co.uk/itm/123456789",
                        "source": "eBay UK",
                    },
                    {
                        "title": "Unrelated non-eBay source",
                        "original": "https://example.org/photo.jpg",
                        "link": "https://example.org/not-an-ebay-listing",
                    },
                ]
            }

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params):
            assert url == "https://serpapi.com/search.json"
            assert params["engine"] == "google_images_light"
            assert params["q"] == "Polymaker dryer box site:ebay.co.uk"
            return FakeResponse()

    monkeypatch.setattr(lib, "get_serpapi_key", lambda: "mock-private-serpapi-key")
    monkeypatch.setattr(lib.httpx, "AsyncClient", FakeClient)
    lib._RESULTS.clear()
    result = await lib.search_images("Polymaker dryer box", "ebay")
    assert len(result["results"]) == 1
    assert result["results"][0]["source_url"] == "https://www.ebay.co.uk/itm/123456789"
    assert result["results"][0]["license"] == ""
    assert lib.verify_result(result["results"][0]["id"])["image_url"].startswith("https://i.ebayimg.com")


def test_serpapi_key_save_preserves_existing_serper_key(monkeypatch, tmp_path):
    settings = tmp_path / "library-image-search.yaml"
    settings.write_text("serper_key: old-serper-key\n", encoding="utf-8")
    monkeypatch.setattr(lib, "_DATA_FILE", settings)
    monkeypatch.delenv("HBC_IMAGE_SEARCH_SERPAPI_KEY", raising=False)
    lib.save_serpapi_key("new-serpapi-key")
    assert settings.stat().st_mode & 0o777 == 0o600
    assert lib.get_google_key() == "old-serper-key"
    assert lib.get_serpapi_key() == "new-serpapi-key"
    assert "new-serpapi-key" not in str(settings.stat())


def test_serper_save_preserves_serpapi_key(monkeypatch, tmp_path):
    settings = tmp_path / "library-image-search.yaml"
    settings.write_text("serpapi_key: keep-serpapi-key\n", encoding="utf-8")
    monkeypatch.setattr(lib, "_DATA_FILE", settings)
    monkeypatch.delenv("HBC_IMAGE_SEARCH_SERPER_KEY", raising=False)
    lib.save_google_key("second-provider-key")
    assert lib.get_serpapi_key() == "keep-serpapi-key"
    assert lib.get_google_key() == "second-provider-key"


@pytest.mark.asyncio
async def test_images_lite_uses_https_thumbnail_when_original_missing(monkeypatch):
    """SerpApi Light results can omit original (or return x-raw-image:// for PDF images)."""

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "images_results": [
                    {
                        "title": "Polymaker product",
                        "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=example",
                        "link": "https://polymaker.com/product/",
                        "source": "Polymaker",
                    },
                    {
                        "title": "Unsupported original image reference",
                        "original": "x-raw-image:///testimage",
                        "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=second",
                        "link": "https://example.com/product.pdf",
                        "source": "PDF",
                    },
                ]
            }

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params):
            assert params["engine"] == "google_images_light"
            return FakeResponse()

    monkeypatch.setattr(lib, "get_serpapi_key", lambda: "mock-private-serpapi-key")
    monkeypatch.setattr(lib.httpx, "AsyncClient", FakeClient)
    lib._RESULTS.clear()
    results = (await lib.search_images("Polymaker product", "serpapi"))["results"]
    assert len(results) == 2
    assert results[0]["source_url"] == "https://polymaker.com/product/"
    assert lib.verify_result(results[0]["id"])["image_url"].startswith("https://encrypted-tbn0.gstatic.com/")
    assert lib.verify_result(results[1]["id"])["image_url"].startswith("https://encrypted-tbn0.gstatic.com/")
