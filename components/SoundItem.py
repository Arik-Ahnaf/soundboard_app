import json
from pathlib import Path
import sys

from utils import database
from components.ContextMenu import ContextMenu
from PySide6.QtCore import QEasingCurve, Qt, QPointF, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractButton,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)
from utils import logger
from utils.playback import get_playback_controller

ICONS_DIR = Path(__file__).resolve().parent.parent / "icons"
THEME_PATH = Path(__file__).resolve().parent.parent / "themes" / "dark.json"
PLAY_TOOLTIP = (
    "Play through speakers and VB-CABLE (select CABLE Output in your voice app)"
    if sys.platform == "win32" else "Play through speakers and Soundboard Mic"
)

with THEME_PATH.open(encoding="utf-8") as theme_file:
    DARK_COLORS = json.load(theme_file)["colors"]


def blend_colors(start: QColor, end: QColor, progress: float) -> QColor:
    """Return the color at ``progress`` between two theme colors."""
    return QColor.fromRgbF(
        start.redF() + (end.redF() - start.redF()) * progress,
        start.greenF() + (end.greenF() - start.greenF()) * progress,
        start.blueF() + (end.blueF() - start.blueF()) * progress,
        start.alphaF() + (end.alphaF() - start.alphaF()) * progress,
    )


class CircleIcon(QAbstractButton):

    def __init__(self, diameter: int = 40, parent=None):
        super().__init__(parent)
        self._diameter = diameter
        self._hover_progress = 0.0
        self._playing = False
        self.setFixedSize(diameter, diameter)
        self.setAttribute(Qt.WA_Hover)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("Play sound")

        self._icon_renderer = QSvgRenderer(str(ICONS_DIR / "play_button.svg"), self)

        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(200)
        self._hover_anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._hover_anim.valueChanged.connect(self._set_hover_progress)

    def set_playing(self, playing: bool):
        self._playing = playing
        self.update()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if not event.isAutoRepeat():
                self.click()
            event.accept()
        else:
            super().keyPressEvent(event)

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

        play_color = QColor(DARK_COLORS["play_btn"])
        background_color = QColor(DARK_COLORS["background"])
        circle_color = blend_colors(
            play_color, background_color, self._hover_progress
        )
        icon_color = blend_colors(
            background_color, play_color, self._hover_progress
        )

        painter.setBrush(circle_color)
        painter.drawEllipse(0, 0, self._diameter, self._diameter)

        icon_size = int(self._diameter * 0.4)
        offset = (self._diameter - icon_size) / 2
        if self._playing:
            painter.setBrush(icon_color)
            painter.drawRect(int(offset), int(offset), icon_size, icon_size)
        else:
            icon_pixmap = self._tinted_icon(icon_size, icon_color)
            painter.drawPixmap(QPointF(offset + 2, offset), icon_pixmap)
        if self.hasFocus():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(DARK_COLORS["foreground"]), 1, Qt.DotLine))
            painter.drawEllipse(3, 3, self._diameter - 6, self._diameter - 6)


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
        painter.setBrush(QColor(DARK_COLORS["neutral"]))

        d = self._dot_size
        slot = self.height() / self._count
        for i in range(self._count):
            cy = slot * i + slot / 2
            painter.drawEllipse(QPointF(d / 2, cy), d / 2, d / 2)


