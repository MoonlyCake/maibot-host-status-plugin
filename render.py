"""Draw a host-resource snapshot locally with Pillow."""

from io import BytesIO
from pathlib import Path, PureWindowsPath
from typing import Dict, Optional, Sequence, Tuple
import math

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .metrics import HostSnapshot


# 以逻辑像素排版；先按 SUPERSAMPLE 倍绘制再缩到 OUTPUT_SCALE 倍，圆环和圆角才有抗锯齿。
WIDTH = 540
MARGIN = 20
GAP = 12
SUPERSAMPLE = 4
OUTPUT_SCALE = 2

BG_TOP = "#121826"
BG_BOTTOM = "#0B0F18"
CARD = "#182031"
CARD_EDGE = "#253049"
TRACK = "#263149"
INK = "#EEF2F8"
SOFT = "#B7C0D0"
MUTED = "#7D889C"
BLUE = "#5B8CFF"
VIOLET = "#A47BFF"
TEAL = "#2CC9A8"
AMBER = "#FFB547"
RED = "#FF6370"

REGULAR_FONTS = (
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
    ("/System/Library/Fonts/STHeiti Light.ttc", 1),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", 2),
    ("/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc", 2),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
    ("C:/Windows/Fonts/msyh.ttc", 0),
    ("C:/Windows/Fonts/msyh.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
)
BOLD_FONTS = (
    ("/System/Library/Fonts/STHeiti Medium.ttc", 1),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 2),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", 2),
    ("/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc", 2),
    ("C:/Windows/Fonts/msyhbd.ttc", 0),
    ("C:/Windows/Fonts/msyhbd.ttf", 0),
)
NUMBER_FONTS = (
    ("/System/Library/Fonts/SFNS.ttf", 0),
    ("C:/Windows/Fonts/seguisb.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
    ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0),
    ("C:/Windows/Fonts/arialbd.ttf", 0),
)

FontSource = Tuple[str, int]


def _first(candidates: Sequence[FontSource]) -> Optional[FontSource]:
    return next((candidate for candidate in candidates if Path(candidate[0]).is_file()), None)


class _Fonts:
    """按字号缓存三种字形；没有粗体字体时用描边模拟粗体。"""

    def __init__(self, font_path: str) -> None:
        regular = (font_path, 0) if font_path else _first(REGULAR_FONTS)
        if regular is None or not Path(regular[0]).is_file():
            raise FileNotFoundError("未找到状态图字体，请在插件配置中设置 font_path。")
        bold = None if font_path else _first(BOLD_FONTS)
        self._sources = {"regular": regular, "bold": bold or regular, "number": _first(NUMBER_FONTS) or bold or regular}
        self.faux_bold = bold is None
        self._cache: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}
        probe = self.get("regular", 24)
        # A Latin-only font gets English labels rather than missing-glyph boxes.
        self.chinese = bytes(probe.getmask("宿")) != bytes(probe.getmask("\uffff"))

    def get(self, kind: str, size: int) -> ImageFont.FreeTypeFont:
        key = (kind, size)
        if key not in self._cache:
            path, index = self._sources[kind]
            try:
                font = ImageFont.truetype(path, size, index=index)
            except OSError:
                font = ImageFont.truetype(path, size)
            if kind == "number":
                _embolden_variable(font)
            self._cache[key] = font
        return self._cache[key]


def _embolden_variable(font: ImageFont.FreeTypeFont) -> None:
    """SF 等可变字体默认是常规字重，把 Weight 轴调到半粗。"""
    try:
        axes = font.get_variation_axes()
    except (OSError, AttributeError):
        return
    values = []
    for axis in axes:
        name = axis["name"].decode() if isinstance(axis["name"], bytes) else axis["name"]
        value = 660 if name == "Weight" else axis["default"]
        values.append(max(axis["minimum"], min(axis["maximum"], value)))
    try:
        font.set_variation_by_axes(values)
    except OSError:
        pass


