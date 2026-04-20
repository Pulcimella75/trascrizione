"""
ui/model_manager_dialog.py
Dialog per scaricare, gestire e selezionare i modelli faster-whisper.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QLineEdit, QFileDialog,
    QProgressBar, QMessageBox, QDialogButtonBox, QAbstractItemView,
)

from config.settings import AppSettings
from core.model_manager import (
    AVAILABLE_MODELS, MODEL_SIZES_MB, ModelDownloaderWorker,
    ModelDeleter, get_local_models,
)


class ModelManagerDialog(QDialog):
    """
    Dialog per gestire i modelli faster-whisper:
    - Visualizza stato (scaricato / non presente)
    - Scarica modelli da HuggingFace
    - Elimina modelli locali
    - Imposta modello default
    - Cambia cartella modelli
    """

    model_default_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = AppSettings()
        self._worker: ModelDownloaderWorker | None = None
        self._deleter: ModelDeleter | None = None

        self.setWindowTitle("Gestione Modelli faster-whisper")
        self.setMinimumSize(720, 520)
        self._build_ui()
        self._refresh_table()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Cartella modelli
        dir_row = QHBoxLayout()
        lbl_dir = QLabel("📁  Cartella modelli:")
        lbl_dir.setStyleSheet("font-weight: 600;")
        self.edit_dir = QLineEdit(self._settings.model_dir)
        self.edit_dir.setReadOnly(True)
        self.btn_browse = QPushButton("Sfoglia...")
        self.btn_browse.setObjectName("btn_flat")
        self.btn_browse.clicked.connect(self._browse_dir)
        dir_row.addWidget(lbl_dir)
        dir_row.addWidget(self.edit_dir)
        dir_row.addWidget(self.btn_browse)
        layout.addLayout(dir_row)

        # Tabella modelli
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Modello", "Dimensione", "Stato", "Default", "Azioni"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        layout.addWidget(self.table)

        # Progress download
        self.lbl_progress = QLabel("")
        self.lbl_progress.setStyleSheet("color: #7eb8f7; font-size: 12px;")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.lbl_progress)
        layout.addWidget(self.progress_bar)

        # Chiudi
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ── Tabella ───────────────────────────────────────────────────────────

    def _refresh_table(self):
        local = set(get_local_models(self._settings.model_dir))
        default_model = self._settings.default_model

        self.table.setRowCount(0)
        for row, (name, _) in enumerate(AVAILABLE_MODELS.items()):
            self.table.insertRow(row)
            size_mb = MODEL_SIZES_MB[name]
            is_local = name in local
            is_default = name == default_model

            # Nome
            self.table.setItem(row, 0, self._cell(name))
            # Dimensione
            self.table.setItem(row, 1, self._cell(f"{size_mb} MB"))
            # Stato
            status_text = "✅ Scaricato" if is_local else "— Non presente"
            status_cell = self._cell(status_text)
            status_cell.setForeground(
                Qt.green if is_local else Qt.darkGray)
            self.table.setItem(row, 2, status_cell)
            # Default
            def_cell = self._cell("⭐ Default" if is_default else "")
            self.table.setItem(row, 3, def_cell)
            # Pulsanti azione (widget nella cella)
            self._set_action_widget(row, name, is_local, is_default)

    def _set_action_widget(self, row: int, name: str,
                           is_local: bool, is_default: bool):
        from PyQt5.QtWidgets import QWidget, QHBoxLayout as HL
        container = QWidget()
        hl = HL(container)
        hl.setContentsMargins(4, 2, 4, 2)
        hl.setSpacing(6)

        if is_local:
            btn_del = QPushButton("🗑 Elimina")
            btn_del.setObjectName("btn_danger")
            btn_del.setFixedHeight(26)
            btn_del.clicked.connect(lambda _, n=name: self._delete_model(n))
            hl.addWidget(btn_del)

            if not is_default:
                btn_default = QPushButton("⭐ Imposta default")
                btn_default.setObjectName("btn_flat")
                btn_default.setFixedHeight(26)
                btn_default.clicked.connect(lambda _, n=name: self._set_default(n))
                hl.addWidget(btn_default)
        else:
            btn_dl = QPushButton("⬇ Scarica")
            btn_dl.setFixedHeight(26)
            btn_dl.clicked.connect(lambda _, n=name: self._download_model(n))
            hl.addWidget(btn_dl)

        hl.addStretch()
        self.table.setCellWidget(row, 4, container)
        self.table.setRowHeight(row, 36)

    @staticmethod
    def _cell(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        return item

    # ── Azioni ────────────────────────────────────────────────────────────

    def _browse_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "Seleziona cartella modelli", self._settings.model_dir)
        if path:
            self._settings.model_dir = path
            self.edit_dir.setText(path)
            self._refresh_table()

    def _set_default(self, name: str):
        self._settings.default_model = name
        self.model_default_changed.emit(name)
        self._refresh_table()

    def _download_model(self, name: str):
        if self._worker and self._worker.isRunning():
            QMessageBox.warning(self, "Download in corso",
                                "Attendi il completamento del download corrente.")
            return
        self._worker = ModelDownloaderWorker(name, self._settings.model_dir, self)
        self._worker.progress.connect(self.progress_bar.setValue)
        self._worker.status.connect(self.lbl_progress.setText)
        self._worker.finished.connect(self._on_download_finished)
        self._worker.error.connect(self._on_download_error)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self._worker.start()

    def _on_download_finished(self, name: str):
        self.progress_bar.setVisible(False)
        self.lbl_progress.setText(f"✅ {name} scaricato correttamente.")
        self._refresh_table()

    def _on_download_error(self, msg: str):
        self.progress_bar.setVisible(False)
        self.lbl_progress.setText("❌ Errore download.")
        QMessageBox.critical(self, "Errore download", msg)

    def _delete_model(self, name: str):
        if name == self._settings.default_model:
            QMessageBox.warning(self, "Impossibile",
                                "Non puoi eliminare il modello impostato come default.")
            return
        reply = QMessageBox.question(
            self, "Elimina modello",
            f"Eliminare il modello '{name}' dalla cartella locale?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._deleter = ModelDeleter(name, self._settings.model_dir, self)
        self._deleter.finished.connect(lambda n: (
            self.lbl_progress.setText(f"🗑 {n} eliminato."),
            self._refresh_table(),
        ))
        self._deleter.error.connect(
            lambda e: QMessageBox.critical(self, "Errore", e))
        self._deleter.start()
