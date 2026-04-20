"""
ui/main_window.py
Finestra principale dell'applicazione di trascrizione.
"""

import os
from pathlib import Path

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout,
    QStatusBar, QAction, QMenuBar, QLabel, QSplitter,
    QMessageBox,
)

from config.settings import AppSettings
from ui.transcription_tab import TranscriptionTab
from ui.editor_panel import EditorPanel
from ui.model_manager_dialog import ModelManagerDialog
from ui.custom_words_dialog import CustomWordsDialog
from ui.settings_dialog import SettingsDialog
from ui.prayers_tab import PrayersTab


class MainWindow(QMainWindow):
    """Finestra principale con tab Trascrizione / Editor."""

    def __init__(self):
        super().__init__()
        self._settings = AppSettings()
        self._settings.ensure_dirs()

        self.setWindowTitle("Trascrizione Audio & Video")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 800)
        self._restore_geometry()

        self._build_menu()
        self._build_central()
        self._build_statusbar()
        self._connect_signals()

    # ── Menu ──────────────────────────────────────────────────────────────

    def _build_menu(self):
        menubar = self.menuBar()

        # File
        menu_file = menubar.addMenu("File")
        act_settings = QAction("⚙️  Impostazioni...", self)
        act_settings.triggered.connect(self._open_settings)
        act_quit = QAction("✕  Esci", self)
        act_quit.triggered.connect(self.close)
        menu_file.addAction(act_settings)
        menu_file.addSeparator()
        menu_file.addAction(act_quit)

        # Modelli
        menu_models = menubar.addMenu("Modelli")
        act_manage = QAction("📦  Gestione Modelli...", self)
        act_manage.triggered.connect(self._open_model_manager)
        menu_models.addAction(act_manage)

        # Dizionario
        menu_dict = menubar.addMenu("Dizionario")
        act_words = QAction("📝  Parole Personalizzate...", self)
        act_words.triggered.connect(self._open_custom_words)
        menu_dict.addAction(act_words)

        # Info
        menu_help = menubar.addMenu("?")
        act_about = QAction("ℹ️  Informazioni", self)
        act_about.triggered.connect(self._show_about)
        menu_help.addAction(act_about)

    # ── Layout centrale ───────────────────────────────────────────────────

    def _build_central(self):
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.North)

        # Tab 1: Trascrizione
        self.transcription_tab = TranscriptionTab()
        self.tabs.addTab(self.transcription_tab, "🎙  Trascrizione")

        # Tab 2: Editor
        self.editor_panel = EditorPanel()
        self.tabs.addTab(self.editor_panel, "✏️  Editor Testo")

        # Tab 3: Archivio Preghiere
        self.prayers_tab = PrayersTab()
        self.tabs.addTab(self.prayers_tab, "📚  Archivio Preghiere")

        self.setCentralWidget(self.tabs)

    # ── Status bar ────────────────────────────────────────────────────────

    def _build_statusbar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.lbl_model_info = QLabel()
        self._update_model_label()
        self.status_bar.addPermanentWidget(self.lbl_model_info)

        self.lbl_output_info = QLabel()
        self._update_output_label()
        self.status_bar.addPermanentWidget(self.lbl_output_info)

    def _update_model_label(self):
        self.lbl_model_info.setText(
            f"  Modello: {self._settings.default_model}  ")

    def _update_output_label(self):
        self.lbl_output_info.setText(
            f"  Output: {self._settings.output_dir}  ")

    # ── Segnali ───────────────────────────────────────────────────────────

    def _connect_signals(self):
        self.transcription_tab.transcription_ready.connect(
            self._on_transcription_ready)
        self.transcription_tab.status_update.connect(
            self.status_bar.showMessage)

    def _on_transcription_ready(self, file_path: str, text: str):
        """Quando una trascrizione è pronta, caricala nell'editor e cambia tab."""
        self.editor_panel.set_source(file_path)
        if self.editor_panel.editor.toPlainText().strip():
            # Se c'è già del testo, aggiungi separatore
            self.editor_panel.editor.append("\n\n─────────────────────────\n")
            self.editor_panel.editor.append(text)
        else:
            self.editor_panel.set_text(text)
        self.tabs.setCurrentIndex(1)  # passa all'editor

    # ── Dialog ────────────────────────────────────────────────────────────

    def _open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec_():
            self._update_model_label()
            self._update_output_label()
            self.transcription_tab.refresh_models()

    def _open_model_manager(self):
        dlg = ModelManagerDialog(self)
        dlg.model_default_changed.connect(self._on_model_default_changed)
        dlg.exec_()
        self.transcription_tab.refresh_models()

    def _open_custom_words(self):
        dlg = CustomWordsDialog(self)
        dlg.exec_()

    def _on_model_default_changed(self, name: str):
        self._update_model_label()

    def _show_about(self):
        QMessageBox.about(
            self,
            "Trascrizione Audio & Video",
            "<b>App Trascrizione</b><br>"
            "Versione 1.0<br><br>"
            "Motore: <b>faster-whisper</b><br>"
            "Download YouTube: <b>yt-dlp</b><br>"
            "Lingue: IT · EN · FR · PT · ES<br><br>"
            "Sviluppato con PyQt5 + faster-whisper.",
        )

    # ── Geometria finestra ────────────────────────────────────────────────

    def _restore_geometry(self):
        geo = self._settings.get("window_geometry")
        if geo:
            try:
                from PyQt5.QtCore import QByteArray
                self.restoreGeometry(QByteArray.fromHex(geo.encode()))
            except Exception:
                pass

    def closeEvent(self, event):
        self._settings.set(
            "window_geometry",
            bytes(self.saveGeometry().toHex()).decode()
        )
        super().closeEvent(event)
