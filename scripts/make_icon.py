"""生成应用图标。

图标与界面的图标一样用 QPainter 画，不依赖设计软件产出的位图：改一个
数字就能重新生成全套尺寸，仓库里也不必存 psd。

构图：Big Sur 规格的圆角矩形（824/1024 的内容区、185 px 圆角），蓝色
渐变底，中间一本翻开的书，书页上方三道向右上扩散的声波——「把文字读
出来」这件事，一眼能看懂。

用法：
    .venv/bin/python scripts/make_icon.py
产出：
    assets/AppIcon.icns    打包用（--icon）
    assets/AppIcon.png     512 px，运行时窗口图标
"""
from __future__ import annotations

import math
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

CANVAS = 1024
BODY = 824           # Big Sur 图标内容区，四周各留 100 px
RADIUS = 185
CX = CANVAS / 2


def _body_path() -> QPainterPath:
    offset = (CANVAS - BODY) / 2
    path = QPainterPath()
    path.addRoundedRect(QRectF(offset, offset, BODY, BODY), RADIUS, RADIUS)
    return path


def _draw_background(painter: QPainter) -> None:
    offset = (CANVAS - BODY) / 2
    gradient = QLinearGradient(0, offset, 0, offset + BODY)
    gradient.setColorAt(0.0, QColor("#5CA8FF"))
    gradient.setColorAt(0.45, QColor("#1B7BEB"))
    gradient.setColorAt(1.0, QColor("#0A4FC2"))
    painter.fillPath(_body_path(), QBrush(gradient))

    # 左上角一团柔光，避免纯平渐变显得塑料。裁剪在圆角内，边缘不会漏。
    painter.save()
    painter.setClipPath(_body_path())
    glow = QRadialGradient(QPointF(CANVAS * 0.3, CANVAS * 0.22), CANVAS * 0.62)
    glow.setColorAt(0.0, QColor(255, 255, 255, 78))
    glow.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.fillRect(QRectF(0, 0, CANVAS, CANVAS), QBrush(glow))

    # 底部压一层深色，让书页的白色更立得住。
    shade = QLinearGradient(0, CANVAS * 0.55, 0, CANVAS)
    shade.setColorAt(0.0, QColor(0, 0, 0, 0))
    shade.setColorAt(1.0, QColor(0, 0, 0, 46))
    painter.fillRect(QRectF(0, 0, CANVAS, CANVAS), QBrush(shade))
    painter.restore()


def _draw_book(painter: QPainter, simplified: bool = False) -> None:
    """一本摊开的书，向左侧挪一点，右侧留给声波。"""
    gap = 8.0
    center_x = 388.0
    top = 424.0          # 书页靠近书脊处的上边缘
    edge_top = 456.0     # 外侧上边缘，比书脊低，形成翻开的弧度
    bottom = 632.0
    edge_bottom = 610.0
    outer = 206.0        # 外侧边界

    white = QColor(255, 255, 255, 250)
    for sign in (-1, 1):
        spine_x = center_x + sign * gap
        outer_x = center_x + sign * outer
        page = QPainterPath()
        page.moveTo(QPointF(spine_x, top))
        # 上边缘：从书脊向外微微下坠
        page.quadTo(
            QPointF(center_x + sign * outer * 0.55, top - 6), QPointF(outer_x, edge_top)
        )
        page.lineTo(QPointF(outer_x, edge_bottom))
        # 下边缘：同样带弧度
        page.quadTo(
            QPointF(center_x + sign * outer * 0.55, bottom - 22),
            QPointF(spine_x, bottom),
        )
        page.closeSubpath()
        painter.fillPath(page, QBrush(white))

        # 书页上的两行文字：用底色而不是灰色，小尺寸下也读得出「这是书」。
        # 32 px 以下这两条线只有零点几个像素，画了也是脏点，直接省掉。
        if simplified:
            continue
        pen = QPen(QColor(11, 79, 194, 125))
        pen.setWidthF(13.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        inset = 40.0
        for line_y, length in ((top + 70, outer * 0.54), (top + 120, outer * 0.36)):
            start_x = center_x + sign * (gap + inset)
            end_x = center_x + sign * (gap + inset + length)
            painter.drawLine(QPointF(start_x, line_y), QPointF(end_x, line_y + 3))


def _draw_waves(painter: QPainter, simplified: bool = False) -> None:
    """书本右侧三道弧，开口朝向书本——通用的「正在发声」符号。

    不做成从一点向上扩散的同心弧：那是 WiFi 图标，而这台机器恰恰不联网。
    圆心放在书脊高度上，弧线朝右张开，读起来就是声音从书里出来。
    """
    center = QPointF(612.0, 528.0)
    pen = QPen(QColor(255, 255, 255, 240))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    # 小尺寸下三道弧会糊成一片，改成两道更粗的，留出干净的间隙。
    radii = (88.0, 176.0) if simplified else (72.0, 132.0, 192.0)
    for index, radius in enumerate(radii):
        pen.setWidthF((46.0 - index * 8.0) if simplified else (34.0 - index * 4.0))
        painter.setPen(pen)
        # Qt 的角度 0° 在 3 点钟方向、逆时针为正；右侧扇形是 -54°→+54°。
        rect = QRectF(
            center.x() - radius, center.y() - radius, radius * 2, radius * 2
        )
        path = QPainterPath()
        path.arcMoveTo(rect, -54.0)
        path.arcTo(rect, -54.0, 108.0)
        painter.drawPath(path)


def _draw_edge(painter: QPainter) -> None:
    """内描边：图标外缘压一圈极淡的白线，深色桌面上不会糊进背景。"""
    painter.save()
    painter.setClipPath(_body_path())
    pen = QPen(QColor(255, 255, 255, 46))
    pen.setWidthF(3.0)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(_body_path())
    painter.restore()


def render(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.scale(size / CANVAS, size / CANVAS)
    simplified = size <= 32
    _draw_background(painter)
    _draw_book(painter, simplified)
    _draw_waves(painter, simplified)
    _draw_edge(painter)
    painter.end()
    return image


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)  # noqa: F841
    ASSETS.mkdir(parents=True, exist_ok=True)

    master = render(CANVAS)
    if not master.save(str(ASSETS / "AppIcon-1024.png"), "PNG"):
        print("无法写出主图", file=sys.stderr)
        return 1

    iconset = ASSETS / "AppIcon.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)

    # iconutil 需要固定命名的两套（1x/2x）。16/32/128/256/512 各一份 2 倍图。
    for base in (16, 32, 128, 256, 512):
        render(base).save(str(iconset / f"icon_{base}x{base}.png"), "PNG")
        render(base * 2).save(str(iconset / f"icon_{base}x{base}@2x.png"), "PNG")

    icns = ASSETS / "AppIcon.icns"
    result = subprocess.run(
        ["/usr/bin/iconutil", "-c", "icns", str(iconset), "-o", str(icns)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"iconutil 失败：{result.stderr.strip()}", file=sys.stderr)
        return 1

    # 窗口图标用 512，Retina 下也够清晰，比整包 icns 好读。
    render(512).save(str(ASSETS / "AppIcon.png"), "PNG")

    # iconset 只是中间产物，留着会让仓库多出十几个重复 png。
    shutil.rmtree(iconset)
    (ASSETS / "AppIcon-1024.png").unlink(missing_ok=True)

    for name in ("AppIcon.icns", "AppIcon.png"):
        path = ASSETS / name
        print(f"{name}: {path.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