class SoundItem(QWidget):
    """Soundboard row: play button, title/duration, and a hamburger menu."""

    def __init__(
        self,
        title: str,
        duration: str,
        path: str | Path | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setFixedSize(300, 60)
        self._sound_path = Path(path).expanduser() if path else None
        self._playback = get_playback_controller()
        self._playback_state = "idle"
        self._playback.state_changed.connect(self._on_playback_state)
        self._playback.failed.connect(self._on_playback_error)
        self.destroyed.connect(
            lambda _=None, owner=id(self), controller=self._playback: controller.stop(owner)
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 20, 0)
        layout.setSpacing(10)

        self.play_button = CircleIcon(40)
        self.play_button.clicked.connect(self._toggle_play)
        self.play_button.setAccessibleName(f"Play {title}")
        self.play_button.setToolTip(PLAY_TOOLTIP)
        layout.addWidget(self.play_button)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)

        self.title = QLabel(title)
        title_font = QFont()
        title_font.setPixelSize(16)
        self.title.setFont(title_font)
        self.title.setStyleSheet(
            f"color: {DARK_COLORS['foreground']}; background: transparent;"
        )

        self.duration = QLabel(str(duration))
        duration_font = QFont()
        duration_font.setPixelSize(14)
        duration_font.setItalic(True)
        self.duration.setFont(duration_font)
        self.duration.setStyleSheet(
            f"color: {DARK_COLORS['foreground']}; background: transparent;"
        )

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
        painter.setPen(QPen(QColor(DARK_COLORS["foreground"]), 1))
        painter.setBrush(QColor(DARK_COLORS["background"]))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 16, 16)

    def contextMenuEvent(self, event):
        self._menu = ContextMenu(self)
        self._menu.play_clicked.connect(self.on_play)
        self._menu.preview_clicked.connect(self.on_preview)
        self._menu.rename_clicked.connect(self.on_rename)
        self._menu.remove_clicked.connect(self.on_remove)
        self._menu.show_at(event.globalPos())

    def on_play(self):
        self._start_playback(preview=False)

    def on_preview(self):
        self._start_playback(preview=True)

    def _toggle_play(self):
        if self._playback_state != "idle":
            self._playback.stop(id(self))
        else:
            self.on_play()

    def _start_playback(self, *, preview: bool):
        if getattr(self, "_menu", None) is not None:
            self._menu.close()
        sound_path = self._get_sound_path()
        if sound_path is None:
            self._on_playback_error(id(self), "The sound file could not be found. Import it again.")
            return
        self._playback.play(sound_path, id(self), preview=preview)

    def _on_playback_state(self, owner, state: str):
        if owner != id(self):
            return
        self._playback_state = state
        active = state != "idle"
        self.play_button.set_playing(active)
        self.play_button.setAccessibleName(
            f"{'Stop' if active else 'Play'} {self.title.text()}"
        )
        self.play_button.setToolTip(
            "Preparing audio — click to cancel" if state == "preparing" else
            "Stop playback" if active else
            PLAY_TOOLTIP
        )

    def _on_playback_error(self, owner, message: str):
        if owner != id(self):
            return
        logger.get_logger("Audit").error("Couldn't play %s: %s", self.title.text(), message)
        # Nonmodal feedback keeps the stop control and the rest of the board usable.
        self._error_dialog = QMessageBox(QMessageBox.Warning, "Soundboard playback", message,
                                        QMessageBox.Ok, self)
        self._error_dialog.setAttribute(Qt.WA_DeleteOnClose)
        self._error_dialog.setWindowModality(Qt.NonModal)
        self._error_dialog.show()

    def _get_sound_path(self) -> Path | None:
        """Return this row's current, valid sound path from the database."""
        title = self.title.text()

        try:
            sounds = database.get_all_sounds()
        except Exception:
            logger.get_logger("Audit").exception(
                "Couldn't fetch the path for playing %s", title
            )
            return None

        matches = [sound for sound in sounds if sound.get("Title") == title]

        # Titles are not unique in the database. MainWindow supplies the path
        # used to create this row, so prefer the matching record when available.
        if self._sound_path is not None:
            matches = [
                sound
                for sound in matches
                if sound.get("Path")
                and Path(sound["Path"]).expanduser() == self._sound_path
            ]

        for sound in matches:
            raw_path = sound.get("Path")
            if not raw_path:
                continue

            sound_path = Path(raw_path).expanduser()
            if sound_path.is_file():
                return sound_path.resolve()

        logger.get_logger("Audit").warning(
            "Couldn't find a valid path for playing %s", title
        )
        return None

    def on_rename(self):
        pass

    def on_remove(self):
        self._playback.stop(id(self))
        database.remove_sound(self.title.text())
        logger.get_logger("Audit").info(f"Removed {self.title.text()}")
        self.deleteLater()