class _Canvas:
    """Accepts logical coordinates and draws on the supersampled image."""

    def __init__(self, height: int, fonts: _Fonts) -> None:
        self.fonts = fonts
        self.height = height
        self.image = _background(WIDTH * SUPERSAMPLE, height * SUPERSAMPLE)
        self.draw = ImageDraw.Draw(self.image)

    @staticmethod
    def _s(value: float) -> int:
        return round(value * SUPERSAMPLE)

    def font(self, size: float, kind: str = "regular") -> ImageFont.FreeTypeFont:
        return self.fonts.get(kind, self._s(size))

    def width_of(self, value: str, size: float, kind: str = "regular") -> float:
        return self.draw.textlength(value, font=self.font(size, kind)) / SUPERSAMPLE

    def text(
        self, x: float, y: float, value: str, size: float = 12, color: str = MUTED,
        kind: str = "regular", anchor: str = "la",
    ) -> None:
        stroke = 0
        if kind == "bold" and self.fonts.faux_bold:
            stroke = max(1, round(size * SUPERSAMPLE / 36))
        self.draw.text(
            (self._s(x), self._s(y)), value, font=self.font(size, kind), fill=color, anchor=anchor,
            stroke_width=stroke, stroke_fill=color,
        )

    def fit(self, value: str, size: float, width: float, kind: str = "regular") -> str:
        if self.width_of(value, size, kind) <= width:
            return value
        while value and self.width_of(value + "…", size, kind) > width:
            value = value[:-1]
        return value + "…"

    def rect(self, box: Tuple[float, float, float, float], radius: float, fill: str, outline: str = "") -> None:
        self.draw.rounded_rectangle(
            tuple(self._s(v) for v in box), radius=self._s(radius), fill=fill,
            outline=outline or None, width=SUPERSAMPLE if outline else 0,
        )

    def card(self, x: float, y: float, width: float, height: float) -> None:
        self.rect((x, y, x + width, y + height), 14, CARD, CARD_EDGE)

    def bar(self, x: float, y: float, width: float, percent: float, color: str, height: float = 6) -> None:
        self.rect((x, y, x + width, y + height), height / 2, TRACK)
        filled = width * min(max(percent, 0), 100) / 100
        if filled > 0:
            self.rect((x, y, x + max(filled, height), y + height), height / 2, color)

    def ring(self, cx: float, cy: float, radius: float, stroke: float, percent: float, color: str) -> None:
        box = tuple(self._s(v) for v in (cx - radius, cy - radius, cx + radius, cy + radius))
        width = self._s(stroke)
        self.draw.ellipse(box, outline=TRACK, width=width)
        sweep = 360 * min(max(percent, 0), 100) / 100
        if sweep <= 0:
            return
        self.draw.arc(box, -90, -90 + sweep, fill=color, width=width)
        # 圆头端点：在弧线两端各补一个直径等于线宽的圆。
        middle = radius - stroke / 2
        for angle in (-90, -90 + sweep):
            px = cx + middle * math.cos(math.radians(angle))
            py = cy + middle * math.sin(math.radians(angle))
            self.draw.ellipse(
                tuple(self._s(v) for v in (px - stroke / 2, py - stroke / 2, px + stroke / 2, py + stroke / 2)),
                fill=color,
            )

    def dot(self, cx: float, cy: float, radius: float, color: str) -> None:
        self.draw.ellipse(tuple(self._s(v) for v in (cx - radius, cy - radius, cx + radius, cy + radius)), fill=color)

    def png(self) -> bytes:
        size = (WIDTH * OUTPUT_SCALE, self.height * OUTPUT_SCALE)
        result = BytesIO()
        self.image.resize(size, Image.LANCZOS).save(result, format="PNG", optimize=True)
        return result.getvalue()


