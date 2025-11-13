from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Optional

import jinja2


ROOT = Path(__file__).parent
TPL_DIR = ROOT / "templates" / "default" / "res" / "templates"
CSS_FILE = ROOT / "templates" / "default" / "res" / "css" / "index.css"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def build_default_html(collected: dict[str, Any], bg_bytes: bytes, avatar_bytes: Optional[bytes] = None) -> str:
    """Compose a single-file HTML with inline CSS and macros, no external fetch.

    - Inline macros.html.jinja at top of index template
    - Remove external JS includes and lazy-load logic
    - Replace background to inline data URL
    - Inline CSS via <style>
    """

    macros = _read_text(TPL_DIR / "macros.html.jinja")
    index = _read_text(TPL_DIR / "index.html.jinja")
    css = _read_text(CSS_FILE)

    # 1) strip import line in index (first line)
    lines = index.splitlines()
    if lines and lines[0].lstrip().startswith("{% from"):
        lines = lines[1:]
    index_no_import = "\n".join(lines)

    # 2) tweak viewport to exact content width to avoid right-side whitespace on full_page screenshots
    index = index.replace(
        'content="width=device-width, initial-scale=1.0"',
        'content="width=650, initial-scale=1.0"',
    )

    # remove external js includes
    index_no_js = index_no_import.replace(
        '<script src="/js/init-global.js"></script>', "",
    ).replace(
        '<script src="/js/lazy-load.js"></script>', "",
    ).replace(
        '<script src="/js/load-plugin.js"></script>', "",
    )

    # 3) inline CSS style + fix page width to component width to avoid right-side white area
    page_fix = "html,body{margin:0;padding:0;width:650px;}"
    index_inlined_css = index_no_js.replace(
        '<link rel="stylesheet" href="/default/res/css/index.css" />',
        f"<style>\n{css}\n{page_fix}\n</style>",
    )

    # 4) inline background image via style instead of data-background-image
    b64 = base64.b64encode(bg_bytes).decode("ascii")
    index_bg = index_inlined_css.replace(
        '<div class="main-background" data-background-image="/api/background">',
        f'<div class="main-background" style="background-image:url(\'data:image/jpeg;base64,{b64}\')">',
    )
    # 不向 body/html 注入背景，避免整页截图时出现与主容器重复的背景

    # 5) inline default avatar for header (replace lazy data-src with inline src)
    try:
        if avatar_bytes is None:
            avatar_bytes = (ROOT / "res" / "assets" / "default_avatar.webp").read_bytes()
        avatar_b64 = base64.b64encode(avatar_bytes).decode("ascii")
        # 将 lazy 的 data-src 改为 src，保证 t2i 无需 JS 也能显示
        index_bg = index_bg.replace(
            'data-src="/api/bot_avatar/{{ info.self_id }}"',
            f'src="data:image/webp;base64,{avatar_b64}"',
        )
    except Exception:
        # ignore if asset missing
        pass

    # 6) put macros at the beginning so calls like {{ header(d) }} work
    tmpl = macros + "\n" + index_bg

    # Render with our own jinja to resolve macros, using the same keys structure
    env = jinja2.Environment(autoescape=jinja2.select_autoescape(["html", "xml"]))

    def percent_to_color(percent: float) -> str:
        if percent < 70:
            return "prog-low"
        if percent < 90:
            return "prog-medium"
        return "prog-high"

    def auto_convert_unit(value: float, suffix: str = "", with_space: bool = False, unit_index: int | None = None) -> str:
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

    template = env.from_string(tmpl)
    # index expects variables: d (collected) and config.ps_default_components
    config = {
        "ps_default_components": ["header", "cpu_mem", "disk", "network", "process", "footer"],
        "ps_default_additional_css": [],
        "ps_default_additional_script": [],
    }
    html = template.render(d=collected, config=config)
    return html
