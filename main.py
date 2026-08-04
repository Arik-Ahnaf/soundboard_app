import sys
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from components.ListItem import ListItem
from components.ContextMenu import ContextMenu


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Soundboard")
        self.setGeometry(100, 100, 500, 500)

        # Create menu bar
        menubar = self.menuBar()
        menubar.addMenu("File")
        menubar.addMenu("Settings")
        menubar.addMenu("Help")
        menubar.addMenu("About")

        # Create central widget and place ListItem centered
        central_widget = QWidget()
        central_layout = QVBoxLayout(central_widget)
        central_layout.setContentsMargins(24, 24, 24, 24)
        central_widget.setStyleSheet("background-color: gray;")
        central_layout.addStretch()
        central_layout.addWidget(
            ListItem("Sound effect.wav", "5s"), alignment=Qt.AlignCenter
        )
        central_layout.addStretch()
        self.setCentralWidget(central_widget)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
