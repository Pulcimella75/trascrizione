"""
ui/queue_panel.py
Pannello lista file in coda con stato visivo.
"""

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLabel,
    QAbstractItemView,
)


class FileStatus(Enum):
    WAITING  = "In attesa"
    RUNNING  = "In corso..."
    DONE     = "Completato"
    ERROR    = "Errore"
    SKIPPED  = "Saltato"


STATUS_COLORS = {
    FileStatus.WAITING:  "#8890aa",
    FileStatus.RUNNING:  "#4a90d9",
    FileStatus.DONE:     "#4aaa6a",
    FileStatus.ERROR:    "#cc5555",
    FileStatus.SKIPPED:  "#666688",
}

STATUS_ICONS = {
    FileStatus.WAITING:  "⏳",
    FileStatus.RUNNING:  "🔄",
    FileStatus.DONE:     "✅",
    FileStatus.ERROR:    "❌",
    FileStatus.SKIPPED:  "⏭",
}


@dataclass
class QueueItem:
    file_path: str
    status: FileStatus = FileStatus.WAITING
    model: str = "large-v2"
    language: str = "auto"
    start_sec: float = 0.0
    end_sec: float = 0.0
    error_msg: str = ""
    output_path: str = ""
    is_local: bool = False
    source_url: str = ""
    download_retries: int = 0

    @property
    def display_name(self) -> str:
        name = os.path.basename(self.file_path)
        if self.is_local:
            return f"💾 {name}"
        return name

    @property
    def range_str(self) -> str:
        def fmt(s):
            s = int(s)
            return f"{s // 60:02d}:{s % 60:02d}"
        if self.start_sec == 0 and self.end_sec == 0:
            return "Intero file"
        elif self.end_sec == 0:
            return f"{fmt(self.start_sec)} → fine"
        else:
            return f"{fmt(self.start_sec)} → {fmt(self.end_sec)}"


class QueuePanel(QWidget):
    """
    Pannello coda file con tabella e controlli.

    Segnali:
        item_selected(QueueItem)    un elemento è selezionato
        queue_cleared()
    """

    item_selected = pyqtSignal(object)
    queue_cleared = pyqtSignal()

    COL_NAME    = 0
    COL_MODEL   = 1
    COL_LANG    = 2
    COL_RANGE   = 3
    COL_STATUS  = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[QueueItem] = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        lbl = QLabel("📋  Coda di elaborazione")
        lbl.setStyleSheet("font-size: 14px; font-weight: 700; color: #7eb8f7;")
        self.lbl_count = QLabel("0 file")
        self.lbl_count.setStyleSheet("color: #5a6080; font-size: 12px;")
        header.addWidget(lbl)
        header.addStretch()
        header.addWidget(self.lbl_count)
        layout.addLayout(header)

        # Tabella
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["File", "Modello", "Lingua", "Intervallo", "Stato"])
        self.table.horizontalHeader().setSectionResizeMode(
            self.COL_NAME, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            self.COL_MODEL, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            self.COL_LANG, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            self.COL_RANGE, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            self.COL_STATUS, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table)

        # Pulsanti
        btn_row = QHBoxLayout()
        self.btn_remove = QPushButton("🗑  Rimuovi selezionato")
        self.btn_remove.setObjectName("btn_flat")
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_clear = QPushButton("✕  Svuota coda")
        self.btn_clear.setObjectName("btn_flat")
        self.btn_clear.clicked.connect(self._clear_queue)
        btn_row.addWidget(self.btn_remove)
        btn_row.addWidget(self.btn_clear)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    # ── API pubblica ───────────────────────────────────────────────────────

    def add_item(self, item: QueueItem):
        """Aggiunge un elemento alla coda."""
        self._items.append(item)
        self._append_row(item)
        self._update_count()

    def update_status(self, file_path: str, status: FileStatus,
                      error_msg: str = ""):
        """Aggiorna lo stato di un elemento per percorso file."""
        for i, item in enumerate(self._items):
            if item.file_path == file_path:
                item.status = status
                item.error_msg = error_msg
                self._refresh_row(i)
                break

    def get_pending(self) -> list[QueueItem]:
        return [it for it in self._items if it.status == FileStatus.WAITING]

    def clear(self):
        self._items.clear()
        self.table.setRowCount(0)
        self._update_count()
        self.queue_cleared.emit()

    def get_all(self) -> list[QueueItem]:
        return list(self._items)

    # ── Rendering ─────────────────────────────────────────────────────────

    def _append_row(self, item: QueueItem):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._fill_row(row, item)

    def _fill_row(self, row: int, item: QueueItem):
        self.table.setItem(row, self.COL_NAME,
                           self._cell(item.display_name))
        self.table.setItem(row, self.COL_MODEL,
                           self._cell(item.model))
        self.table.setItem(row, self.COL_LANG,
                           self._cell(item.language))
        self.table.setItem(row, self.COL_RANGE,
                           self._cell(item.range_str))

        status_text = f"{STATUS_ICONS[item.status]}  {item.status.value}"
        status_cell = self._cell(status_text)
        status_cell.setForeground(QColor(STATUS_COLORS[item.status]))
        self.table.setItem(row, self.COL_STATUS, status_cell)

        if item.error_msg:
            self.table.item(row, self.COL_STATUS).setToolTip(item.error_msg)

    def _refresh_row(self, index: int):
        self._fill_row(index, self._items[index])

    @staticmethod
    def _cell(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        return item

    def _update_count(self):
        n = len(self._items)
        self.lbl_count.setText(f"{n} file" if n != 1 else "1 file")

    # ── Slot ──────────────────────────────────────────────────────────────

    def _on_selection_changed(self):
        rows = self.table.selectedItems()
        if rows:
            row = self.table.currentRow()
            if 0 <= row < len(self._items):
                self.item_selected.emit(self._items[row])

    def _remove_selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._items):
            return
        item = self._items[row]
        if item.status == FileStatus.RUNNING:
            return  # non rimuovere file in elaborazione
        self._items.pop(row)
        self.table.removeRow(row)
        self._update_count()

    def _clear_queue(self):
        # Mantieni solo quelli in corso
        running = [it for it in self._items if it.status == FileStatus.RUNNING]
        self._items.clear()
        self.table.setRowCount(0)
        for it in running:
            self._items.append(it)
            self._append_row(it)
        self._update_count()
        if not running:
            self.queue_cleared.emit()
