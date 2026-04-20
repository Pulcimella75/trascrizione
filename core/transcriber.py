"""
core/transcriber.py
Worker QThread per la trascrizione con faster-whisper.
Supporta: file audio, file video (estrazione audio via FFmpeg),
range temporale (start_sec / end_sec), dizionario parole personalizzate.
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QThread, pyqtSignal

from core.logger import get_logger

logger = get_logger("Transcriber")


SUPPORTED_AUDIO = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".wma"}
SUPPORTED_VIDEO = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".ts"}

LANGUAGE_CODES = {
    "auto": None,
    "Italiano": "it",
    "English": "en",
    "Français": "fr",
    "Português": "pt",
    "Español": "es",
}


class TranscriptionSegment:
    """Rappresenta un segmento di testo trascritto."""

    def __init__(self, text: str, start: float, end: float):
        self.text = text.strip()
        self.start = start
        self.end = end

    def __repr__(self):
        return f"[{self.start:.1f}s→{self.end:.1f}s] {self.text}"


class TranscriberWorker(QThread):
    """
    Worker thread per la trascrizione.

    Segnali:
        progress(int)                  0–100
        status_message(str)            messaggio descrittivo corrente
        segment_ready(str)             testo di un segmento appena trascritto
        finished(list[TranscriptionSegment], str)  segmenti + percorso file sorgente
        error(str)                     messaggio di errore
    """

    progress = pyqtSignal(int)
    status_message = pyqtSignal(str)
    segment_ready = pyqtSignal(str)
    finished = pyqtSignal(list, str)
    error = pyqtSignal(str)

    def __init__(
        self,
        file_path: str,
        model_dir: str,
        model_name: str = "large-v2",
        language: str = "auto",
        custom_words: Optional[list] = None,
        start_sec: float = 0.0,
        end_sec: float = 0.0,
        parent=None,
    ):
        super().__init__(parent)
        self.file_path = file_path
        self.model_dir = model_dir
        self.model_name = model_name
        self.language = language
        self.custom_words = custom_words or []
        self.start_sec = start_sec
        self.end_sec = end_sec  # 0 = fino alla fine
        self._abort = False
        self.result_segments = []

    def abort(self):
        self._abort = True

    def run(self):
        try:
            self._transcribe()
        except Exception as e:
            self.error.emit(str(e))

    def _transcribe(self):
        file_path = Path(self.file_path)
        suffix = file_path.suffix.lower()
        temp_audio = None
        outputs_to_clean = []

        if self._abort:
            return

        # ── 1. Estrazione audio (FFmpeg funziona benissimo nel QThread) ──
        need_extraction = (suffix in SUPPORTED_VIDEO or self.start_sec > 0 or self.end_sec > 0)
        
        if need_extraction:
            logger.info(f"Avvio estrazione audio per {file_path.name}")
            self.status_message.emit("Estrazione audio dal file...")
            self.progress.emit(5)
            temp_audio = self._extract_audio(str(file_path))
            audio_path = temp_audio
            outputs_to_clean.append(temp_audio)
        else:
            audio_path = str(file_path)

        if self._abort:
            self._cleanup_files(outputs_to_clean)
            return

        # ── 2. Lancio Sottoprocesso Isolato per l'AI ───────────────────────
        import json
        import subprocess
        import sys
        
        # Generiamo due file temporanei: uno per il config e uno per il risultato
        fd_cfg, cfg_file = tempfile.mkstemp(suffix=".json")
        os.close(fd_cfg)
        fd_res, res_file = tempfile.mkstemp(suffix=".json")
        os.close(fd_res)
        
        outputs_to_clean.extend([cfg_file, res_file])
        
        config = {
            "audio_path": audio_path,
            "model_dir": self.model_dir,
            "model_name": self.model_name,
            "language": self.language,
            "custom_words": self.custom_words,
            "output_file": res_file
        }
        
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump(config, f)
            
        script_path = str(Path(__file__).parent / "transcribe_subprocess.py")
        
        # Eseguiamo tramite subprocess catturando lo standard output JSON
        logger.info(f"Lancio sottoprocesso isolato per il modello da: {script_path}")
        
        process = subprocess.Popen(
            [sys.executable, script_path, cfg_file],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )
        
        segments = []
        # Leggiamo in loop gli aggiornamenti dal processo separato
        for line in iter(process.stdout.readline, ''):
            if self._abort:
                process.terminate()
                self._cleanup_files(outputs_to_clean)
                return
                
            line = line.strip()
            if not line: continue
            
            try:
                msg = json.loads(line)
                mtype = msg.get("type")
                
                if mtype == "status":
                    self.status_message.emit(msg["msg"])
                elif mtype == "progress":
                    self.progress.emit(msg["val"])
                elif mtype == "segment":
                    ts = TranscriptionSegment(msg["text"], msg["start"], msg["end"])
                    self.segment_ready.emit(ts.text)
                    self.progress.emit(msg["pct"])
                elif mtype == "error":
                    self.error.emit(f"Errore processo AI: {msg['msg']}")
                    self._cleanup_files(outputs_to_clean)
                    return
                elif mtype == "done":
                    break
            except json.JSONDecodeError:
                # Se il sottoprocesso stampa roba nativa (es. warning librerie C), loggala
                logger.debug(f"[SubProcess]: {line}")
                
        process.stdout.close()
        ret_code = process.wait()
        
        if ret_code != 0:
            logger.error("Il sottoprocesso è andato in crash anomalo.")
            self.error.emit(f"Arresto anomalo del motore di trascrizione.\nAssicurati che la memoria sia sufficiente.")
            self._cleanup_files(outputs_to_clean)
            return

        # Recuperiamo il file JSON finale con tutti i timestamp
        if os.path.exists(res_file) and os.path.getsize(res_file) > 0:
            try:
                with open(res_file, "r", encoding="utf-8") as f:
                    final_data = json.load(f)
                    segments = [TranscriptionSegment(d["text"], d["start"], d["end"]) for d in final_data]
            except Exception as e:
                logger.error(f"Impossibile leggere il file dei risultati: {e}")
                
        self._cleanup_files(outputs_to_clean)

        if not self._abort:
            self.progress.emit(100)
            self.status_message.emit("Trascrizione completata.")
            self.result_segments = segments
            self.finished.emit(segments, self.file_path)
            return segments
        return []

    def _cleanup_files(self, paths: list):
        for path in paths:
            if path and os.path.exists(path):
                try: os.unlink(path)
                except OSError: pass

    def _extract_audio(self, input_path: str) -> str:
        """Estrae l'audio in WAV temporaneo usando FFmpeg."""
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        output_path = tmp.name

        cmd = ["ffmpeg", "-y", "-i", input_path]

        if self.start_sec > 0:
            cmd += ["-ss", str(self.start_sec)]
        if self.end_sec > 0:
            duration_sec = self.end_sec - self.start_sec
            if duration_sec > 0:
                cmd += ["-t", str(duration_sec)]

        cmd += [
            "-vn",           # nessun video
            "-acodec", "pcm_s16le",
            "-ar", "16000",  # 16kHz ottimale per Whisper
            "-ac", "1",      # mono
            output_path,
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg error:\n{result.stderr}")

        return output_path

    @staticmethod
    def _cleanup(temp_path: Optional[str]):
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass
