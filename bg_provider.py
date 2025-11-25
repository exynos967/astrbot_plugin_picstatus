from __future__ import annotations

import asyncio
import mimetypes
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

try:
    from astrbot.api import logger  # type: ignore
except Exception:  # pragma: no cover - fallback for local test env
    import logging

    logger = logging.getLogger("astrbot_plugin_picstatus")


ASSETS_PATH = Path(__file__).parent / "res" / "assets"
DEFAULT_BG_PATH = ASSETS_PATH / "default_bg.webp"
DEFAULT_TIMEOUT = 10


@dataclass
class BgBytesData:
    data: bytes
    mime: str


def _guess_mime_from_suffix(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    if mime:
        return mime
    if path.suffix.lower() == ".webp":
        return "image/webp"
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        return "image/jpeg"
    return "application/octet-stream"


async def _fetch_loli(timeout: int, proxy: str | None) -> Optional[BgBytesData]:
    url = "https://www.loliapi.com/acg/pe/"
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            proxy=proxy or None,
        ) as cli:
            resp = await cli.get(url)
            resp.raise_for_status()
            return BgBytesData(
                data=resp.content,
                mime=resp.headers.get("Content-Type") or "image/jpeg",
            )
    except Exception as e:
        logger.warning(f"fetch_loli failed: {e.__class__.__name__}: {e}")
        return None


async def _fetch_lolicon(timeout: int, proxy: str | None, r18_type: int) -> Optional[BgBytesData]:
    """Fetch one background from Lolicon (Pixiv). r18_type: 0=off,1=R18,2=mixed."""
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            proxy=proxy or None,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/119.0.0.0 Safari/537.36"
                ),
            },
        ) as cli:
            resp = await cli.get(
                "https://api.lolicon.app/setu/v2",
                params={
                    "num": 1,
                    "r18": max(0, min(2, int(r18_type))),
                    "proxy": "false",
                    "excludeAI": "true",
                },
            )
            data = resp.raise_for_status().json()
            payload = data.get("data") or []
            if not payload:
                return None
            url = payload[0].get("urls", {}).get("original")
            if not url:
                return None
            img_resp = await cli.get(
                url,
                headers={
                    "Referer": "https://www.pixiv.net/",
                },
            )
            img_resp.raise_for_status()
            return BgBytesData(
                data=img_resp.content,
                mime=img_resp.headers.get("Content-Type") or "image/jpeg",
            )
    except Exception as e:
        logger.warning(f"fetch_lolicon failed: {e.__class__.__name__}: {e}")
        return None


def _read_local(path: Path | None = None) -> Optional[BgBytesData]:
    p = path or DEFAULT_BG_PATH
    try:
        target = p
        if target.is_dir():
            candidates = [x for x in target.glob("*") if x.is_file()]
            if not candidates:
                target = DEFAULT_BG_PATH
            else:
                target = random.choice(candidates)
        data = target.read_bytes()
        mime = _guess_mime_from_suffix(target)
        return BgBytesData(data=data, mime=mime)
    except Exception as e:
        logger.warning(f"read_local failed: {e.__class__.__name__}: {e}")
        return None


async def _fetch_none() -> Optional[BgBytesData]:
    return _read_local(DEFAULT_BG_PATH)


async def _fetch_provider(
    provider: str,
    local_path: Path | None,
    timeout: int,
    proxy: str | None,
    r18_type: int,
) -> Optional[BgBytesData]:
    name = (provider or "").lower()
    if name == "loli":
        return await _fetch_loli(timeout, proxy)
    if name == "lolicon":
        return await _fetch_lolicon(timeout, proxy, r18_type)
    if name == "local":
        return _read_local(local_path)
    if name == "none":
        return await _fetch_none()
    # unknown provider -> fallback to local
    return _read_local(local_path)


class BgPreloader:
    def __init__(
        self,
        provider: str,
        local_path: Path | None,
        timeout: int,
        proxy: str | None,
        preload_count: int,
        r18_type: int,
    ):
        self.provider = provider
        self.local_path = local_path
        self.timeout = timeout
        self.proxy = proxy
        self.preload_count = max(1, preload_count)
        self.r18_type = r18_type
        self.queue: asyncio.Queue[BgBytesData] = asyncio.Queue()
        self._preload_task: asyncio.Task | None = None

    async def _fill_queue(self):
        try:
            while self.queue.qsize() < self.preload_count:
                bg = await _fetch_provider(
                    self.provider,
                    self.local_path,
                    self.timeout,
                    self.proxy,
                    self.r18_type,
                )
                if not bg:
                    break
                await self.queue.put(bg)
        except Exception:
            logger.exception("BgPreloader fill_queue failed")
        finally:
            self._preload_task = None

    def _ensure_preload(self):
        if self._preload_task and not self._preload_task.done():
            return
        self._preload_task = asyncio.create_task(self._fill_queue())

    async def get(self) -> BgBytesData:
        # ensure some items are loading
        self._ensure_preload()
        try:
            return self.queue.get_nowait()
        except asyncio.QueueEmpty:
            bg = await _fetch_provider(
                self.provider,
                self.local_path,
                self.timeout,
                self.proxy,
                self.r18_type,
            )
            if bg:
                return bg
            # final fallback
            fallback = _read_local(DEFAULT_BG_PATH)
            assert fallback, "Default background missing"
            return fallback


_cached_preloader: BgPreloader | None = None
_cached_key: tuple | None = None


def _get_preloader(
    provider: str,
    local_path: Path | None,
    timeout: int,
    proxy: str | None,
    preload_count: int,
    r18_type: int,
) -> BgPreloader:
    global _cached_preloader, _cached_key
    key = (provider, str(local_path) if local_path else "", timeout, proxy or "", preload_count, r18_type)
    if _cached_preloader is None or _cached_key != key:
        _cached_preloader = BgPreloader(
            provider=provider,
            local_path=local_path,
            timeout=timeout,
            proxy=proxy,
            preload_count=preload_count,
            r18_type=r18_type,
        )
        _cached_key = key
    return _cached_preloader


async def resolve_background(
    prefer_bytes: bytes | None = None,
    provider: str = "loli",
    local_path: Path | None = None,
    config: dict | None = None,
) -> BgBytesData:
    """
    Resolve background with priority:
    1) prefer_bytes (如消息自带图片)
    2) 配置/参数指定的 provider (loli/lolicon/local/none)
    3) 默认内置背景
    """
    if prefer_bytes:
        return BgBytesData(prefer_bytes, "image")

    cfg = config or {}
    timeout = int(cfg.get("bg_req_timeout", DEFAULT_TIMEOUT))
    proxy = cfg.get("bg_proxy") or None
    preload_count = int(cfg.get("bg_preload_count", 1))
    r18_type = int(cfg.get("bg_lolicon_r18_type", 0))
    preloader = _get_preloader(provider, local_path, timeout, proxy, preload_count, r18_type)
    return await preloader.get()
