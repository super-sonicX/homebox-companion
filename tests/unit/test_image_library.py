"""Library image search, token integrity, and SSRF regression checks."""

import base64
import io

import pytest
import yaml
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


@pytest.mark.parametrize("provider", ["google", "openverse", "serper", "shopping"])
@pytest.mark.asyncio
async def test_only_google_images_lite_and_ebay_are_enabled(provider):
    with pytest.raises(lib.ImageLibraryError, match="Unsupported image search provider"):
        await lib.search_images("Polymaker dryer", provider)


def _png_or_webp_with_alpha(fmt: str) -> bytes:
    img = Image.new("RGBA", (120, 60))
    img.paste((210, 30, 30, 255), (0, 0, 40, 60))
    img.paste((0, 0, 255, 128), (40, 0, 80, 60))
    img.paste((30, 150, 60, 0), (80, 0, 120, 60))
    buf = io.BytesIO()
    img.save(buf, format=fmt, **({"lossless": True} if fmt == "WEBP" else {}))
    return buf.getvalue()


def _photo_at(jpg: bytes, x: int, y: int) -> tuple[int, int, int]:
    with Image.open(io.BytesIO(jpg)) as photo:
        assert photo.format == "JPEG"
        assert photo.mode == "RGB"
        pixel = photo.getpixel((x, y))
        assert isinstance(pixel, tuple) and len(pixel) == 3
        return (int(pixel[0]), int(pixel[1]), int(pixel[2]))


def _rough_rgb(actual: tuple[int, int, int], expected: tuple[int, int, int], tolerance: int = 10) -> None:
    assert all(abs(a - b) <= tolerance for a, b in zip(actual, expected, strict=True)), (
        actual,
        expected,
    )


@pytest.mark.parametrize("fmt", ["PNG", "WEBP"])
def test_transparent_rgba_imports_flatten_on_white_even_without_transparency_info(fmt: str):
    source = _png_or_webp_with_alpha(fmt)
    with Image.open(io.BytesIO(source)) as original:
        assert original.mode == "RGBA"
        # In normal PNG RGBA, the alpha channel is present WITHOUT info["transparency"].
        assert "transparency" not in original.info
    jpeg = lib._to_jpeg(source)
    _rough_rgb(_photo_at(jpeg, 20, 30), (210, 30, 30))
    _rough_rgb(_photo_at(jpeg, 60, 30), (127, 127, 255))
    _rough_rgb(_photo_at(jpeg, 100, 30), (255, 255, 255))


@pytest.mark.parametrize("fmt", ["PNG", "GIF"])
def test_transparent_palette_imports_flatten_onto_white(fmt: str):
    img = Image.new("P", (100, 48), 0)
    img.putpalette([4, 6, 8, 200, 40, 15] + [0] * 762)
    img.paste(1, (50, 0, 100, 48))
    raw = io.BytesIO()
    img.save(raw, format=fmt, transparency=0)
    jpeg = lib._to_jpeg(raw.getvalue())
    _rough_rgb(_photo_at(jpeg, 20, 24), (255, 255, 255))
    _rough_rgb(_photo_at(jpeg, 80, 24), (200, 40, 15))


def test_rgb_png_transparency_key_is_flattened_to_white():
    img = Image.new("RGB", (100, 50), (0, 0, 250))
    img.paste((80, 160, 30), (50, 0, 100, 50))
    raw = io.BytesIO()
    img.save(raw, format="PNG", transparency=(0, 0, 250))
    with Image.open(io.BytesIO(raw.getvalue())) as source:
        assert source.mode == "RGB"
        assert "transparency" in source.info
    jpeg = lib._to_jpeg(raw.getvalue())
    _rough_rgb(_photo_at(jpeg, 20, 25), (255, 255, 255))
    _rough_rgb(_photo_at(jpeg, 80, 25), (80, 160, 30))


