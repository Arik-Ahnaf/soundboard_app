from pathlib import Path
from utils import database
from components.ContextMenu import ContextMenu
from PySide6.QtCore import QEasingCurve, Qt, QPointF, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from utils import logger

ICONS_DIR = Path(__file__).resolve().parent.parent / "icons"


class CircleIcon(QWidget):

    def __init__(self, diameter: int = 40, parent=None):
        super().__init__(parent)
        self._diameter = diameter
        self._hover_progress = 0.0
        self.setFixedSize(diameter, diameter)
        self.setAttribute(Qt.WA_Hover)
        self.setMouseTracking(True)

        self._icon_renderer = QSvgRenderer(str(ICONS_DIR / "play_button.svg"), self)

        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(200)
        self._hover_anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._hover_anim.valueChanged.connect(self._set_hover_progress)

    def _set_hover_progress(self, value):
        self._hover_progress = value
        self.update()

    def enterEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(event)

    def _tinted_icon(self, size: int, color: QColor) -> QPixmap:
        """Render the SVG to a pixmap, then recolor its opaque pixels via
        SourceIn compositing so the icon can animate between colors the
        same way the circle background does."""
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        icon_painter = QPainter(pixmap)
        icon_painter.setRenderHint(QPainter.Antialiasing)
        self._icon_renderer.render(icon_painter)
        icon_painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        icon_painter.fillRect(pixmap.rect(), color)
        icon_painter.end()
        return pixmap

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        shade = int(255 * (1.0 - self._hover_progress))
        circle_color = QColor(shade, shade, shade)
        icon_color = QColor(255 - shade, 255 - shade, 255 - shade)

        painter.setBrush(circle_color)
        painter.drawEllipse(0, 0, self._diameter, self._diameter)

        icon_size = int(self._diameter * 0.4)
        offset = (self._diameter - icon_size) / 2
        icon_pixmap = self._tinted_icon(icon_size, icon_color)
        painter.drawPixmap(QPointF(offset + 2, offset), icon_pixmap)


class HamburgerDots(QWidget):
    """Three-dot vertical menu icon"""

    def __init__(self, dot_size: int = 6, count: int = 3, height: int = 30, parent=None):
        super().__init__(parent)
        self._dot_size = dot_size
        self._count = count
        self.setFixedSize(dot_size, height)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("black"))

        d = self._dot_size
        slot = self.height() / self._count
        for i in range(self._count):
            cy = slot * i + slot / 2
            painter.drawEllipse(QPointF(d / 2, cy), d / 2, d / 2)


class ListItem(QWidget):
    """Soundboard row: play button, title/duration, and a hamburger menu."""

    def __init__(self, title: str, duration: str, path=None, parent=None):
        super().__init__(parent)
        self.setFixedSize(300, 60)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 20, 0)
        layout.setSpacing(10)

        layout.addWidget(CircleIcon(40))

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)

        self.title = QLabel(title)
        title_font = QFont()
        title_font.setPixelSize(16)
        self.title.setFont(title_font)
        self.title.setStyleSheet("color: black; background: transparent;")

        self.duration = QLabel(str(duration))
        duration_font = QFont()
        duration_font.setPixelSize(14)
        duration_font.setItalic(True)
        self.duration.setFont(duration_font)
        self.duration.setStyleSheet("color: #8a8a8a; background: transparent;")

        text_layout.addStretch()
        text_layout.addWidget(self.title)
        text_layout.addWidget(self.duration)
        text_layout.addStretch()

        layout.addLayout(text_layout)
        layout.addStretch()
        layout.addWidget(HamburgerDots())

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 0)
        shadow.setColor(QColor(0, 0, 0, 0))
        self.setGraphicsEffect(shadow)
        self._shadow_effect = shadow
        self._shadow_progress = 0.0

        self._shadow_anim = QVariantAnimation(self)
        self._shadow_anim.setDuration(220)
        self._shadow_anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._shadow_anim.valueChanged.connect(self._update_shadow)

    def _update_shadow(self, value):
        self._shadow_progress = value
        alpha = int(120 * value)
        self._shadow_effect.setColor(QColor(0, 0, 0, alpha))
        self._shadow_effect.setOffset(0, 6 * value)

    def enterEvent(self, event):
        self._shadow_anim.stop()
        self._shadow_anim.setStartValue(self._shadow_progress)
        self._shadow_anim.setEndValue(1.0)
        self._shadow_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._shadow_anim.stop()
        self._shadow_anim.setStartValue(self._shadow_progress)
        self._shadow_anim.setEndValue(0.0)
        self._shadow_anim.start()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("white"))
        painter.drawRoundedRect(self.rect(), 16, 16)

    def contextMenuEvent(self, event):
        self._menu = ContextMenu(self)
        self._menu.play_clicked.connect(self.on_play)
        self._menu.preview_clicked.connect(self.on_preview)
        self._menu.rename_clicked.connect(self.on_rename)
        self._menu.remove_clicked.connect(self.on_remove)
        self._menu.show_at(event.globalPos())

    def on_play(self):
        pass

    def on_preview(self):
        pass

    def on_rename(self):
        pass

    def on_remove(self):
        pass