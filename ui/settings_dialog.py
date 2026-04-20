"""
ui/settings_dialog.py
Dialog impostazioni generali dell'applicazione.
"""

from pathlib import Path
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog,
    QComboBox, QGroupBox, QDialogButtonBox, QCheckBox,
)

from config.settings import AppSettings
from core.transcriber import LANGUAGE_CODES
from core.model_manager import AVAILABLE_MODELS


class SettingsDialog(QDialog):
    """Dialog impostazioni: cartelle, modello default, lingua default."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = AppSettings()
        self.setWindowTitle("Impostazioni")
        self.setMinimumWidth(560)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        # ── Cartelle ──────────────────────────────────────────────────────
        folder_box = QGroupBox("📁  Cartelle")
        form = QFormLayout(folder_box)
        form.setSpacing(10)

        self.edit_output = self._dir_row(form, "Cartella output trascrizioni:")
        self.edit_models = self._dir_row(form, "Cartella modelli faster-whisper:")
        self.edit_temp   = self._dir_row(form, "Cartella temp YouTube:")
        layout.addWidget(folder_box)

        # ── Trascrizione ──────────────────────────────────────────────────
        tx_box = QGroupBox("🎙  Trascrizione")
        tx_form = QFormLayout(tx_box)
        tx_form.setSpacing(10)

        self.combo_model = QComboBox()
        self.combo_model.addItems(list(AVAILABLE_MODELS.keys()))
        tx_form.addRow("Modello default:", self.combo_model)

        self.combo_lang = QComboBox()
        for display in LANGUAGE_CODES.keys():
            self.combo_lang.addItem(display)
        tx_form.addRow("Lingua default:", self.combo_lang)

        layout.addWidget(tx_box)

        # ── Bottoni ───────────────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._save_and_close)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _dir_row(self, form: QFormLayout, label: str) -> QLineEdit:
        row = QHBoxLayout()
        edit = QLineEdit()
        edit.setReadOnly(True)
        btn = QPushButton("📁")
        btn.setFixedWidth(34)
        btn.setObjectName("btn_flat")
        btn.clicked.connect(lambda _, e=edit: self._browse(e))
        row.addWidget(edit)
        row.addWidget(btn)
        form.addRow(label, row)
        return edit

    def _browse(self, edit: QLineEdit):
        path = QFileDialog.getExistingDirectory(
            self, "Seleziona cartella", edit.text() or "")
        if path:
            edit.setText(path)

    def _load(self):
        self.edit_output.setText(self._settings.output_dir)
        self.edit_models.setText(self._settings.model_dir)
        self.edit_temp.setText(self._settings.temp_dir)

        model_idx = self.combo_model.findText(self._settings.default_model)
        if model_idx >= 0:
            self.combo_model.setCurrentIndex(model_idx)

        lang_idx = self.combo_lang.findText(self._settings.default_language)
        if lang_idx >= 0:
            self.combo_lang.setCurrentIndex(lang_idx)

    def _save_and_close(self):
        self._settings.output_dir   = self.edit_output.text()
        self._settings.model_dir    = self.edit_models.text()
        self._settings.temp_dir     = self.edit_temp.text()
        self._settings.default_model   = self.combo_model.currentText()
        self._settings.default_language = self.combo_lang.currentText()
        self._settings.ensure_dirs()
        self.accept()
