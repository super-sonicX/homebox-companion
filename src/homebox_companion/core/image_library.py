"""Safe online image search and import for personal inventory cataloguing.

Google Images results are provided by the Serper API (not Google scraping).
Openverse offers freely licensed search results without an API key.
The server signs result references to prevent arbitrary fetch URLs from clients.
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import io
import ipaddress
import json
import os
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
Image.MAX_IMAGE_PIXELS = _MAX_PIXELS
_RESULTS: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}


class ImageLibraryError(ValueError):
    """A user-safe error from an image provider or download."""


def has_google_key() -> bool:
    return bool(get_google_key())


def get_google_key() -> str:
    configured = os.getenv("HBC_IMAGE_SEARCH_SERPER_KEY", "").strip()
    if configured:
        return configured
    if not _DATA_FILE.is_file():
        return ""
    try:
        content = yaml.safe_load(_DATA_FILE.read_text(encoding="utf-8")) or {}
        return str(content.get("serper_key", "")).strip() if isinstance(content, dict) else ""
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Unable to read image search provider settings: {}", type(exc).__name__)
        return ""


def save_google_key(key: str) -> None:
    if os.getenv("HBC_IMAGE_SEARCH_SERPER_KEY"):
        raise ImageLibraryError("Provider key is managed by the Docker environment.")
    if len(key) > 512:
        raise ImageLibraryError("Provider key is too long.")
    _DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".library-image-search-", dir=_DATA_FILE.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as dest:
            os.chmod(temporary, 0o600)
            yaml.safe_dump({"serper_key": key.strip()}, dest)
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


async def search_images(query: str, provider: str = "google") -> dict[str, Any]:
    q = " ".join(query.split())
    if not q or len(q) > 180:
        raise ImageLibraryError("Enter a product name or model number (maximum 180 characters).")
    if provider not in ("google", "openverse"):
        raise ImageLibraryError("Unsupported image search provider.")
    if provider == "google" and not has_google_key():
        raise ImageLibraryError(
            "Google image search requires a Serper API key. Configure it first or select Openverse."
        )

    cache_key = (provider, q.casefold())
    cached = _RESULTS.get(cache_key)
    if cached and time.monotonic() - cached[0] < 600:
        return {"provider": provider, "query": q, "results": cached[1]}

    async with httpx.AsyncClient(timeout=18, follow_redirects=False, trust_env=False) as client:
        try:
            if provider == "google":
                response = await client.post(
                    "https://google.serper.dev/images",
                    headers={"X-API-KEY": get_google_key(), "Content-Type": "application/json"},
                    json={"q": q, "num": 18, "gl": "gb", "hl": "en"},
                )
            else:
                response = await client.get(
                    "https://api.openverse.org/v1/images/",
                    params={"q": q, "page_size": 18, "page": 1},
                    headers={"User-Agent": "HomeboxCompanion-LibraryImages/1.0"},
                )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("Image library {} search failed: {}", provider, type(exc).__name__)
            raise ImageLibraryError("Image search was unavailable. Check provider credits or retry later.") from exc

    raw_results = payload.get("images", []) if provider == "google" else payload.get("results", [])
    if not isinstance(raw_results, list):
        raise ImageLibraryError("Image provider returned an unexpected response.")

    selected: list[dict[str, Any]] = []
    for index, entry in enumerate(raw_results[:40]):
        if not isinstance(entry, dict):
            continue
        original = _valid_public_url(entry.get("imageUrl") if provider == "google" else entry.get("url"))
        thumbnail = _valid_public_url(entry.get("thumbnailUrl") if provider == "google" else entry.get("thumbnail"))
        if not original:
            continue
        source_url = _valid_public_url(entry.get("link") if provider == "google" else entry.get("foreign_landing_url"))
        license_name = (entry.get("license") or "") if provider == "openverse" else ""
        attribution = (entry.get("attribution") or "") if provider == "openverse" else ""
        original_source = entry.get("domain") or entry.get("source") or ""
        if not isinstance(original_source, str):
            original_source = ""
        preview = thumbnail or original
        signed = _sign_result(
            {
                "image_url": original,
                "thumbnail_url": thumbnail,
                "source_url": source_url,
                "license": license_name,
                "attribution": attribution,
            }
        )
        selected.append(
            {
                "id": signed,
                "thumbnail_url": preview,
                "title": str(entry.get("title") or "Product photo")[:150],
                "source": original_source[:80] or urlsplit(original).hostname,
                "source_url": source_url or "",
                "license": license_name,
                "attribution": str(attribution)[:250],
                "rank": index + 1,
            }
        )
        if len(selected) >= 18:
            break
    if len(_RESULTS) >= 80:
        _RESULTS.clear()
    _RESULTS[cache_key] = (time.monotonic(), selected)
    return {"provider": provider, "query": q, "results": selected}


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


def _to_jpeg(content: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(content)) as original:
            if original.width * original.height > _MAX_PIXELS:
                raise ImageLibraryError("The selected image is too large to process safely.")
            original.seek(0)
            im = ImageOps.exif_transpose(original)
            im.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            if im.mode in ("RGBA", "LA", "P") and "transparency" in im.info:
                canvas = Image.new("RGB", im.size, "white")
                rgba = im.convert("RGBA")
                canvas.paste(rgba, mask=rgba.getchannel("A"))
                im = canvas
            else:
                im = im.convert("RGB")
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
