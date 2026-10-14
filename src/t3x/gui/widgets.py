# SPDX-License-Identifier: GPL-2.0-or-later
"""Reusable widgets: chunk map, step list, banners, key/value boxes, tables, log view."""

from __future__ import annotations

import html
import time
from typing import Callable, Dict, Iterable, List, Optional, Sequence

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QHeaderView,
                               QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QSizePolicy,
                               QTableWidget, QTableWidgetItem, QWidget)

from . import theme as T

PENDING, SENDING, ACKED, FAILED = range(4)


class ChunkMap(QWidget):
    """One tile per 2048-byte chunk; colours show pending / sending / acknowledged / failed."""

    COLORS = {PENDING: T.TILE_IDLE, SENDING: T.ACCENT, ACKED: T.OK_TILE, FAILED: T.ERR}

    def __init__(self, total: int = 82, cols: int = 41, parent=None):
        super().__init__(parent)
        self.cols = cols
        self.state: List[int] = []
        self.reset(total)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def reset(self, total: int):
        self.state = [PENDING] * max(0, total)
        self._update_height()
        self.update()

    def _update_height(self):
        rows = max(1, (len(self.state) + self.cols - 1) // self.cols)
        self.setMinimumHeight(rows * 28)

    def set_progress(self, acked: int, sending: bool = True):
        for i in range(len(self.state)):
            self.state[i] = ACKED if i < acked else (SENDING if sending and i == acked else PENDING)
        self.update()

    def mark_failed(self, index0: int):
        if 0 <= index0 < len(self.state):
            self.state[index0] = FAILED
            self.update()

    def counts(self) -> Dict[int, int]:
        return {k: self.state.count(k) for k in self.COLORS}

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        g = 4
        w = (self.width() - g * (self.cols - 1)) / self.cols
        for i, st in enumerate(self.state):
            r, c = divmod(i, self.cols)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(self.COLORS[st]))
            p.drawRoundedRect(QRectF(c * (w + g), r * (w + g), w, w), 3, 3)


class StepList(QListWidget):
    """Connect / Verify / Flash / Confirm with done / current / pending states."""

    NAMES = ["1. Connect", "2. Verify", "3. Flash", "4. Confirm"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("steps")
        self.setFixedWidth(250)
        self.setFixedHeight(190)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        for n in self.NAMES:
            self.addItem(QListWidgetItem(n))
        self.set_step(0)

    def set_step(self, current: int, failed: bool = False):
        """current = index of the active step; 4 = all done."""
        for i in range(self.count()):
            it = self.item(i)
            name = self.NAMES[i]
            if i < current:
                it.setText("✔  " + name)
                it.setForeground(QColor(T.OK))
            elif i == current:
                it.setText(("✖  " if failed else "➜  ") + name)
                it.setForeground(QColor(T.ERR if failed else "#ff9d55"))
            else:
                it.setText("    " + name)
                it.setForeground(QColor(T.DIM))
        if current < self.count():
            self.setCurrentRow(current)
        else:
            self.clearSelection()


class Banner(QFrame):
    """Coloured message box: kind = warn | info | errbox | okbox."""

    def __init__(self, text: str = "", kind: str = "warn", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.label)
        self.set(text, kind)

    def set(self, text: str, kind: Optional[str] = None):
        if kind:
            self.setObjectName(kind)
            self.style().unpolish(self)
            self.style().polish(self)
        self.label.setText(text)
        self.setVisible(bool(text))


class KeyValueBox(QGroupBox):
    """Titled box of label/value rows that can be updated in place."""

    def __init__(self, title: str, keys: Sequence[str], parent=None):
        super().__init__(title, parent)
        self.form = QFormLayout(self)
        self.values: Dict[str, QLabel] = {}
        for k in keys:
            a = QLabel(k)
            a.setObjectName("muted")
            v = QLabel("—")
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.values[k] = v
            self.form.addRow(a, v)

    def set(self, **kv):
        for k, v in kv.items():
            key = k.replace("_", " ")
            lab = self.values.get(key) or self.values.get(k)
            if lab is not None:
                lab.setText("—" if v in (None, "") else str(v))

    def clear(self):
        for v in self.values.values():
            v.setText("—")


def make_table(headers: Sequence[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(list(headers))
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    return t


def fill_table(t: QTableWidget, rows: Iterable[Sequence[str]],
               colors: Optional[Dict[int, Callable[[str], Optional[str]]]] = None):
    rows = list(rows)
    t.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            it = QTableWidgetItem(str(v))
            it.setToolTip(str(v))                  # full text when a column truncates it
            if colors and c in colors:
                col = colors[c](str(v))
                if col:
                    it.setForeground(QColor(col))
            t.setItem(r, c, it)
        t.setRowHeight(r, 32)


class LogView(QPlainTextEdit):
    """Timestamped, colour-coded TX/RX/INFO/WARN/ERROR lines."""

    COLORS = {"TX": T.TX, "RX": T.OK, "WARN": T.WARN, "ERROR": T.ERR, "INFO": "#b9c0ca", "DEBUG": "#8a919e"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)
        self.lines: List[str] = []

    def add(self, kind: str, text: str):
        ts = time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"
        self.lines.append(f"{ts}  {kind:<5} {text}")
        col = self.COLORS.get(kind, "#b9c0ca")
        self.appendHtml(f'<span style="color:#5b6370">{ts}</span>&nbsp;&nbsp;'
                        f'<span style="color:{col}">{kind:<5}&nbsp;{html.escape(text)}</span>')

    def clear_all(self):
        self.lines.clear()
        self.clear()


def h1(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("h1")
    return lab


def muted(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("muted")
    lab.setWordWrap(True)
    return lab
