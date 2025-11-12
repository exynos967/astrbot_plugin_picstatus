from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
try:
    from astrbot.api import logger  # type: ignore
except Exception:  # pragma: no cover - fallback for local test env
    import logging

    logger = logging.getLogger("picstatus")


ASSETS_PATH = Path(__file__).parent / "res" / "assets"
DEFAULT_BG_PATH = ASSETS_PATH / "default_bg.webp"


@dataclass
class BgBytesData:
    data: bytes
    mime: str


async def fetch_loli() -> Optional[BgBytesData]:
    """Fetch one background from loliapi.

    API: https://www.loliapi.com/acg/pe/
    Returns None on error.
    """
    url = "https://www.loliapi.com/acg/pe/"
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as cli:
            resp = await cli.get(url)
            resp.raise_for_status()
            return BgBytesData(
                data=resp.content,
                mime=resp.headers.get("Content-Type") or "image/jpeg",
            )
    except Exception as e:
        logger.warning(f"fetch_loli failed: {e.__class__.__name__}: {e}")
        return None


def read_local(path: Path | None = None) -> Optional[BgBytesData]:
    p = path or DEFAULT_BG_PATH
    try:
        data = p.read_bytes()
        mime = "image/webp" if p.suffix.lower() == ".webp" else "image/jpeg"
        return BgBytesData(data=data, mime=mime)
    except Exception as e:
        logger.warning(f"read_local failed: {e.__class__.__name__}: {e}")
        return None


async def resolve_background(
    prefer_bytes: bytes | None = None,
    provider: str = "loli",
    local_path: Path | None = None,
) -> BgBytesData:
    """Resolve background with priority: prefer_bytes -> provider(loli/local) -> default.
    """
    if prefer_bytes:
        return BgBytesData(prefer_bytes, "image")

    if provider.lower() == "loli":
        if bg := await fetch_loli():
            return bg
        # fallback to local
        if bg := read_local(local_path):
            return bg
    elif provider.lower() == "local":
        if bg := read_local(local_path):
            return bg

    # final fallback
    bg = read_local()
    assert bg, "Default background missing"
    return bg
