"""Safe SerpApi image search for catalogue photos and eBay UK listings.

Use Google Images Lite for product photos and eBay Search for listing main images.
Full eBay listing photo galleries are fetched only after an explicit user action.
Signed image selections are checked before safe, public HTTPS downloads.
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import io
import ipaddress
import json
import os
import re
import secrets
import socket
import tempfile
import time
from pathlib import Path
from typing import Any, cast
from urllib.parse import urljoin, urlsplit

import aiohttp
import httpx
import yaml
from aiohttp.abc import AbstractResolver, ResolveResult
from loguru import logger
from PIL import Image, ImageOps, UnidentifiedImageError

_DATA_FILE = Path("/app/data/library_image_search.yaml")
_SIGNING_KEY = secrets.token_bytes(32)  # Tokens expire on container restart.
_MAX_DOWNLOAD = 8 * 1024 * 1024
_MAX_PIXELS = 24_000_000
_RESULTS: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}
_EBAY_GALLERIES: dict[str, tuple[float, dict[str, Any]]] = {}


class ImageLibraryError(ValueError):
    """A user-safe error from an image provider or download."""


def get_serpapi_key() -> str:
    """Retrieve the one search-provider API key, never returning it to the browser."""
    configured = os.getenv("HBC_IMAGE_SEARCH_SERPAPI_KEY", "").strip()
    if configured:
        return configured
    if not _DATA_FILE.is_file():
        return ""
    try:
        content = yaml.safe_load(_DATA_FILE.read_text(encoding="utf-8")) or {}
        return str(content.get("serpapi_key", "")).strip() if isinstance(content, dict) else ""
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Unable to read image search provider settings: {}", type(exc).__name__)
        return ""


def has_serpapi_key() -> bool:
    return bool(get_serpapi_key())


def save_serpapi_key(key: str) -> None:
    """Save the SerpApi key; leave any legacy settings intact for rollback."""
    if os.getenv("HBC_IMAGE_SEARCH_SERPAPI_KEY"):
        raise ImageLibraryError("SerpApi key is managed by the Docker environment.")
    if len(key) > 512:
        raise ImageLibraryError("Provider key is too long.")
    _DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, str] = {}
    if _DATA_FILE.is_file():
        try:
            loaded = yaml.safe_load(_DATA_FILE.read_text(encoding="utf-8")) or {}
            if not isinstance(loaded, dict):
                raise ImageLibraryError("Existing image-search settings are invalid.")
            data = {str(k): str(v) for k, v in loaded.items()}
        except (OSError, yaml.YAMLError) as exc:
            raise ImageLibraryError("Unable to read existing image-search settings.") from exc
    if key.strip():
        data["serpapi_key"] = key.strip()
    else:
        data.pop("serpapi_key", None)

    descriptor, temporary = tempfile.mkstemp(prefix=".library-image-search-", dir=_DATA_FILE.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as dest:
            os.chmod(temporary, 0o600)
            yaml.safe_dump(data, dest)
            dest.flush()
            os.fsync(dest.fileno())
        os.replace(temporary, _DATA_FILE)
        _DATA_FILE.chmod(0o600)
    finally:
        Path(temporary).unlink(missing_ok=True)
    _RESULTS.clear()


def _valid_public_url(url: Any) -> str:
    """Reject malformed URLs; IP and DNS address checks happen before *every* fetch."""
    if not isinstance(url, str) or len(url) > 2048:
        return ""
    try:
        p = urlsplit(url)
        if p.scheme != "https" or not p.hostname or p.username or p.password:
            return ""
        if p.port not in (None, 443):
            return ""
        host = p.hostname.strip(".").lower()
        if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal", ".lan", ".arpa")):
            return ""
        try:
            if not ipaddress.ip_address(host).is_global:
                return ""
        except ValueError:
            pass
    except ValueError:
        return ""
    return url


def _sign_result(value: dict[str, Any]) -> str:
    value = {key: value.get(key) for key in ("image_url", "thumbnail_url", "source_url", "license", "attribution")}
    value["expires"] = int(time.time()) + 20 * 60
    content = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
    signature = hmac.digest(_SIGNING_KEY, content, "sha256")
    return base64.urlsafe_b64encode(content + signature).decode().rstrip("=")


def verify_result(token: str) -> dict[str, Any]:
    if not token or len(token) > 12000:
        raise ImageLibraryError("Invalid library image selection.")
    try:
        padded = token + "=" * (-len(token) % 4)
        decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
        data, tag = decoded[:-32], decoded[-32:]
        if len(tag) != 32 or not hmac.compare_digest(hmac.digest(_SIGNING_KEY, data, "sha256"), tag):
            raise ValueError("Invalid signature")
        item = json.loads(data)
        if not isinstance(item, dict) or not isinstance(item.get("expires"), int):
            raise ValueError("Invalid payload")
        if item["expires"] < time.time():
            raise ImageLibraryError("Search results expired. Search again and reselect the image.")
        if not _valid_public_url(item.get("image_url")):
            raise ImageLibraryError("The selected image URL cannot be imported.")
        return item
    except ImageLibraryError:
        raise
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ImageLibraryError("Invalid library image selection.") from exc


async def search_images(query: str, provider: str = "serpapi") -> dict[str, Any]:
    """Search exactly one of two SerpApi engines on explicit user request."""
    q = " ".join(query.split())
    if not q or len(q) > 180:
        raise ImageLibraryError("Enter a product name or model number (maximum 180 characters).")
    if provider not in ("serpapi", "ebay"):
        raise ImageLibraryError("Unsupported image search provider.")
    if not has_serpapi_key():
        raise ImageLibraryError("SerpApi key required. Configure it before searching.")

    cache_key = (provider, q.casefold())
    cached = _RESULTS.get(cache_key)
    if cached and time.monotonic() - cached[0] < 600:
        return {"provider": provider, "query": q, "results": cached[1]}

    params = (
        {
            "engine": "google_images_light",
            "q": q,
            "gl": "uk",
            "hl": "en",
            "google_domain": "google.co.uk",
        }
        if provider == "serpapi"
        else {"engine": "ebay", "_nkw": q, "ebay_domain": "ebay.co.uk"}
    )
    params["api_key"] = get_serpapi_key()
    async with httpx.AsyncClient(timeout=22, follow_redirects=False, trust_env=False) as client:
        try:
            response = await client.get("https://serpapi.com/search.json", params=params)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ImageLibraryError("Unexpected SerpApi response.")
            if payload.get("error"):
                raise ImageLibraryError("SerpApi rejected the search. Check the API key and remaining free searches.")
        except ImageLibraryError:
            raise
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("Library {} search failed: {}", provider, type(exc).__name__)
            raise ImageLibraryError("Image search unavailable. Check SerpApi credits and retry.") from exc

    raw_results = payload.get("images_results" if provider == "serpapi" else "organic_results", [])
    if not isinstance(raw_results, list):
        raise ImageLibraryError("SerpApi returned an unexpected image-search result.")

    selected: list[dict[str, Any]] = []
    for entry in raw_results[:75]:
        if not isinstance(entry, dict):
            continue
        if provider == "ebay":
            # eBay Search provides the *listing main image*, without needing the
            # individual listing page or a separate product-details API request.
            listing_id = str(entry.get("product_id") or "")
            if not re.fullmatch(r"[0-9]{9,15}", listing_id):
                continue
            source_url = _valid_public_url(entry.get("link"))
            listing_host = (urlsplit(source_url).hostname or "").lower()
            if listing_host not in {"ebay.co.uk", "www.ebay.co.uk", "ebay.com", "www.ebay.com"}:
                continue
            original = _valid_public_url(entry.get("thumbnail"))
            thumbnail = original
            source_name = "eBay UK"
        else:
            listing_id = ""
            original = _valid_public_url(entry.get("original"))
            thumbnail = _valid_public_url(entry.get("thumbnail"))
            original = original or thumbnail
            source_url = _valid_public_url(entry.get("link"))
            source_name = str(entry.get("source") or "")[:80] or (urlsplit(original).hostname or "")
        if not original:
            continue
        signed = _sign_result(
            {
                "image_url": original,
                "thumbnail_url": thumbnail,
                "source_url": source_url,
                "license": "",
                "attribution": "",
            }
        )
        selected.append(
            {
                "id": signed,
                "thumbnail_url": thumbnail or original,
                "title": str(entry.get("title") or "Product photo")[:150],
                "source": source_name,
                "source_url": source_url or "",
                "license": "",
                "attribution": "",
                "rank": len(selected) + 1,
                "product_id": listing_id or None,
            }
        )
        if len(selected) >= 18:
            break
    if len(_RESULTS) >= 80:
        _RESULTS.clear()
    _RESULTS[cache_key] = (time.monotonic(), selected)
    return {"provider": provider, "query": q, "results": selected}


async def get_ebay_listing_photos(product_id: str) -> dict[str, Any]:
    """Fetch the entire listing gallery only if the user clicks View listing photos.

    One SerpApi eBay Product lookup is charged separately from the main search;
    successful results are cached for ten minutes.
    """
    if not re.fullmatch(r"[0-9]{9,15}", product_id):
        raise ImageLibraryError("Invalid eBay listing number.")
    if not has_serpapi_key():
        raise ImageLibraryError("SerpApi key required. Configure it before searching.")
    cached = _EBAY_GALLERIES.get(product_id)
    if cached and time.monotonic() - cached[0] < 600:
        return cached[1]

    async with httpx.AsyncClient(timeout=22, follow_redirects=False, trust_env=False) as client:
        try:
            response = await client.get(
                "https://serpapi.com/search.json",
                params={
                    "engine": "ebay_product",
                    "product_id": product_id,
                    "ebay_domain": "ebay.co.uk",
                    "api_key": get_serpapi_key(),
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ImageLibraryError("Unexpected eBay product response.")
            if payload.get("error"):
                raise ImageLibraryError("SerpApi could not retrieve this eBay listing's gallery.")
        except ImageLibraryError:
            raise
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("eBay listing gallery request failed: {}", type(exc).__name__)
            raise ImageLibraryError("Listing photos were unavailable. Try again later.") from exc

    product = payload.get("product_results") or {}
    if not isinstance(product, dict) or str(product.get("product_id") or "") != product_id:
        raise ImageLibraryError("eBay returned no matching product details.")
    title = str(product.get("title") or "eBay product")[:150]
    source_url = f"https://www.ebay.co.uk/itm/{product_id}"
    media = product.get("media") or []
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in media[:40] if isinstance(media, list) else []:
        if not isinstance(item, dict) or item.get("type") != "image":
            continue
        images = item.get("image") or []
        if not isinstance(images, list):
            continue
        sizes: list[tuple[int, str]] = []
        for candidate in images:
            if not isinstance(candidate, dict):
                continue
            link = _valid_public_url(candidate.get("link"))
            if not link:
                continue
            meta = candidate.get("size") or {}
            width = meta.get("width", 0) if isinstance(meta, dict) else 0
            sizes.append((width if isinstance(width, int) else 0, link))
        if not sizes:
            continue
        sizes.sort(key=lambda x: x[0])
        original = sizes[-1][1]
        thumbnail = min(sizes, key=lambda x: abs(x[0] - 500))[1]
        if original in seen:
            continue
        seen.add(original)
        results.append(
            {
                "id": _sign_result(
                    {
                        "image_url": original,
                        "thumbnail_url": thumbnail,
                        "source_url": source_url,
                        "license": "",
                        "attribution": "",
                    }
                ),
                "thumbnail_url": thumbnail,
                "title": f"{title} — Photo {len(results) + 1}",
                "source": "eBay UK",
                "source_url": source_url,
                "license": "",
                "attribution": "",
                "rank": len(results) + 1,
                "product_id": product_id,
            }
        )
    result = {"product_id": product_id, "title": title, "results": results}
    if len(_EBAY_GALLERIES) >= 80:
        _EBAY_GALLERIES.clear()
    _EBAY_GALLERIES[product_id] = (time.monotonic(), result)
    return result


class _PublicResolver(AbstractResolver):
    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ) -> list[ResolveResult]:
        if not _valid_public_url(f"https://{host}/"):
            raise OSError("Private network hosts cannot be used for image downloads")
        info = await asyncio.get_running_loop().getaddrinfo(host, port, family=family, type=socket.SOCK_STREAM)
        addresses: list[ResolveResult] = []
        for ai_family, _type, proto, _canon, sockaddr in info:
            addr = cast(str, sockaddr[0])
            if not ipaddress.ip_address(addr).is_global:
                raise OSError("Image host resolves to a private network address")
            addresses.append(ResolveResult(hostname=host, host=addr, port=port, family=ai_family, proto=proto, flags=0))
        if not addresses:
            raise OSError("Unable to resolve image host")
        return addresses

    async def close(self) -> None:
        return None


async def _fetch_image(url: str) -> bytes:
    current = _valid_public_url(url)
    if not current:
        raise ImageLibraryError("Image source is not a public HTTPS address.")
    timeout = aiohttp.ClientTimeout(total=25, connect=9, sock_read=12)
    connector = aiohttp.TCPConnector(resolver=_PublicResolver(), use_dns_cache=False, force_close=True)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout, trust_env=False) as session:
        try:
            for _ in range(4):
                async with session.get(
                    current,
                    allow_redirects=False,
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; HomeboxCompanion/1.0)",
                        "Accept": "image/avif,image/webp,image/png,image/jpeg,image/gif,*/*;q=0.5",
                    },
                ) as response:
                    if response.status in (301, 302, 303, 307, 308):
                        dest = _valid_public_url(urljoin(current, response.headers.get("Location", "")))
                        if not dest:
                            raise ImageLibraryError("Image redirects to an unsafe or unsupported address.")
                        current = dest
                        continue
                    if response.status != 200:
                        raise ImageLibraryError(f"Image host returned HTTP {response.status}.")
                    mime = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                    if mime and mime not in (
                        "image/png",
                        "image/jpeg",
                        "image/webp",
                        "image/gif",
                        "application/octet-stream",
                    ):
                        raise ImageLibraryError("The source did not provide a supported image file.")
                    parts = []
                    length = 0
                    async for part in response.content.iter_chunked(64 * 1024):
                        length += len(part)
                        if length > _MAX_DOWNLOAD:
                            raise ImageLibraryError("The selected image exceeds the 8 MB limit.")
                        parts.append(part)
                    if not length:
                        raise ImageLibraryError("The selected image is empty.")
                    return b"".join(parts)
            raise ImageLibraryError("Too many redirects from the image host.")
        except (TimeoutError, aiohttp.ClientError, OSError) as exc:
            raise ImageLibraryError("Unable to retrieve the image from its source website.") from exc


def _flatten_transparency_to_white(image: Image.Image) -> Image.Image:
    """Return an opaque RGB photo, compositing actual alpha onto white.

    PNG/WebP RGBA images often have an alpha channel but no transparency
    entry in image.info. We must inspect alpha pixels, not rely on that
    metadata; otherwise convert("RGB") silently discards alpha and exposes
    invisible RGB colours as black or other unexpected backgrounds.

    Opaque RGB/JPEG images retain the existing RGB conversion path.
    """
    has_alpha = (
        "A" in image.getbands()
        or "a" in image.getbands()
        or "transparency" in image.info  # GIF/PNG palette or PNG RGB tRNS
    )
    if not has_alpha:
        return image.convert("RGB")

    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    if alpha.getextrema()[0] == 255:
        # An RGBA image whose pixels are all opaque needs no white compositing.
        return rgba.convert("RGB")

    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    return Image.alpha_composite(white, rgba).convert("RGB")


def _to_jpeg(content: bytes) -> bytes:
    """Re-encode imported library photographs as JPEG, with white behind real transparency."""
    try:
        with Image.open(io.BytesIO(content)) as original:
            if original.width * original.height > _MAX_PIXELS:
                raise ImageLibraryError("The selected image is too large to process safely.")
            original.seek(0)
            im = ImageOps.exif_transpose(original)
            im.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            im = _flatten_transparency_to_white(im)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=85, optimize=True)
            return buf.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise ImageLibraryError("The downloaded file was not a valid supported image.") from exc


async def download_selected_image(token: str) -> bytes:
    item = verify_result(token)
    try:
        original = await _fetch_image(item["image_url"])
    except ImageLibraryError as exc:
        alternate = item.get("thumbnail_url")
        if not alternate or alternate == item["image_url"]:
            raise exc
        original = await _fetch_image(alternate)
    return await asyncio.to_thread(_to_jpeg, original)
