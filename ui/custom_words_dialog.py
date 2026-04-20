"""
ui/custom_words_dialog.py
Dialog per gestire il dizionario di parole/frasi personalizzate.
Le parole vengono iniettate come initial_prompt in faster-whisper.
"""

import os
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QListWidgetItem, QLineEdit, QLabel, QFileDialog, QMessageBox,
    QDialogButtonBox, QAbstractItemView,
)

from config.settings import AppSettings


class CustomWordsDialog(QDialog):
    """
    Dialog per aggiungere/rimuovere parole personalizzate
    che aiutano Whisper a trascrivere correttamente termini specifici.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = AppSettings()
        self.setWindowTitle("Dizionario Parole Personalizzate")
        self.setMinimumSize(520, 460)
        self._build_ui()
        self._load_words()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Descrizione
        desc = QLabel(
            "Aggiungi nomi propri, termini tecnici o parole che Whisper\n"
            "tende a sbagliare. Verranno usate come suggerimento durante la trascrizione."
        )
        desc.setStyleSheet("color: #8890aa; font-size: 12px;")
        layout.addWidget(desc)

        # Input + aggiungi
        input_row = QHBoxLayout()
        self.edit_word = QLineEdit()
        self.edit_word.setPlaceholderText("Scrivi una parola o frase...")
        self.edit_word.returnPressed.connect(self._add_word)
        self.btn_add = QPushButton("➕  Aggiungi")
        self.btn_add.setObjectName("btn_success")
        self.btn_add.clicked.connect(self._add_word)
        input_row.addWidget(self.edit_word)
        input_row.addWidget(self.btn_add)
        layout.addLayout(input_row)

        # Lista parole
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_widget.setAlternatingRowColors(True)
        layout.addWidget(self.list_widget)

        # Conta
        self.lbl_count = QLabel("0 parole")
        self.lbl_count.setStyleSheet("color: #5a6080; font-size: 12px;")
        layout.addWidget(self.lbl_count)

        # Pulsanti azioni
        action_row = QHBoxLayout()
        self.btn_remove = QPushButton("🗑  Rimuovi selezionati")
        self.btn_remove.setObjectName("btn_flat")
        self.btn_remove.clicked.connect(self._remove_selected)

        self.btn_import = QPushButton("📥  Importa da TXT")
        self.btn_import.setObjectName("btn_flat")
        self.btn_import.clicked.connect(self._import_txt)

        self.btn_export = QPushButton("📤  Esporta TXT")
        self.btn_export.setObjectName("btn_flat")
        self.btn_export.clicked.connect(self._export_txt)

        self.btn_clear_all = QPushButton("✕  Svuota tutto")
        self.btn_clear_all.setObjectName("btn_flat")
        self.btn_clear_all.clicked.connect(self._clear_all)

        action_row.addWidget(self.btn_remove)
        action_row.addWidget(self.btn_import)
        action_row.addWidget(self.btn_export)
        action_row.addStretch()
        action_row.addWidget(self.btn_clear_all)
        layout.addLayout(action_row)

        # OK / Annulla
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._save_and_close)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ── Dati ──────────────────────────────────────────────────────────────

    def _load_words(self):
        self.list_widget.clear()
        for word in self._settings.custom_words:
            self.list_widget.addItem(QListWidgetItem(word))
        self._update_count()

    def _get_words(self) -> list[str]:
        words = []
        for i in range(self.list_widget.count()):
            w = self.list_widget.item(i).text().strip()
            if w:
                words.append(w)
        return words

    def _update_count(self):
        n = self.list_widget.count()
        self.lbl_count.setText(f"{n} parole" if n != 1 else "1 parola")

    # ── Azioni ────────────────────────────────────────────────────────────

    def _add_word(self):
        word = self.edit_word.text().strip()
        if not word:
            return
        # Evita duplicati
        existing = [self.list_widget.item(i).text()
                    for i in range(self.list_widget.count())]
        if word in existing:
            self.edit_word.clear()
            return
        self.list_widget.addItem(QListWidgetItem(word))
        self.edit_word.clear()
        self._update_count()

    def _remove_selected(self):
        for item in self.list_widget.selectedItems():
            self.list_widget.takeItem(self.list_widget.row(item))
        self._update_count()

    def _clear_all(self):
        reply = QMessageBox.question(
            self, "Svuota dizionario",
            "Rimuovere tutte le parole personalizzate?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.list_widget.clear()
            self._update_count()

    def _import_txt(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Importa parole da TXT", "", "Testo (*.txt)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
            existing = set(self._get_words())
            added = 0
            for line in lines:
                if line not in existing:
                    self.list_widget.addItem(QListWidgetItem(line))
                    existing.add(line)
                    added += 1
            self._update_count()
            QMessageBox.information(
                self, "Importazione", f"Aggiunte {added} parole.")
        except OSError as e:
            QMessageBox.critical(self, "Errore", str(e))

    def _export_txt(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Esporta parole come TXT", "parole_personalizzate.txt",
            "Testo (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(self._get_words()))
            QMessageBox.information(self, "Esportazione", f"Salvato: {path}")
        except OSError as e:
            QMessageBox.critical(self, "Errore", str(e))

    def _save_and_close(self):
        self._settings.custom_words = self._get_words()
        self.accept()
