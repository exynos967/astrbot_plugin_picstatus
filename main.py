from __future__ import annotations
from pathlib import Path
from typing import Final
from io import BytesIO
from PIL import Image
import uuid

import astrbot.api.message_components as Comp
import httpx
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .bg_provider import resolve_background
from .collectors import collect_all
from .utils import ensure_dir


PLUGIN_NAME: Final[str] = "astrbot_plugin_picstatus"
ALIASES: Final[set[str]] = {"状态", "zt", "yxzt", "status", "运行状态"}
CACHE_DIR = Path(__file__).parent / ".cache"


@register(
	PLUGIN_NAME,
	"薄暝",
	"以图片形式显示当前设备的运行状态",
	"1.0.1",
)
class PicStatusPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        ensure_dir(CACHE_DIR)
        # 统一从插件配置读取，避免依赖环境变量
        self.config = config or context.get_config() or {}

    async def initialize(self):
        logger.info("PicStatus plugin initialized")

    @filter.command("运行状态", alias=ALIASES)
    async def cmd_status(self, event: AstrMessageEvent):
        """生成并发送当前服务器运行状态图片"""
        # t2i_error 用於標記 AstrBot t2i 渲染階段的錯誤，使外層錯誤處理可以給出更精準提示。
        t2i_error: Exception | None = None
        try:
            collected = await collect_all()
            collected.setdefault("ps_version", "v1.0.0")
            # Provide header bots info for template compatibility
            try:
                self_id = event.get_self_id()
                adapter = (event.get_platform_name() or "AstrBot")

                # 1) 头像右侧文字：留空使用默认 "AstrBot"，填写则使用用户配置
                cfg = getattr(self, "config", None) or {}
                bot_nick: str = "AstrBot"
                if hasattr(cfg, "get"):
                    raw = cfg.get("avatar_text")
                    if isinstance(raw, str):
                        raw = raw.strip()
                        if raw:
                            bot_nick = raw

                bots = [
                    {
                        "self_id": self_id,
                        "nick": bot_nick,
                        "adapter": adapter,
                        "bot_connected": collected.get("bot_run_time", ""),
                        "msg_rec": 0,
                        "msg_sent": 0,
                    }
                ]
            except Exception:
                bots = []
            collected.setdefault("bots", bots)

            # prefer user image in message chain
            bg_bytes = None
            try:
                for seg in event.get_messages():
                    if isinstance(seg, Comp.Image):
                        f = getattr(seg, "file", None) or ""
                        if isinstance(f, str) and f.startswith(("http://", "https://")):
                            async with httpx.AsyncClient(
                                follow_redirects=True, timeout=5
                            ) as cli:
                                r = await cli.get(f)
                                r.raise_for_status()
                                bg_bytes = r.content
                                break
            except Exception:
                pass

            provider = (
                self.config.get("bg_provider")
                or "loli"
            )
            local_path = (
                self.config.get("bg_local_path")
                or ""
            )
            resolved = await resolve_background(
                prefer_bytes=bg_bytes,
                provider=provider,
                local_path=Path(local_path) if local_path else None,
                config=self.config,
            )
            # Only use AstrBot t2i path
            try:
                from .t2i_renderer import build_default_html

                # 尝试获取 Bot 头像：先用配置的本地/URL，其次自动推断 Bot 自己头像
                avatar_bytes = None
                avatar_url = None
                # 配置优先：本地路径
                avatar_local_path = self.config.get("avatar_local_path")
                use_local_avatar = bool(self.config.get("avatar_use_local", True))
                if use_local_avatar and avatar_local_path:
                    try:
                        avatar_bytes = Path(avatar_local_path).read_bytes()
                    except Exception as e:
                        logger.warning(f"PicStatus: 读取本地头像失败 {avatar_local_path}: {e}")
                # 配置优先：URL
                if avatar_bytes is None:
                    cfg_url = self.config.get("avatar_url")
                    if isinstance(cfg_url, str) and cfg_url.strip():
                        avatar_url = cfg_url.strip()
                # 默认使用 Bot 自己头像
                if avatar_bytes is None and avatar_url is None:
                    try:
                        if "qq" in adapter.lower() or "aiocqhttp" in adapter.lower():
                            avatar_url = f"https://q1.qlogo.cn/g?b=qq&nk={self_id}&s=640"
                    except Exception:
                        pass
                if avatar_bytes is None and avatar_url:
                    try:
                        async with httpx.AsyncClient(
                            follow_redirects=True, timeout=5
                        ) as cli:
                            r = await cli.get(avatar_url)
                            r.raise_for_status()
                            avatar_bytes = r.content
                    except Exception as e:
                        logger.warning(f"PicStatus: 获取头像失败 {avatar_url}: {e}")
                        avatar_bytes = None

                html = build_default_html(
                    collected, resolved.data, resolved.mime, avatar_bytes=avatar_bytes
                )
                image_to_send: str | None = None
                try:
                    image_to_send = await self._render_with_playwright(html)
                    logger.info("PicStatus: Playwright local render used")
                except Exception as e:
                    logger.warning(f"PicStatus: Playwright render failed, fallback to t2i: {e}")

                if not image_to_send:
                    options = {"type": "jpeg", "quality": 100, "full_page": False}
                    img_path = await self.html_render(html, {}, return_url=False, options=options)
                    image_to_send = img_path
                    logger.info("PicStatus: AstrBot t2i renderer used")
            except Exception as e:
                t2i_error = e
                logger.warning(f"PicStatus: AstrBot t2i renderer failed, reason: {e}")
        except Exception:
            logger.exception("生成运行状态图片失败")
            msg = "获取运行状态图片失败，请检查后台输出"
            if t2i_error:
                msg += "（AstrBot t2i 未就绪/模板渲染失败）"
            yield event.plain_result(msg)
            return

        image_to_send = self._crop_whitespace(image_to_send) or image_to_send
        yield event.image_result(image_to_send)

    async def _render_with_playwright(self, html: str) -> str:
        from playwright.async_api import async_playwright

        out_path = CACHE_DIR / f"picstatus_{uuid.uuid4().hex}.jpeg"
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            )
            page = await browser.new_page(viewport={"width": 760, "height": 2000})
            await page.set_content(html, wait_until="networkidle")
            try:
                await page.wait_for_selector(".main-background", timeout=5000)
                elem = await page.query_selector(".main-background")
            except Exception:
                elem = None
            if elem:
                await elem.screenshot(path=str(out_path), type="jpeg", quality=95)
            else:
                await page.screenshot(path=str(out_path), type="jpeg", quality=95, full_page=True)
            await browser.close()
        return str(out_path)

    async def terminate(self):
        logger.info("PicStatus plugin terminated")

    def _crop_whitespace(self, image_path: str) -> str | None:
        """裁剪图片周围接近白色的空白区域"""
        try:
            img = Image.open(image_path)
            rgb = img.convert("RGB")
            # 创建掩码：非接近白色的区域
            mask = rgb.convert("L").point(lambda v: 0 if v > 245 else 255)
            bbox = mask.getbbox()
            if not bbox:
                return None
            cropped = img.crop(bbox)
            cropped.save(image_path, quality=100)
            return image_path
        except Exception as e:
            logger.warning(f"PicStatus: 裁剪空白失败 {e}")
            return None
