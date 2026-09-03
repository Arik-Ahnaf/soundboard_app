import json
from pathlib import Path
from weakref import ReferenceType, ref

from utils import database
from components.ContextMenu import ContextMenu
from PySide6.QtCore import QEasingCurve, Qt, QPointF, QUrl, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
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
THEME_PATH = Path(__file__).resolve().parent.parent / "themes" / "dark.json"

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
        painter.setBrush(QColor(DARK_COLORS["neutral"]))

        d = self._dot_size
        slot = self.height() / self._count
        for i in range(self._count):
            cy = slot * i + slot / 2
            painter.drawEllipse(QPointF(d / 2, cy), d / 2, d / 2)


class SoundItem(QWidget):
    """Soundboard row: play button, title/duration, and a hamburger menu."""

    _active_preview_player_ref: ReferenceType[QMediaPlayer] | None = None

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
        self._preview_player = None
        self._preview_output = None

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
        pass

    def on_preview(self):
        sound_path = self._get_preview_path()
        if sound_path is None:
            return

        default_device = QMediaDevices.defaultAudioOutput()
        if default_device.isNull():
            logger.get_logger("Audit").warning(
                "Couldn't preview %s because no default audio output is available",
                self.title.text(),
            )
            return

        if self._preview_player is None:
            self._preview_output = QAudioOutput(self)
            self._preview_player = QMediaPlayer(self)
            self._preview_player.setAudioOutput(self._preview_output)
            self._preview_player.errorOccurred.connect(self._on_preview_error)

        active_player_ref = SoundItem._active_preview_player_ref
        active_player = active_player_ref() if active_player_ref is not None else None
        if active_player is not None and active_player is not self._preview_player:
            try:
                active_player.stop()
            except RuntimeError:
                # Its owning row may already have been deleted by Qt.
                pass

        # Restart the sound when Preview is clicked again while it is playing.
        self._preview_player.stop()
        self._preview_output.setDevice(default_device)
        self._preview_player.setSource(QUrl.fromLocalFile(str(sound_path)))
        self._preview_player.play()
        SoundItem._active_preview_player_ref = ref(self._preview_player)

    def _get_preview_path(self) -> Path | None:
        """Return this row's current, valid sound path from the database."""
        title = self.title.text()

        try:
            sounds = database.get_all_sounds()
        except Exception:
            logger.get_logger("Audit").exception(
                "Couldn't fetch the path for previewing %s", title
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
            "Couldn't find a valid path for previewing %s", title
        )
        return None

    def _on_preview_error(self, error, error_string):
        logger.get_logger("Audit").error(
            "Couldn't preview %s: %s", self.title.text(), error_string or error
        )

    def on_rename(self):
        pass

    def on_remove(self):
        database.remove_sound(self.title.text())
        logger.get_logger("Audit").info(f"Removed {self.title.text()}")
        self.deleteLater()
