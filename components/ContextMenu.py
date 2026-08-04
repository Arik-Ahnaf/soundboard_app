from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGraphicsDropShadowEffect
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPushButton,
    QFrame,
)


class MenuButton(QPushButton):
    def __init__(
        self,
        text,
        hover_color="#D9D9D9",
        hover_text="black",
        parent=None,
    ):
        super().__init__(text, parent)

        self.hover_color = hover_color
        self.hover_text = hover_text

        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(130, 30)
        self.setStyleSheet(self._normal_style())

    def enterEvent(self, event):
        self.setStyleSheet(self._hover_style())
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(self._normal_style())
        super().leaveEvent(event)

    def _normal_style(self):
        return """
        QPushButton {
            border: none;
            border-radius: 15px;
            background: white;
            color: black;
            font-size: 14px;
        }
        """

    def _hover_style(self):
        return f"""
        QPushButton {{
            border: none;
            border-radius: 15px;
            background: {self.hover_color};
            color: {self.hover_text};
            font-size: 14px;
        }}
        """


class ContextMenu(QWidget):
    playClicked = Signal()
    previewClicked = Signal()
    renameClicked = Signal()
    removeClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # Design dimensions (150x170) increased to make room for box shadow
        self.setFixedSize(166, 186)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(8, 8, 8, 8)

        self.card = QFrame()
        self.card.setStyleSheet("""
            QFrame {
                background: white;
                border-radius: 16px;
            }
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 40))
        self.card.setGraphicsEffect(shadow)

        outer_layout.addWidget(self.card)

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignCenter)

        self.playButton = MenuButton(
            "Play",
            hover_color="#19C463",
            hover_text="white",
        )

        self.previewButton = MenuButton("Preview")

        self.renameButton = MenuButton("Rename")

        self.removeButton = MenuButton(
            "Remove",
            hover_color="#D81E5B",
            hover_text="white",
        )

        layout.addWidget(self.playButton)
        layout.addWidget(self.previewButton)
        layout.addWidget(self.renameButton)
        layout.addWidget(self.removeButton)

        self.playButton.clicked.connect(self.playClicked)
        self.previewButton.clicked.connect(self.previewClicked)
        self.renameButton.clicked.connect(self.renameClicked)
        self.removeButton.clicked.connect(self.removeClicked)

    def show_at(self, global_pos):
        screen = QGuiApplication.screenAt(global_pos) or QGuiApplication.primaryScreen()
        rect = screen.availableGeometry()
        x = min(global_pos.x(), rect.right() - self.width())
        y = min(global_pos.y(), rect.bottom() - self.height())
        self.move(max(rect.left(), x), max(rect.top(), y))
        self.show()