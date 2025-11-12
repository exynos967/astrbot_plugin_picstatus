from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

import jinja2


ROOT = Path(__file__).parent
TPL_RES = ROOT / "templates" / "default" / "res"
JS_RES = ROOT / "res" / "js"
ASSETS = ROOT / "res" / "assets"


def _jinja_env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TPL_RES / "templates")),
        autoescape=jinja2.select_autoescape(["html", "xml"]),
        enable_async=True,
    )

    # filters
    def percent_to_color(percent: float) -> str:
        if percent < 70:
            return "prog-low"
        if percent < 90:
            return "prog-medium"
        return "prog-high"

    def auto_convert_unit(value: float, suffix: str = "", with_space: bool = False, unit_index: int | None = None) -> str:
        # simple byte auto unit converter
        units = ["B", "KB", "MB", "GB", "TB"]
        idx = 0
        v = float(value)
        while (unit_index is None) and v >= 1024 and idx < len(units) - 1:
            v /= 1024
            idx += 1
        if unit_index is not None:
            idx = unit_index
        sp = " " if with_space else ""
        return f"{v:.0f}{sp}{units[idx]}{suffix}"

    from .utils import CpuFreq

    def format_cpu_freq(freq: CpuFreq) -> str:
        def cu(x: float | None) -> str:
            if not x:
                return "未知"
            # Hz → show in Hz with unit_index=2 (Hz->KHz->MHz)
            v = x
            units = ["Hz", "KHz", "MHz", "GHz"]
            idx = 0
            while v >= 1000 and idx < len(units) - 1:
                v /= 1000
                idx += 1
            return f"{v:.0f}{units[idx]}"

        cur = cu(freq.current)
        if freq.max:
            return f"{cur} / {cu(freq.max)}"
        return cur

    env.filters.update(
        percent_to_color=percent_to_color,
        auto_convert_unit=auto_convert_unit,
        format_cpu_freq=format_cpu_freq,
        br=lambda s: (str(s).replace("\n", "<br />") if s is not None else ""),
    )
    return env


@dataclass
class TemplateConfig:
    ps_default_components: list[str]
    ps_default_additional_css: list[str]
    ps_default_additional_script: list[str]


async def render_html_image(collected: dict[str, Any], bg_bytes: bytes) -> bytes:
    # Prepare HTML
    env = _jinja_env()
    tpl = env.get_template("index.html.jinja")
    config = TemplateConfig(
        ps_default_components=["header", "cpu_mem", "disk", "network", "process", "footer"],
        ps_default_additional_css=[],
        ps_default_additional_script=[],
    )
    html = await tpl.render_async(d=collected, config=config)

    # Render via Playwright
    from playwright.async_api import async_playwright

    ROUTE_BASE = "http://picstatus.nonebot"

    async with async_playwright() as p:
        cdp_url = os.getenv("PICSTATUS_PW_CDP")
        if cdp_url:
            # Connect to an external Chrome/Chromium over CDP
            browser = await p.chromium.connect_over_cdp(cdp_url)
        else:
            browser = await p.chromium.launch(args=["--no-sandbox"], headless=True)
        try:
            context = (
                browser.contexts[0] if browser.contexts else await browser.new_context()
            )
            page = await context.new_page()

            # / -> html
            await page.route("**/", lambda route: asyncio.create_task(route.fulfill(content_type="text/html", body=html)))

            # /default/res/**/* -> template assets
            async def route_tpl(route, request):
                url = request.url
                path = url.split("/default/res/")[-1]
                fp = TPL_RES / path
                await route.fulfill(path=str(fp))

            await page.route("**/default/res/**", route_tpl)

            # /js/* -> js assets
            async def route_js(route, request):
                url = request.url
                name = url.rsplit("/", 1)[-1]
                await route.fulfill(path=str(JS_RES / name))

            await page.route("**/js/*", route_js)

            # /api/background -> bg bytes
            async def route_bg(route, _):
                await route.fulfill(content_type="image/jpeg", body=bg_bytes)

            await page.route("**/api/background", route_bg)

            # /api/bot_avatar/* -> default avatar
            async def route_avatar(route, _):
                await route.fulfill(path=str(ASSETS / "default_avatar.webp"))

            await page.route("**/api/bot_avatar/*", route_avatar)

            await page.goto(f"{ROUTE_BASE}/")
            await page.wait_for_selector("body.done")
            elem = await page.query_selector(".main-background")
            assert elem
            buf = await elem.screenshot(type="jpeg")
            return bytes(buf)
        finally:
            await browser.close()
