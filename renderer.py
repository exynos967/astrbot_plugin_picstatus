from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFont


DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720


def _find_cjk_font() -> Optional[str]:
    """Try to find a CJK-capable font installed in the system."""
    candidates = [
        # Noto / Source Han / HarmonyOS
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansSC-Regular.ttf",
        "/usr/share/fonts/truetype/source-han-sans/SourceHanSansCN-Regular.otf",
        "/usr/share/fonts/truetype/harmonyos-sans/HarmonyOS_Sans_SC_Regular.ttf",
        # Common fallbacks
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/arphic/ukai.ttc",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    # Try common fonts; fallback to default
    import os

    env_font = os.getenv("PICSTATUS_FONT_PATH")
    cjk = env_font if (env_font and Path(env_font).exists()) else _find_cjk_font()
    names = [
        cjk,
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for name in filter(None, names):
        p = Path(name)
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def _bar(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, percent: float):
    draw.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=(255, 255, 255, 48))
    pw = max(0, min(1.0, percent / 100.0)) * w
    color = (53, 189, 85) if percent < 70 else (255, 170, 0) if percent < 90 else (236, 75, 75)
    draw.rounded_rectangle((x, y, x + int(pw), y + h), radius=h // 2, fill=color)


def _paste_background(canvas: Image.Image, bg_bytes: Optional[bytes]) -> None:
    if not bg_bytes:
        return
    try:
        bg = Image.open(BytesIO(bg_bytes)).convert("RGB")
        # cover fit
        W, H = canvas.size
        bw, bh = bg.size
        scale = max(W / bw, H / bh)
        bg = bg.resize((int(bw * scale), int(bh * scale)), Image.LANCZOS)
        # center crop
        bx = (bg.width - W) // 2
        by = (bg.height - H) // 2
        bg = bg.crop((bx, by, bx + W, by + H))
        canvas.paste(bg, (0, 0))
        # mask overlay
        mask = Image.new("RGBA", (W, H), (250, 250, 250, 90))
        canvas.paste(Image.alpha_composite(canvas.convert("RGBA"), mask), (0, 0))
    except Exception:
        pass


def render_status(collected: dict[str, Any], save_dir: Path, bg_bytes: Optional[bytes] = None) -> Path:
    save_dir.mkdir(parents=True, exist_ok=True)
    W, H = DEFAULT_WIDTH, DEFAULT_HEIGHT
    img = Image.new("RGB", (W, H), (28, 30, 34))
    draw = ImageDraw.Draw(img)

    # background
    _paste_background(img, bg_bytes)

    title_font = _load_font(36)
    small_font = _load_font(22)
    mono_font = _load_font(24)

    # Header
    draw.text((40, 30), "系统运行状态", font=title_font, fill=(240, 240, 240))
    draw.text(
        (40, 80),
        f"系统: {collected['system_name']} | {collected['python_version']} | AstrBot PicStatus",
        font=small_font,
        fill=(200, 200, 200),
    )
    draw.text(
        (40, 110),
        f"运行: AstrBot {collected['nonebot_run_time']} | 系统 {collected['system_run_time']} | {collected['time']}",
        font=small_font,
        fill=(200, 200, 200),
    )

    # CPU/Mem
    y = 160
    draw.text((40, y), f"CPU: {collected['cpu_brand']}", font=small_font, fill=(230, 230, 230))
    _bar(draw, 300, y + 4, 400, 22, float(collected["cpu_percent"]))
    freq = collected.get("cpu_freq")
    if hasattr(freq, "current"):
        freq_cur = getattr(freq, "current")
        freq_max = getattr(freq, "max")
        freq_s = f"{freq_cur:.0f}MHz" if freq_cur else "?"
        if freq_max:
            freq_s += f" / {freq_max:.0f}MHz"
        draw.text((720, y), f"频率: {freq_s}", font=small_font, fill=(180, 180, 180))

    y += 40
    mem = collected["memory_stat"]
    draw.text((40, y), f"内存: {mem.used/1024**3:.1f}G / {mem.total/1024**3:.1f}G", font=small_font, fill=(230, 230, 230))
    _bar(draw, 300, y + 4, 400, 22, float(mem.percent))

    y += 40
    swap = collected["swap_stat"]
    draw.text((40, y), f"交换: {swap.used/1024**3:.1f}G / {swap.total/1024**3:.1f}G", font=small_font, fill=(230, 230, 230))
    _bar(draw, 300, y + 4, 400, 22, float(swap.percent))

    # Disk usage
    y += 60
    draw.text((40, y), "磁盘使用:", font=small_font, fill=(230, 230, 230))
    y += 6
    for it in collected["disk_usage"][:6]:
        y += 28
        if it.exception:
            draw.text((60, y), f"{it.name} - {it.exception}", font=small_font, fill=(200, 120, 120))
        else:
            used = (it.used or 0) / 1024 ** 3
            total = (it.total or 0) / 1024 ** 3
            draw.text((60, y), f"{it.name} {used:.1f}G / {total:.1f}G", font=small_font, fill=(230, 230, 230))
            _bar(draw, 420, y + 4, 300, 18, float(it.percent or 0.0))

    # Network
    y += 60
    draw.text((40, y), "网络速率:", font=small_font, fill=(230, 230, 230))
    for idx, it in enumerate(collected["network_io"][:5]):
        draw.text((250 + idx * 200, y), it.name, font=mono_font, fill=(180, 180, 180))
        draw.text(
            (250 + idx * 200, y + 28),
            f"↑{it.sent/1024:.0f}K/s ↓{it.recv/1024:.0f}K/s",
            font=small_font,
            fill=(200, 200, 200),
        )

    # Connection tests
    y += 70
    draw.text((40, y), "连通性:", font=small_font, fill=(230, 230, 230))
    for idx, it in enumerate(collected["network_connection"]):
        label = f"{it.name}: {it.status} {it.reason} {it.delay:.1f}ms"
        color = (170, 210, 170) if (it.error is None and str(it.status).isdigit()) else (220, 150, 150)
        draw.text((140 + idx * 400, y), label, font=small_font, fill=color)

    # Processes
    y += 50
    draw.text((40, y), "进程TOP:", font=small_font, fill=(230, 230, 230))
    for i, it in enumerate(collected["process_status"]):
        draw.text((180 + i * 200, y), f"{it.name}", font=small_font, fill=(200, 200, 200))
        draw.text((180 + i * 200, y + 26), f"CPU {it.cpu:.1f}%", font=small_font, fill=(200, 200, 200))
        draw.text((180 + i * 200, y + 50), f"MEM {it.mem/1024**2:.0f}M", font=small_font, fill=(200, 200, 200))

    # Footer
    draw.text((40, H - 40), "AstrBot × PicStatus | https://github.com/lgc-NB2Dev/nonebot-plugin-picstatus", font=small_font, fill=(160, 160, 160))

    out = save_dir / "status.jpg"
    img.save(out, format="JPEG", quality=90)
    return out