def _hex(color: str) -> Tuple[int, int, int]:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _background(width: int, height: int) -> Image.Image:
    """竖向渐变底色，左上和右上各叠一团模糊光晕。"""
    top, bottom = _hex(BG_TOP), _hex(BG_BOTTOM)
    column = Image.new("RGB", (1, 256))
    column.putdata([tuple(round(a + (b - a) * i / 255) for a, b in zip(top, bottom)) for i in range(256)])
    image = column.resize((width, height), Image.BILINEAR)

    small = (max(1, width // 16), max(1, height // 16))
    glow = Image.new("RGB", small, (0, 0, 0))
    draw = ImageDraw.Draw(glow)
    w, h = small
    draw.ellipse((-w * 0.25, -w * 0.35, w * 0.55, w * 0.3), fill=(40, 70, 150))
    draw.ellipse((w * 0.6, -w * 0.3, w * 1.25, w * 0.25), fill=(80, 50, 140))
    glow = glow.filter(ImageFilter.GaussianBlur(w * 0.12)).resize((width, height), Image.BILINEAR)
    return Image.blend(image, Image.composite(glow, image, glow.convert("L")), 0.35)


def _size(value: int) -> str:
    number = float(value)
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    index = 0
    while number >= 1024 and index < len(units) - 1:
        number /= 1024
        index += 1
    return f"{number:.1f} {units[index]}" if index else f"{value} B"


def _uptime(seconds: int, chinese: bool) -> str:
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if chinese:
        return f"{days} 天 {hours} 小时 {minutes} 分钟" if days else f"{hours} 小时 {minutes} 分钟"
    return f"{days}d {hours}h {minutes}m" if days else f"{hours}h {minutes}m"


def _disk_name(path: str, index: int, chinese: bool) -> str:
    if path == "/System/Volumes/Data":
        return "数据卷" if chinese else "Data volume"
    if path == "/":
        return "根卷" if chinese else "Root volume"
    drive = PureWindowsPath(path).drive
    if len(drive) == 2 and drive.endswith(":"):
        return f"{'磁盘' if chinese else 'Volume'} {drive}"
    return f"{'磁盘' if chinese else 'Volume'} {index}"


def _tone(percent: float, color: str) -> str:
    """指标平时用自身配色，偏高转琥珀色，紧张转红色。"""
    if percent >= 90:
        return RED
    if percent >= 75:
        return AMBER
    return color


def _core_rows(count: int) -> int:
    return max(1, math.ceil(count / 16))


def render_status(snapshot: HostSnapshot, font_path: str = "") -> bytes:
    """深色卡片：头部状态、三项环形概览、核心柱状图、内存与磁盘明细。"""
    fonts = _Fonts(font_path)
    zh = fonts.chinese
    content = WIDTH - MARGIN * 2
    primary_disk = snapshot.disks[0]

    gauges_top = 96
    gauge_height = 178
    cores_top = gauges_top + gauge_height + GAP
    core_count = len(snapshot.core_percent)
    rows = _core_rows(core_count)
    core_row_height = 104
    cores_height = 52 + rows * core_row_height
    details_top = cores_top + cores_height + GAP
    memory_height = 156
    disk_height = 52 + len(snapshot.disks) * 64
    details_height = max(memory_height, disk_height)
    footer_top = details_top + details_height + 16
    canvas = _Canvas(footer_top + 30, fonts)

    # 头部：标题、系统信息、总体状态胶囊和采样时间。
    canvas.text(MARGIN, 26, "宿主机状态" if zh else "Host Status", 24, INK, "bold")
    system = {"Darwin": "macOS", "Linux": "Linux", "Windows": "Windows"}.get(snapshot.system, snapshot.system)
    cores = (
        f"{snapshot.physical_cores} 核 {snapshot.logical_cores} 线程"
        if zh else f"{snapshot.physical_cores}C / {snapshot.logical_cores}T"
    )
    canvas.text(MARGIN, 62, f"{system}  ·  {snapshot.architecture.upper()}  ·  {cores}", 12, MUTED)

    peak = max(snapshot.cpu_percent, snapshot.memory_percent, *(disk.percent for disk in snapshot.disks))
    if peak >= 90:
        state, state_color = ("资源紧张" if zh else "Critical"), RED
    elif peak >= 75:
        state, state_color = ("负载偏高" if zh else "Elevated"), AMBER
    else:
        state, state_color = ("运行平稳" if zh else "Healthy"), TEAL
    pill_width = canvas.width_of(state, 12, "bold") + 34
    pill_x = WIDTH - MARGIN - pill_width
    canvas.rect((pill_x, 24, WIDTH - MARGIN, 50), 13, CARD, CARD_EDGE)
    canvas.dot(pill_x + 14, 37, 4, state_color)
    canvas.text(pill_x + 24, 37, state, 12, INK, "bold", "lm")
    canvas.text(WIDTH - MARGIN, 62, snapshot.captured_at.strftime("%Y.%m.%d  %H:%M:%S"), 12, MUTED, "number", "ra")

    # 三项环形概览。
    gauge_width = (content - GAP * 2) / 3
    top_core = max(snapshot.core_percent, default=0.0)
    gauges = (
        ("CPU", snapshot.cpu_percent, BLUE, f"{'峰值核心' if zh else 'Peak core'} {top_core:.0f}%"),
        ("内存" if zh else "Memory", snapshot.memory_percent, VIOLET,
         f"{_size(snapshot.memory_used)} / {_size(snapshot.memory_total)}"),
        ("硬盘" if zh else "Disk", primary_disk.percent, TEAL,
         f"{_size(primary_disk.used)} / {_size(primary_disk.total)}"),
    )
    for index, (title, percent, color, detail) in enumerate(gauges):
        x = MARGIN + index * (gauge_width + GAP)
        cx = x + gauge_width / 2
        cy = gauges_top + 70
        tone = _tone(percent, color)
        canvas.card(x, gauges_top, gauge_width, gauge_height)
        canvas.ring(cx, cy, 48, 9, percent, tone)
        value = f"{percent:.1f}"
        value_width = canvas.width_of(value, 23, "number")
        unit_width = canvas.width_of("%", 11, "number")
        start = cx - (value_width + unit_width + 1) / 2
        canvas.text(start, cy + 8, value, 23, INK, "number", "ls")
        canvas.text(start + value_width + 1, cy + 8, "%", 11, MUTED, "number", "ls")
        canvas.text(cx, gauges_top + 138, title, 13, SOFT, "bold", "ma")
        canvas.text(cx, gauges_top + 158, canvas.fit(detail, 11, gauge_width - 16), 11, MUTED, "regular", "ma")

    # 核心负载柱状图：每行最多 16 根，柱宽随核心数自适应。
    canvas.card(MARGIN, cores_top, content, cores_height)
    inner_x = MARGIN + 18
    inner_width = content - 36
    canvas.text(inner_x, cores_top + 18, "核心负载" if zh else "Core load", 14, INK, "bold")
    summary = (
        f"平均 {snapshot.cpu_percent:.1f}%  ·  峰值 {top_core:.0f}%"
        if zh else f"avg {snapshot.cpu_percent:.1f}%  ·  peak {top_core:.0f}%"
    )
    canvas.text(WIDTH - MARGIN - 18, cores_top + 20, summary, 11, MUTED, "regular", "ra")
    per_row = math.ceil(core_count / rows) if core_count else 1
    column_gap = 10 if per_row <= 8 else 6
    column_width = (inner_width - column_gap * (per_row - 1)) / per_row
    bar_width = min(column_width, 34)
    bar_height = 56
    for index, percent in enumerate(snapshot.core_percent):
        row, column = divmod(index, per_row)
        cx = inner_x + column * (column_width + column_gap) + column_width / 2
        base = cores_top + 52 + row * core_row_height + 16 + bar_height
        left, right = cx - bar_width / 2, cx + bar_width / 2
        canvas.rect((left, base - bar_height, right, base), 5, TRACK)
        filled = bar_height * min(max(percent, 0), 100) / 100
        if filled > 0:
            canvas.rect((left, base - max(filled, 6), right, base), 5, _tone(percent, BLUE))
        canvas.text(cx, base - bar_height - 4, f"{percent:.0f}", 10, SOFT, "number", "md")
        canvas.text(cx, base + 8, f"{index + 1}", 10, MUTED, "number", "ma")

    # 明细：左侧内存与交换空间，右侧逐个磁盘。
    half = (content - GAP) / 2
    left_x, right_x = MARGIN, MARGIN + half + GAP
    canvas.card(left_x, details_top, half, details_height)
    canvas.card(right_x, details_top, half, details_height)

    lx, lw = left_x + 18, half - 36
    canvas.text(lx, details_top + 18, "内存" if zh else "Memory", 14, INK, "bold")
    memory_rows = (
        ("已用" if zh else "Used", _size(snapshot.memory_used)),
        ("可用" if zh else "Available", _size(snapshot.memory_available)),
    )
    for offset, (label, value) in zip((52, 76), memory_rows):
        canvas.text(lx, details_top + offset, label, 12, MUTED)
        canvas.text(lx + lw, details_top + offset, value, 12, INK, "number", "ra")
    canvas.text(lx, details_top + 104, "交换空间" if zh else "Swap", 12, MUTED)
    swap = f"{_size(snapshot.swap_used)} / {_size(snapshot.swap_total)}"
    canvas.text(lx + lw, details_top + 104, swap, 12, INK, "number", "ra")
    canvas.bar(lx, details_top + 128, lw, snapshot.swap_percent, _tone(snapshot.swap_percent, VIOLET))

    rx, rw = right_x + 18, half - 36
    canvas.text(rx, details_top + 18, "磁盘" if zh else "Disks", 14, INK, "bold")
    for index, disk in enumerate(snapshot.disks):
        y = details_top + 52 + index * 64
        # 数字字体不含中文，标签和数值分开绘制。
        free_label, free = ("可用" if zh else "Free"), _size(disk.free)
        free_width = canvas.width_of(free, 12, "number")
        label_width = canvas.width_of(free_label, 11)
        name = canvas.fit(_disk_name(disk.path, index + 1, zh), 12, rw - free_width - label_width - 16)
        canvas.text(rx, y, name, 12, SOFT)
        canvas.text(rx + rw, y, free, 12, INK, "number", "ra")
        canvas.text(rx + rw - free_width - 5, y + 1, free_label, 11, MUTED, "regular", "ra")
        canvas.bar(rx, y + 24, rw, disk.percent, _tone(disk.percent, TEAL))
        usage = f"{_size(disk.used)} / {_size(disk.total)}  ·  {disk.percent:.1f}%"
        canvas.text(rx, y + 38, canvas.fit(usage, 11, rw), 11, MUTED, "number")

    uptime = f"{'已运行' if zh else 'Uptime'}  {_uptime(snapshot.uptime_seconds, zh)}"
    canvas.text(MARGIN + 2, footer_top, uptime, 11, MUTED)
    canvas.text(WIDTH - MARGIN - 2, footer_top, "HOST STATUS", 10, MUTED, "number", "ra")
    return canvas.png()
