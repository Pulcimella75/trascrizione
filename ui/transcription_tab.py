"""
ui/transcription_tab.py
Tab principale: drop zone, URL YouTube, selezione modello/lingua,
range temporale, avvio trascrizione, barra di avanzamento.
"""

import os
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QDragEnterEvent, QDropEvent
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QLineEdit, QGroupBox, QProgressBar, QSizePolicy,
    QMessageBox, QSpinBox, QFormLayout, QFileDialog,
)

from config.settings import AppSettings
from core.transcriber import (
    TranscriberWorker, LANGUAGE_CODES, SUPPORTED_AUDIO, SUPPORTED_VIDEO,
)
from core.downloader import YouTubeDownloaderWorker
from core.meditation_extractor import MeditationFinderWorker
from core.model_manager import get_local_models
from ui.queue_panel import QueuePanel, QueueItem, FileStatus
from ui.video_navigator import VideoNavigatorDialog


def _sec_to_mmss(sec: float) -> tuple[int, int]:
    s = int(sec)
    return s // 60, s % 60


def _mmss_to_sec(minutes: int, seconds: int) -> float:
    return float(minutes * 60 + seconds)


class TimeRangeWidget(QWidget):
    """Widget coppia mm:ss per start e end time."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(QLabel("Da:"))
        self.spin_start_m = self._spin()
        self.spin_start_s = self._spin(59)
        layout.addWidget(self.spin_start_m)
        layout.addWidget(QLabel("m"))
        layout.addWidget(self.spin_start_s)
        layout.addWidget(QLabel("s"))

        layout.addSpacing(14)
        layout.addWidget(QLabel("A:"))
        self.spin_end_m = self._spin()
        self.spin_end_s = self._spin(59)
        layout.addWidget(self.spin_end_m)
        layout.addWidget(QLabel("m"))
        layout.addWidget(self.spin_end_s)
        layout.addWidget(QLabel("s"))
        layout.addWidget(QLabel("(0:00 = fine file)"))

        layout.addStretch()

    @staticmethod
    def _spin(max_val: int = 999) -> QSpinBox:
        sp = QSpinBox()
        sp.setRange(0, max_val)
        sp.setFixedWidth(56)
        return sp

    def get_start_sec(self) -> float:
        return _mmss_to_sec(self.spin_start_m.value(), self.spin_start_s.value())

    def get_end_sec(self) -> float:
        return _mmss_to_sec(self.spin_end_m.value(), self.spin_end_s.value())

    def set_range(self, start_sec: float, end_sec: float):
        m, s = _sec_to_mmss(start_sec)
        self.spin_start_m.setValue(m)
        self.spin_start_s.setValue(s)
        m, s = _sec_to_mmss(end_sec)
        self.spin_end_m.setValue(m)
        self.spin_end_s.setValue(s)


class DropZone(QLabel):
    """Area drag & drop per file audio/video."""

    files_dropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("drop_zone")
        self.setAlignment(Qt.AlignCenter)
        self.setText(
            "🎵  Trascina qui file audio o video\n\n"
            "MP3 · WAV · M4A · AAC · OGG · FLAC\n"
            "MP4 · MKV · AVI · MOV · WEBM"
        )
        self.setAcceptDrops(True)
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setObjectName("drop_zone_active")
            self._refresh_style()

    def dragLeaveEvent(self, event):
        self.setObjectName("drop_zone")
        self._refresh_style()

    def dropEvent(self, event: QDropEvent):
        self.setObjectName("drop_zone")
        self._refresh_style()
        paths = []
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p:
                paths.append(p)
        if paths:
            self.files_dropped.emit(paths)

    def _refresh_style(self):
        self.style().unpolish(self)
        self.style().polish(self)


class TranscriptionTab(QWidget):
    """
    Tab principale di trascrizione.

    Segnali:
        transcription_ready(str, str)   (file_path, testo completo)
        status_update(str)              messaggio per la status bar
    """

    transcription_ready = pyqtSignal(str, str)
    status_update = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = AppSettings()
        self._worker: TranscriberWorker | None = None
        self._yt_worker: YouTubeDownloaderWorker | None = None
        self._meditation_finder = None
        self._current_segments: list = []
        self._is_running = False
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)

        # ─ Drop zone ─────────────────────────────────────────────────────
        self.drop_zone = DropZone()
        self.drop_zone.files_dropped.connect(self._on_files_dropped)
        layout.addWidget(self.drop_zone)

        # ─ YouTube URL ───────────────────────────────────────────────────
        yt_box = QGroupBox("🎬  YouTube")
        yt_outer = QVBoxLayout(yt_box)
        yt_outer.setSpacing(6)

        yt_url_row = QHBoxLayout()
        self.edit_yt_url = QLineEdit()
        self.edit_yt_url.setPlaceholderText("Incolla URL YouTube (es. https://www.youtube.com/watch?v=...)")
        self.btn_add_yt = QPushButton("➕  Aggiungi")
        self.btn_add_yt.clicked.connect(self._on_add_youtube)
        self.btn_detect_med= QPushButton("🔍 Rileva Omelia")
        self.btn_detect_med.setToolTip("Cerca la meditazione (dopo l'Alleluia e termina con pausa) e l'aggiunge alla coda")
        self.btn_detect_med.clicked.connect(self._on_detect_meditation)
        yt_url_row.addWidget(self.edit_yt_url)
        yt_url_row.addWidget(self.btn_add_yt)
        yt_url_row.addWidget(self.btn_detect_med)
        yt_outer.addLayout(yt_url_row)

        # Riga cookies
        yt_cookies_row = QHBoxLayout()
        lbl_cookies = QLabel("🍪  Cookies YouTube:")
        lbl_cookies.setStyleSheet("color: #6b738f; font-size: 12px;")
        self.edit_cookies_path = QLineEdit()
        self.edit_cookies_path.setPlaceholderText(
            "File cookies.txt (opzionale — usato se il download fallisce)")
        self.edit_cookies_path.setReadOnly(True)
        self.edit_cookies_path.setText(self._settings.cookies_file)
        self.btn_cookies_browse = QPushButton("📂")
        self.btn_cookies_browse.setObjectName("btn_flat")
        self.btn_cookies_browse.setFixedWidth(36)
        self.btn_cookies_browse.setToolTip("Seleziona file cookies.txt esportato dal browser")
        self.btn_cookies_browse.clicked.connect(self._browse_cookies)
        self.btn_cookies_clear = QPushButton("✕")
        self.btn_cookies_clear.setObjectName("btn_flat")
        self.btn_cookies_clear.setFixedWidth(28)
        self.btn_cookies_clear.setToolTip("Rimuovi file cookies")
        self.btn_cookies_clear.clicked.connect(self._clear_cookies)
        yt_cookies_row.addWidget(lbl_cookies)
        yt_cookies_row.addWidget(self.edit_cookies_path)
        yt_cookies_row.addWidget(self.btn_cookies_browse)
        yt_cookies_row.addWidget(self.btn_cookies_clear)
        yt_outer.addLayout(yt_cookies_row)

        layout.addWidget(yt_box)

        # ─ Opzioni ───────────────────────────────────────────────────────
        opt_box = QGroupBox("⚙️  Opzioni trascrizione")
        opt_layout = QFormLayout(opt_box)
        opt_layout.setSpacing(10)

        # Modello
        self.combo_model = QComboBox()
        self._populate_models()
        opt_layout.addRow("Modello:", self.combo_model)

        # Lingua
        self.combo_lang = QComboBox()
        for lang in LANGUAGE_CODES.keys():
            self.combo_lang.addItem(lang)
        lang_idx = self.combo_lang.findText(self._settings.default_language)
        if lang_idx >= 0:
            self.combo_lang.setCurrentIndex(lang_idx)
        opt_layout.addRow("Lingua:", self.combo_lang)

        # Range temporale
        self.time_range = TimeRangeWidget()
        self.btn_open_navigator = QPushButton("🎬  Naviga video...")
        self.btn_open_navigator.setObjectName("btn_flat")
        self.btn_open_navigator.setToolTip(
            "Apri il player video per selezionare visivamente l'intervallo")
        self.btn_open_navigator.clicked.connect(self._open_video_navigator)

        range_row = QHBoxLayout()
        range_row.addWidget(self.time_range)
        range_row.addWidget(self.btn_open_navigator)
        opt_layout.addRow("Intervallo:", range_row)

        layout.addWidget(opt_box)

        # ─ Coda ──────────────────────────────────────────────────────────
        self.queue_panel = QueuePanel()
        layout.addWidget(self.queue_panel, stretch=1)

        # ─ Avanzamento + controlli ────────────────────────────────────────
        progress_box = QGroupBox()
        progress_box.setFlat(True)
        prog_layout = QVBoxLayout(progress_box)
        prog_layout.setContentsMargins(0, 4, 0, 0)

        self.lbl_status = QLabel("Pronto.")
        self.lbl_status.setStyleSheet("color: #2a5cbf; font-size: 12px;")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        bottom_row = QHBoxLayout()
        self.btn_start = QPushButton("▶  Avvia Trascrizione")
        self.btn_start.setObjectName("btn_success")
        self.btn_start.setMinimumHeight(40)
        self.btn_start.clicked.connect(self._start_queue)

        self.btn_stop = QPushButton("⏹  Interrompi")
        self.btn_stop.setObjectName("btn_danger")
        self.btn_stop.setMinimumHeight(40)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_transcription)

        bottom_row.addWidget(self.btn_start)
        bottom_row.addWidget(self.btn_stop)

        prog_layout.addWidget(self.lbl_status)
        prog_layout.addWidget(self.progress_bar)
        prog_layout.addLayout(bottom_row)
        layout.addWidget(progress_box)

    # ── Modelli ───────────────────────────────────────────────────────────

    def _populate_models(self):
        self.combo_model.clear()
        local = get_local_models(self._settings.model_dir)
        if local:
            self.combo_model.addItems(local)
            default = self._settings.default_model
            idx = self.combo_model.findText(default)
            if idx >= 0:
                self.combo_model.setCurrentIndex(idx)
        else:
            self.combo_model.addItem("(nessun modello — scarica dal menu Modelli)")

    def refresh_models(self):
        """Ricarica la lista modelli (dopo download/eliminazione)."""
        self._populate_models()

    # ── Drop / YouTube ────────────────────────────────────────────────────

    def _on_files_dropped(self, paths: list[str]):
        for path in paths:
            ext = Path(path).suffix.lower()
            if ext not in SUPPORTED_AUDIO and ext not in SUPPORTED_VIDEO:
                QMessageBox.warning(
                    self, "Formato non supportato",
                    f"Il file '{Path(path).name}' non è un file audio/video supportato.")
                continue
            self._add_to_queue(path)

    def _on_add_youtube(self):
        url = self.edit_yt_url.text().strip()
        if not url.startswith("http"):
            QMessageBox.warning(self, "URL non valido",
                                "Inserisci un URL YouTube valido.")
            return
        # Il download avviene prima della trascrizione
        self._add_to_queue(url, is_youtube=True)
        self.edit_yt_url.clear()

    def _on_detect_meditation(self):
        url = self.edit_yt_url.text().strip()
        if not url.startswith("http"):
            QMessageBox.warning(self, "URL non valido", "Inserisci un URL YouTube valido.")
            return
            
        cookies = self._settings.cookies_file
        self._set_ui_running(True)
        self.btn_stop.setEnabled(True)
        
        self._meditation_finder = MeditationFinderWorker(url, cookies, self)
        self._meditation_finder.progress.connect(self.progress_bar.setValue)
        self._meditation_finder.status_message.connect(self._update_status)
        self._meditation_finder.finished.connect(lambda s, e: self._on_meditation_found(url, s, e))
        self._meditation_finder.error.connect(self._on_meditation_error)
        self._meditation_finder.start()

    def _on_meditation_found(self, url: str, start_sec: float, end_sec: float):
        self._set_ui_running(False)
        self._update_status("💡 Omelia trovata, aggiunta in coda.")
        self.time_range.set_range(start_sec, end_sec)
        self._add_to_queue(url, is_youtube=True)
        self.edit_yt_url.clear()
        
    def _on_meditation_error(self, err: str):
        self._set_ui_running(False)
        self._update_status("Errore rilevamento.")
        QMessageBox.warning(self, "Errore Rilevamento Omelia", f"Errore durante l'analisi:\n{err}")

    def _add_to_queue(self, path: str, is_youtube: bool = False):
        model = self.combo_model.currentText()
        lang  = self.combo_lang.currentText()
        start = self.time_range.get_start_sec()
        end   = self.time_range.get_end_sec()

        item = QueueItem(
            file_path=path,
            model=model,
            language=lang,
            start_sec=start,
            end_sec=end,
        )
        self.queue_panel.add_item(item)

    # ── Navigator video ───────────────────────────────────────────────────

    def _open_video_navigator(self):
        """Apre il player video per selezionare l'intervallo."""
        # Usa il primo file video della coda, o chiedi all'utente
        from PyQt5.QtWidgets import QFileDialog
        pending = self.queue_panel.get_pending()
        video_path = None

        for item in pending:
            ext = Path(item.file_path).suffix.lower()
            if ext in SUPPORTED_VIDEO:
                video_path = item.file_path
                break

        if not video_path:
            video_path, _ = QFileDialog.getOpenFileName(
                self, "Seleziona file video",
                self._settings.get("last_output_dir", ""),
                "Video (*.mp4 *.mkv *.avi *.mov *.webm *.ts *.wmv)",
            )
        if not video_path:
            return

        start = self.time_range.get_start_sec()
        end   = self.time_range.get_end_sec()

        dlg = VideoNavigatorDialog(video_path, start, end, self)
        if dlg.exec_() == VideoNavigatorDialog.Accepted:
            s, e = dlg.get_range()
            self.time_range.set_range(s, e)

    # ── Trascrizione ──────────────────────────────────────────────────────

    def _start_queue(self):
        pending = self.queue_panel.get_pending()
        if not pending:
            QMessageBox.information(self, "Coda vuota",
                                    "Aggiungi file alla coda prima di avviare.")
            return

        local_models = get_local_models(self._settings.model_dir)
        if not local_models:
            QMessageBox.warning(
                self, "Nessun modello",
                "Nessun modello faster-whisper trovato.\n"
                "Scarica un modello dal menu Modelli → Gestione Modelli.")
            return

        self._is_running = True
        self._set_ui_running(True)
        self._process_next()

    def _process_next(self):
        if not self._is_running:
            return

        pending = self.queue_panel.get_pending()
        if not pending:
            self._on_all_done()
            return

        item = pending[0]
        self.queue_panel.update_status(item.file_path, FileStatus.RUNNING)

        # YouTube: prima scarica, poi trascrive
        if item.file_path.startswith("http"):
            self._download_youtube(item)
        else:
            self._start_transcription(item)

    def _download_youtube(self, item: QueueItem):
        cookies = self._settings.cookies_file
        self._yt_worker = YouTubeDownloaderWorker(
            item.file_path, self._settings.temp_dir,
            cookies_file=cookies, parent=self)
        self._yt_worker.progress.connect(self.progress_bar.setValue)
        self._yt_worker.status.connect(self._update_status)
        self._yt_worker.finished.connect(
            lambda url, local_path, it=item: self._on_yt_downloaded(it, local_path))
        self._yt_worker.error.connect(
            lambda e, it=item: self._on_item_error(it, e))
        self._yt_worker.start()

    def _on_yt_downloaded(self, item: QueueItem, local_path: str):
        item.file_path = local_path
        self._start_transcription(item)

    def _start_transcription(self, item: QueueItem):
        self._current_segments = []
        self._worker = TranscriberWorker(
            file_path=item.file_path,
            model_dir=self._settings.model_dir,
            model_name=item.model,
            language=item.language,
            custom_words=self._settings.custom_words,
            start_sec=item.start_sec,
            end_sec=item.end_sec,
            parent=self,
        )
        self._worker.progress.connect(self.progress_bar.setValue)
        self._worker.status_message.connect(self._update_status)
        self._worker.segment_ready.connect(self._on_segment_ready)
        self._worker.finished.connect(
            lambda segs, path, it=item: self._on_item_done(it, segs, path))
        self._worker.error.connect(
            lambda e, it=item: self._on_item_error(it, e))
        self._worker.start()

    def _on_segment_ready(self, text: str):
        self._current_segments.append(text)

    def _on_item_done(self, item: QueueItem, segments, path: str):
        self.queue_panel.update_status(item.file_path, FileStatus.DONE)
        full_text = " ".join(s.text for s in segments)
        self.transcription_ready.emit(path, full_text)
        self.status_update.emit(f"Completato: {Path(path).name}")
        # Prosegui con il prossimo
        QTimer.singleShot(200, self._process_next)

    def _on_item_error(self, item: QueueItem, error: str):
        self.queue_panel.update_status(item.file_path, FileStatus.ERROR, error)
        QMessageBox.warning(
            self, "Errore trascrizione",
            f"Errore su '{Path(item.file_path).name}':\n{error}",
        )
        QTimer.singleShot(200, self._process_next)

    def _on_all_done(self):
        self._is_running = False
        self._set_ui_running(False)
        self.progress_bar.setValue(100)
        self._update_status("✅ Tutti i file elaborati.")
        self.status_update.emit("Trascrizione completata.")

    def _stop_transcription(self):
        self._is_running = False
        if self._worker and self._worker.isRunning():
            self._worker.abort()
        if self._yt_worker and self._yt_worker.isRunning():
            self._yt_worker.terminate()
        if self._meditation_finder and self._meditation_finder.isRunning():
            self._meditation_finder.abort()
        self._set_ui_running(False)
        self._update_status("Trascrizione interrotta.")

    def _set_ui_running(self, running: bool):
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.btn_add_yt.setEnabled(not running)
        self.btn_detect_med.setEnabled(not running)

    def _update_status(self, msg: str):
        self.lbl_status.setText(msg)
        self.status_update.emit(msg)

    # ── Cookies ───────────────────────────────────────────────────────────

    def _browse_cookies(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleziona file cookies.txt",
            self._settings.cookies_file or "",
            "Cookies file (*.txt);;Tutti i file (*)",
        )
        if path:
            self._settings.cookies_file = path
            self.edit_cookies_path.setText(path)

    def _clear_cookies(self):
        self._settings.cookies_file = ""
        self.edit_cookies_path.clear()
