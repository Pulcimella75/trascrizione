"""
ui/video_navigator.py
Dialog player video per scegliere il punto di inizio e fine trascrizione.
Usa QMediaPlayer + QVideoWidget (Windows Media Foundation, nativo Win11).
"""

from PyQt5.QtCore import Qt, QUrl, QTimer
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QSlider, QGroupBox, QDialogButtonBox, QSizePolicy,
)


def _sec_to_mmss(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"


class VideoNavigatorDialog(QDialog):
    """
    Riproduttore video integrato per selezionare start/end time.
    Restituisce (start_sec: float, end_sec: float) tramite .get_range().
    """

    def __init__(self, file_path: str, initial_start: float = 0.0,
                 initial_end: float = 0.0, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.start_sec: float = initial_start
        self.end_sec: float = initial_end
        self._duration_ms: int = 0
        self._user_seeking = False

        self.setWindowTitle("Navigatore Video — Seleziona Intervallo")
        self.setMinimumSize(850, 600)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        self._build_ui()
        self._connect_signals()
        self._load_file()

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        # Video
        self.video_widget = QVideoWidget()
        self.video_widget.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_widget.setMinimumHeight(360)
        layout.addWidget(self.video_widget)

        # Slider posizione
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.setTracking(True)
        layout.addWidget(self.slider)

        # Etichette tempo
        time_row = QHBoxLayout()
        self.lbl_current = QLabel("00:00")
        self.lbl_current.setStyleSheet("color: #7eb8f7; font-size: 14px; font-weight: 700;")
        self.lbl_duration = QLabel("/ 00:00")
        self.lbl_duration.setStyleSheet("color: #5a6080; font-size: 13px;")
        time_row.addWidget(self.lbl_current)
        time_row.addWidget(self.lbl_duration)
        time_row.addStretch()
        layout.addLayout(time_row)

        # Controlli playback
        ctrl_row = QHBoxLayout()
        self.btn_play = QPushButton("▶  Play")
        self.btn_play.setMinimumWidth(100)
        self.btn_rewind = QPushButton("⏮  -10s")
        self.btn_forward = QPushButton("+10s  ⏭")
        ctrl_row.addWidget(self.btn_rewind)
        ctrl_row.addWidget(self.btn_play)
        ctrl_row.addWidget(self.btn_forward)
        ctrl_row.addStretch()
        layout.addLayout(ctrl_row)

        # Selezione intervallo
        interval_box = QGroupBox("Intervallo di Trascrizione")
        interval_layout = QHBoxLayout(interval_box)

        # Start
        self.btn_set_start = QPushButton("⏱  Segna INIZIO qui")
        self.btn_set_start.setObjectName("btn_success")
        self.lbl_start = QLabel(f"Inizio: {_sec_to_mmss(self.start_sec)}")
        self.lbl_start.setStyleSheet("color: #4aaa6a; font-weight: 700; font-size: 14px;")

        # End
        self.btn_set_end = QPushButton("⏹  Segna FINE qui")
        self.btn_set_end.setObjectName("btn_danger")
        self.lbl_end = QLabel(
            f"Fine: {_sec_to_mmss(self.end_sec) if self.end_sec > 0 else 'fine file'}")
        self.lbl_end.setStyleSheet("color: #cc5555; font-weight: 700; font-size: 14px;")

        # Reset
        self.btn_reset = QPushButton("↺  Reset")
        self.btn_reset.setObjectName("btn_flat")

        interval_layout.addWidget(self.btn_set_start)
        interval_layout.addWidget(self.lbl_start)
        interval_layout.addSpacing(20)
        interval_layout.addWidget(self.btn_set_end)
        interval_layout.addWidget(self.lbl_end)
        interval_layout.addSpacing(20)
        interval_layout.addWidget(self.btn_reset)
        interval_layout.addStretch()
        layout.addWidget(interval_box)

        # Bottoni OK/Annulla
        btns = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            Qt.Horizontal, self
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _connect_signals(self):
        self.player = QMediaPlayer(self)
        self.player.setVideoOutput(self.video_widget)

        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.stateChanged.connect(self._on_state_changed)

        self.slider.sliderPressed.connect(lambda: setattr(self, "_user_seeking", True))
        self.slider.sliderReleased.connect(self._on_slider_released)
        self.slider.sliderMoved.connect(self._on_slider_moved)

        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_rewind.clicked.connect(lambda: self._seek_relative(-10))
        self.btn_forward.clicked.connect(lambda: self._seek_relative(10))
        self.btn_set_start.clicked.connect(self._mark_start)
        self.btn_set_end.clicked.connect(self._mark_end)
        self.btn_reset.clicked.connect(self._reset_range)

    def _load_file(self):
        url = QUrl.fromLocalFile(self.file_path)
        self.player.setMedia(QMediaContent(url))
        # Vai al punto iniziale se impostato
        if self.start_sec > 0:
            QTimer.singleShot(500, lambda: self.player.setPosition(int(self.start_sec * 1000)))

    # ── Slot player ───────────────────────────────────────────────────────

    def _on_duration_changed(self, duration_ms: int):
        self._duration_ms = duration_ms
        self.slider.setRange(0, duration_ms)
        self.lbl_duration.setText(f"/ {_sec_to_mmss(duration_ms / 1000)}")

    def _on_position_changed(self, pos_ms: int):
        if not self._user_seeking:
            self.slider.setValue(pos_ms)
        self.lbl_current.setText(_sec_to_mmss(pos_ms / 1000))

    def _on_state_changed(self, state):
        if state == QMediaPlayer.PlayingState:
            self.btn_play.setText("⏸  Pausa")
        else:
            self.btn_play.setText("▶  Play")

    def _on_slider_released(self):
        pos = self.slider.value()
        self.player.setPosition(pos)
        self._user_seeking = False

    def _on_slider_moved(self, pos: int):
        self.lbl_current.setText(_sec_to_mmss(pos / 1000))

    # ── Controlli ─────────────────────────────────────────────────────────

    def _toggle_play(self):
        if self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _seek_relative(self, delta_sec: int):
        pos = self.player.position() + delta_sec * 1000
        pos = max(0, min(pos, self._duration_ms))
        self.player.setPosition(pos)

    def _mark_start(self):
        self.start_sec = self.player.position() / 1000
        self.lbl_start.setText(f"Inizio: {_sec_to_mmss(self.start_sec)}")

    def _mark_end(self):
        self.end_sec = self.player.position() / 1000
        self.lbl_end.setText(f"Fine: {_sec_to_mmss(self.end_sec)}")

    def _reset_range(self):
        self.start_sec = 0.0
        self.end_sec = 0.0
        self.lbl_start.setText("Inizio: 00:00")
        self.lbl_end.setText("Fine: fine file")

    # ── Output ────────────────────────────────────────────────────────────

    def get_range(self) -> tuple[float, float]:
        return self.start_sec, self.end_sec

    def closeEvent(self, event):
        self.player.stop()
        super().closeEvent(event)
