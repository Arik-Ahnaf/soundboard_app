import sys
import typing
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog
)
from components.ListItem import ListItem
from components.ContextMenu import ContextMenu
from utils.FlexLayout import FlexLayout
from utils.ScrollArea import FlowScrollArea 
import json
from pathlib import Path
from mutagen import File as MutagenFile
import sqlite3
from logging.handlers import RotatingFileHandler
import logging
from utils import database
from utils.logger import get_logger


class MainWindow(QMainWindow):


    def __init__(self):

        super().__init__()
        self.setWindowTitle("Soundboard")
        self.setGeometry(100, 100, 500, 500)
        self.logger = get_logger("Audit")

        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        menubar.addMenu("Settings")
        menubar.addMenu("Help")
        menubar.addMenu("About")

        import_action = file_menu.addAction("Import")
        import_action.triggered.connect(self.on_import_sounds)

        container = QWidget()
        self.flex_layout = FlexLayout(container, margin=20, h_spacing=10, v_spacing=10)
        container.setLayout(self.flex_layout)

        self.scroll_area = FlowScrollArea(container)
        self.setCentralWidget(self.scroll_area)
        database.initiate_db()
        valid_sounds = self._validate_files()
        self._load_files(valid_sounds)

    def _validate_files(self):

        sounds = database.get_all_sounds()
        valid_sounds = []
        invalid_sounds = []

        for sound in sounds:
            sound_path = sound.get("Path")
            if sound_path and Path(sound_path).is_file():
                valid_sounds.append(sound)
            else:
                invalid_sounds.append(sound)

        if invalid_sounds:
            self.logger.warning(f"Couldn't validate paths for {len(invalid_sounds)} sounds")

        return valid_sounds

    def _load_files(self, sounds: list[dict[str, object]]):

        if not sounds:
            return

        # Clear current elements and then re-render
        while self.flex_layout.count():
            item = self.flex_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for sound in sounds: 

            item = ListItem(title=sound["Title"], duration=sound["Duration"], path=sound["Path"])
            self.flex_layout.addWidget(item)

        # Loading may occur before Qt processes the layout-request event, so
        # update the scrollable height immediately as well.
        self.scroll_area.sync_content_height()
        self.logger.info("Initialized all sounds")

    def on_import_sounds(self):

        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Import Sound Files",
            "",
            "Audio Files (*.mp3 *.wav *.ogg *.flac *.m4a *.aac);;All Files (*)"
        )

        if not files:
            return

        for file_path in files:
            path = Path(file_path)
            title = path.stem

            try:
                audio = MutagenFile(file_path)
                duration = int(audio.info.length) if audio and audio.info else 0
            except Exception:
                duration = 0

            database.add_sound(title, duration, str(path))

        self.logger.info(f"Added {len(files)} sounds")
        self._load_files(self._validate_files())


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