def test_grayscale_with_alpha_is_flattened_to_white():
    img = Image.new("LA", (100, 50), (30, 0))
    img.paste((90, 255), (50, 0, 100, 50))
    raw = io.BytesIO()
    img.save(raw, format="PNG")
    jpeg = lib._to_jpeg(raw.getvalue())
    _rough_rgb(_photo_at(jpeg, 20, 25), (255, 255, 255))
    _rough_rgb(_photo_at(jpeg, 80, 25), (90, 90, 90))


def test_opaque_rgb_jpeg_import_preserves_existing_conversion():
    img = Image.new("RGB", (96, 64), (60, 120, 180))
    raw = io.BytesIO()
    img.save(raw, format="JPEG", quality=95)
    # The already deployed JPEG pipeline is precisely: EXIF transpose, resize,
    # RGB conversion, then JPEG quality 85. Opaque photos should retain that.
    with Image.open(io.BytesIO(raw.getvalue())) as source:
        from PIL import ImageOps

        old = ImageOps.exif_transpose(source)
        old.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        baseline = io.BytesIO()
        old.convert("RGB").save(baseline, format="JPEG", quality=85, optimize=True)
    assert lib._to_jpeg(raw.getvalue()) == baseline.getvalue()


def test_fully_opaque_rgba_skips_white_compositing():
    img = Image.new("RGBA", (16, 12), (25, 70, 140, 255))
    flattened = lib._flatten_transparency_to_white(img)
    assert flattened.mode == "RGB"
    assert flattened.getpixel((3, 4)) == (25, 70, 140)


