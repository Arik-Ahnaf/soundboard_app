from PySide6.QtWidgets import QScrollArea, QFrame
from PySide6.QtCore import Qt


class FlowScrollArea(QScrollArea):
    """
    Wraps a widget using FlowLayout so it scrolls vertically once content
    exceeds the available height. QScrollArea doesn't recompute
    height-for-width layouts on its own, so we do it on every resize.
    """
 
    def __init__(self, content_widget, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidget(content_widget)
 
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_content_height()
 
    def _sync_content_height(self):
        widget = self.widget()
        layout = widget.layout() if widget else None
        if layout is None or not layout.hasHeightForWidth():
            return
        width = self.viewport().width()
        height = layout.heightForWidth(width)
        widget.setFixedHeight(height)
