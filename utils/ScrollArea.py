from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtWidgets import QFrame, QScrollArea


class FlowScrollArea(QScrollArea):
    """
    Wraps a height-for-width layout so it scrolls vertically once its content
    exceeds the available height. QScrollArea does not recalculate that
    height when layout items are added or removed, so listen for layout
    requests from the content widget as well as viewport resizes.
    """
 
    def __init__(self, content_widget, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidget(content_widget)
        content_widget.installEventFilter(self)
        self.sync_content_height()
 
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.sync_content_height()

    def eventFilter(self, watched, event):
        if watched is self.widget() and event.type() == QEvent.LayoutRequest:
            # Let Qt finish adding/removing the item before measuring the
            # layout; doing this synchronously observes the previous layout.
            QTimer.singleShot(0, self.sync_content_height)
        return super().eventFilter(watched, event)

    def sync_content_height(self):
        widget = self.widget()
        layout = widget.layout() if widget else None
        if layout is None or not layout.hasHeightForWidth():
            return

        width = self.viewport().width()
        height = layout.heightForWidth(width)
        # A minimum preserves the full layout height for scrolling without
        # preventing QScrollArea from expanding the content to the viewport.
        widget.setMinimumHeight(height)
        widget.updateGeometry()