@pytest.mark.asyncio
async def test_both_provider_import_actions_use_white_flattened_jpeg(monkeypatch):
    raw = _png_or_webp_with_alpha("PNG")
    calls: list[str] = []

    async def fetch_image(url: str) -> bytes:
        calls.append(url)
        return raw

    monkeypatch.setattr(lib, "_fetch_image", fetch_image)
    for provider in ("google-lite", "ebay-main-image"):
        token = lib._sign_result(_example(image_url=f"https://example.org/{provider}.png"))
        jpeg = await lib.download_selected_image(token)
        _rough_rgb(_photo_at(jpeg, 100, 30), (255, 255, 255))
    assert calls == [
        "https://example.org/google-lite.png",
        "https://example.org/ebay-main-image.png",
    ]


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
async def test_ebay_search_returns_listing_main_image_without_extra_api_request(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "organic_results": [
                    {
                        "product_id": "388216346120",
                        "title": "PolyDryer Box Only",
                        "thumbnail": "https://i.ebayimg.com/images/g/AAAA/s-l500.webp",
                        "link": "https://www.ebay.co.uk/itm/388216346120",
                        "price": "£25.00",
                    },
                    {
                        "product_id": "invalid",
                        "title": "Invalid product ID",
                        "thumbnail": "https://i.ebayimg.com/images/g/BBBB/s-l500.webp",
                        "link": "https://www.ebay.co.uk/itm/invalid",
                    },
                    {
                        "product_id": "257768939026",
                        "title": "Wrong site",
                        "thumbnail": "https://i.ebayimg.com/images/g/CCCC/s-l500.webp",
                        "link": "https://other.example.net/itm/257768939026",
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
            assert params == {
                "engine": "ebay",
                "_nkw": "Polymaker dryer box",
                "ebay_domain": "ebay.co.uk",
                "api_key": "mock-private-serpapi-key",
            }
            return FakeResponse()

    monkeypatch.setattr(lib, "get_serpapi_key", lambda: "mock-private-serpapi-key")
    monkeypatch.setattr(lib.httpx, "AsyncClient", FakeClient)
    lib._RESULTS.clear()
    result = await lib.search_images("Polymaker dryer box", "ebay")
    assert len(result["results"]) == 1
    item = result["results"][0]
    assert item["title"] == "PolyDryer Box Only"
    assert item["product_id"] == "388216346120"
    assert item["source_url"] == "https://www.ebay.co.uk/itm/388216346120"
    assert item["license"] == ""
    assert lib.verify_result(item["id"])["image_url"] == "https://i.ebayimg.com/images/g/AAAA/s-l500.webp"


@pytest.mark.asyncio
async def test_ebay_product_gallery_only_runs_after_explicit_request_and_caches(monkeypatch):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "product_results": {
                    "product_id": "388216346120",
                    "title": "PolyDryer Box Only",
                    "media": [
                        {
                            "type": "image",
                            "image": [
                                {
                                    "size": {"width": 140, "height": 140},
                                    "link": "https://i.ebayimg.com/images/g/AAAA/s-l140.png",
                                },
                                {
                                    "size": {"width": 500, "height": 500},
                                    "link": "https://i.ebayimg.com/images/g/AAAA/s-l500.png",
                                },
                                {
                                    "size": {"width": 960, "height": 960},
                                    "link": "https://i.ebayimg.com/images/g/AAAA/s-l960.png",
                                },
                            ],
                        },
                        {
                            "type": "image",
                            "image": [
                                {
                                    "size": {"width": 500, "height": 500},
                                    "link": "https://i.ebayimg.com/images/g/BBBB/s-l500.png",
                                },
                            ],
                        },
                        {"type": "video", "link": "https://example.org/video"},
                    ],
                }
            }

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params):
            calls.append(params)
            assert url == "https://serpapi.com/search.json"
            assert params == {
                "engine": "ebay_product",
                "product_id": "388216346120",
                "ebay_domain": "ebay.co.uk",
                "api_key": "mock-private-serpapi-key",
            }
            return FakeResponse()

    monkeypatch.setattr(lib, "get_serpapi_key", lambda: "mock-private-serpapi-key")
    monkeypatch.setattr(lib.httpx, "AsyncClient", FakeClient)
    lib._EBAY_GALLERIES.clear()
    result = await lib.get_ebay_listing_photos("388216346120")
    assert result["product_id"] == "388216346120"
    assert len(result["results"]) == 2
    assert lib.verify_result(result["results"][0]["id"])["image_url"].endswith("/s-l960.png")
    assert result["results"][0]["thumbnail_url"].endswith("/s-l500.png")
    assert result["results"][1]["source_url"] == "https://www.ebay.co.uk/itm/388216346120"
    cached = await lib.get_ebay_listing_photos("388216346120")
    assert cached == result
    assert len(calls) == 1


@pytest.mark.parametrize("item_number", ["", "../admin", "123", "https://ebay.co.uk/itm/388216346120"])
@pytest.mark.asyncio
async def test_ebay_gallery_rejects_invalid_item_numbers_before_provider_call(item_number):
    with pytest.raises(lib.ImageLibraryError, match="Invalid eBay listing number"):
        await lib.get_ebay_listing_photos(item_number)


def test_serpapi_key_save_preserves_existing_serper_key(monkeypatch, tmp_path):
    settings = tmp_path / "library-image-search.yaml"
    settings.write_text("serper_key: old-serper-key\n", encoding="utf-8")
    monkeypatch.setattr(lib, "_DATA_FILE", settings)
    monkeypatch.delenv("HBC_IMAGE_SEARCH_SERPAPI_KEY", raising=False)
    lib.save_serpapi_key("new-serpapi-key")
    assert settings.stat().st_mode & 0o777 == 0o600
    assert yaml.safe_load(settings.read_text())["serper_key"] == "old-serper-key"
    assert lib.get_serpapi_key() == "new-serpapi-key"
    assert "new-serpapi-key" not in str(settings.stat())


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



def test_importing_catalogue_images_does_not_change_pillow_process_wide_limits():
    """A catalogue import cannot lower the image limit for unrelated camera captures."""
    import os
    import subprocess
    import sys

    code = (
        "from PIL import Image; "
        "Image.MAX_IMAGE_PIXELS = 90_000_000; "
        "from homebox_companion.core import image_library; "
        "assert Image.MAX_IMAGE_PIXELS == 90_000_000"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=10,
        env=os.environ.copy(),
        check=False,
    )
    assert result.returncode == 0, result.stderr
