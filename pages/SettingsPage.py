import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QDialog, QLabel, QPushButton, QSlider


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "settings.json"
DEFAULT_THEMES_DIR = PROJECT_ROOT / "themes"
REQUIRED_THEME_COLORS = frozenset(
    {"foreground", "background", "play_btn", "neutral"}
)


class SettingsPage(QDialog):
    """Modal settings window based on the Figma settings page."""

    settings_saved = Signal(dict)

    def __init__(
        self,
        parent=None,
        *,
        settings_path: Path = DEFAULT_SETTINGS_PATH,
        themes_dir: Path = DEFAULT_THEMES_DIR,
    ):
        super().__init__(parent)
        self._settings_path = Path(settings_path)
        self._themes_dir = Path(themes_dir)

        self.setObjectName("settingsPage")
        self.setWindowTitle("Settings")
        self.setFixedSize(350, 201)
        self.setModal(True)
        self.setWindowModality(Qt.WindowModal)
        self.setStyleSheet(
            """
            QDialog#settingsPage {
                background-color: #282a36;
            }
            QDialog#settingsPage QLabel {
                background: transparent;
                color: #bfbfbf;
                font-size: 14px;
            }
            """
        )

        self.theme_label = QLabel("Theme:", self)
        self.theme_label.setGeometry(35, 42, 60, 20)

        # These controls intentionally keep Qt's native platform styling.
        self.theme_combo = QComboBox(self)
        self.theme_combo.setGeometry(107, 39, 190, 26)

        self.volume_label = QLabel("Max Volume:", self)
        self.volume_label.setGeometry(35, 82, 90, 20)

        self.volume_slider = QSlider(Qt.Horizontal, self)
        self.volume_slider.setGeometry(137, 82, 168, 20)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setPageStep(10)

        self.save_button = QPushButton("Save", self)
        self.save_button.setObjectName("saveButton")
        self.save_button.setGeometry(180, 151, 70, 33)

        self.quit_button = QPushButton("Quit", self)
        self.quit_button.setObjectName("quitButton")
        self.quit_button.setGeometry(260, 151, 70, 33)

        self._populate_themes()
        self._load_values()

        self.save_button.clicked.connect(self.save_settings)
        self.quit_button.clicked.connect(self.reject)

    def _read_settings(self) -> dict:
        try:
            with self._settings_path.open(encoding="utf-8") as settings_file:
                settings = json.load(settings_file)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}
        return settings if isinstance(settings, dict) else {}

    def _populate_themes(self):
        self.theme_combo.clear()

        if self._themes_dir.is_dir():
            for theme_path in sorted(self._themes_dir.glob("*.json")):
                try:
                    with theme_path.open(encoding="utf-8") as theme_file:
                        theme = json.load(theme_file)
                except (json.JSONDecodeError, OSError):
                    continue

                if self._is_valid_theme(theme):
                    self.theme_combo.addItem(theme["name"], theme_path.stem)

        self.theme_combo.setEnabled(self.theme_combo.count() > 0)

    @staticmethod
    def _is_valid_theme(theme) -> bool:
        if not isinstance(theme, dict):
            return False

        name = theme.get("name")
        colors = theme.get("colors")
        if not isinstance(name, str) or not name.strip():
            return False
        if not isinstance(colors, dict) or not REQUIRED_THEME_COLORS <= colors.keys():
            return False

        for color_name in REQUIRED_THEME_COLORS:
            color = colors[color_name]
            if not isinstance(color, str) or len(color) != 7 or color[0] != "#":
                return False
            try:
                int(color[1:], 16)
            except ValueError:
                return False

        return True

    def _load_values(self):
        settings = self._read_settings()

        theme = str(settings.get("theme", "dracula"))
        theme_index = self.theme_combo.findData(theme)
        if theme_index >= 0:
            self.theme_combo.setCurrentIndex(theme_index)

        try:
            max_volume = int(settings.get("max_volume", 80))
        except (TypeError, ValueError):
            max_volume = 80
        self.volume_slider.setValue(max(0, min(100, max_volume)))

    def save_settings(self):
        settings = self._read_settings()
        selected_theme = self.theme_combo.currentData()
        if selected_theme is not None:
            settings["theme"] = selected_theme
        settings["max_volume"] = self.volume_slider.value()

        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        with self._settings_path.open("w", encoding="utf-8") as settings_file:
            json.dump(settings, settings_file, indent=4)
            settings_file.write("\n")

        self.settings_saved.emit(settings)
