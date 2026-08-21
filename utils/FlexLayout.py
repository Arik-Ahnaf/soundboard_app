from PySide6.QtWidgets import QLayout
from PySide6.QtCore import Qt, QRect, QSize, QPoint


class FlexLayout(QLayout):
    def __init__(self, parent=None, margin=0, h_spacing=10, v_spacing=10):
        super().__init__(parent)
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._items = []
        self.setContentsMargins(margin, margin, margin, margin)
 
    # --- required QLayout overrides ---
    def addItem(self, item):
        self._items.append(item)
        self.invalidate()
 
    def count(self):
        return len(self._items)
 
    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None
 
    def takeAt(self, index):
        if not 0 <= index < len(self._items):
            return None
        item = self._items.pop(index)
        self.invalidate()
        return item
 
    def expandingDirections(self):
        return Qt.Orientation(0)
 
    def hasHeightForWidth(self):
        return True
 
    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)
 
    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)
 
    def sizeHint(self):
        return self.minimumSize()
 
    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(self._item_size(item))
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _item_size(self, item):
        """Return a stable size while widgets are being reparented.

        QScrollArea reparents its content to the viewport. During that
        transition, QWidgetItem can report a 0x0 hint even though its widget
        already has a valid fixed/minimum size.
        """
        size = item.sizeHint().expandedTo(item.minimumSize())
        widget = item.widget()
        if widget is not None:
            size = size.expandedTo(widget.sizeHint())
            size = size.expandedTo(widget.minimumSize())
        return size
 
    # --- core flex-wrap + centering logic ---
    def _do_layout(self, rect, test_only):
        left, top, right, bottom = self.getContentsMargins()
        effective = rect.adjusted(left, top, -right, -bottom)
        x, y = effective.x(), effective.y()
        line_height = 0
        row_items = []

        def place_row(items, row_y, row_height):
            if not items:
                return
            row_width = sum(self._item_size(it).width() for it in items)
            row_width += self._h_spacing * (len(items) - 1)
            # justify-content: center
            item_x = effective.x() + max(0, (effective.width() - row_width) // 2)
            for it in items:
                sz = self._item_size(it)
                # align-items: center
                item_y = row_y + (row_height - sz.height()) // 2
                if not test_only:
                    it.setGeometry(QRect(QPoint(item_x, item_y), sz))
                item_x += sz.width() + self._h_spacing
 
        for item in self._items:
            sz = self._item_size(item)
            next_x = x + sz.width()
            if next_x > effective.right() and line_height > 0:
                place_row(row_items, y, line_height)
                row_items = []
                x = effective.x()
                y += line_height + self._v_spacing
                next_x = x + sz.width()
                line_height = 0
 
            row_items.append(item)
            x = next_x + self._h_spacing
            line_height = max(line_height, sz.height())
 
        place_row(row_items, y, line_height)
        return y + line_height - rect.y() + bottom
