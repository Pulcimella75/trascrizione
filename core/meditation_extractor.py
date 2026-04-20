import os
import re
import tempfile
import subprocess
from pathlib import Path
from PyQt5.QtCore import QThread, pyqtSignal

from core.logger import get_logger

logger = get_logger("MeditationExtractor")

class MeditationFinderWorker(QThread):
    progress = pyqtSignal(int)
    status_message = pyqtSignal(str)
    finished = pyqtSignal(float, float) # start_sec, end_sec
    error = pyqtSignal(str)

    def __init__(self, url: str, cookies_file: str = None, parent=None):
        super().__init__(parent)
        self.url = url
        self.cookies_file = cookies_file
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        try:
            start_sec, end_sec = self._process()
            if not self._abort:
                self.finished.emit(start_sec, end_sec)
        except Exception as e:
            if not self._abort:
                self.error.emit(str(e))
                logger.error(f"Errore detect meditazione: {e}", exc_info=True)

    def _process(self) -> tuple[float, float]:
        with tempfile.TemporaryDirectory() as tmpdir:
            self.status_message.emit("Scaricamento sottotitoli YouTube...")
            self.progress.emit(10)
            
            if self._abort: return 0.0, 0.0

            # 1. Scarica VTT (auto-sub) per individuare "Alleluia"
            vtt_path = os.path.join(tmpdir, "subs.vtt")
            cmd_subs = [
                "yt-dlp", "--write-auto-sub", "--sub-lang", "it",
                "--skip-download", "-o", os.path.join(tmpdir, "subs.%(ext)s"),
                self.url
            ]
            if self.cookies_file and os.path.exists(self.cookies_file):
                cmd_subs.extend(["--cookies", self.cookies_file])
                
            subprocess.run(cmd_subs, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            
            # Cerca il file it.vtt effettivo
            actual_vtt = None
            for f in os.listdir(tmpdir):
                if f.endswith(".vtt"):
                    actual_vtt = os.path.join(tmpdir, f)
                    break
                    
            if not actual_vtt or not os.path.exists(actual_vtt):
                raise RuntimeError("Sottotitoli non disponibili. Impossibile individuare gli Alleluia.")
                
            self.progress.emit(40)
            self.status_message.emit("Analisi degli Alleluia in corso...")
            
            # 2. Parsing VTT e identificazione cluster
            start_sec = self._find_meditation_start(actual_vtt)
            
            if self._abort: return 0.0, 0.0
            
            # 3. Scarica audio parziale per ffmpeg silencedetect (durata max 30 min)
            self.status_message.emit("Ricerca della lunga pausa (download frammento audio)...")
            self.progress.emit(60)
            
            audio_part = os.path.join(tmpdir, "audio_part.webm")
            cmd_audio = [
                "yt-dlp", "-f", "ba", "--download-sections", f"*{start_sec}-{start_sec+1800}",
                "-o", audio_part, self.url
            ]
            if self.cookies_file and os.path.exists(self.cookies_file):
                cmd_audio.extend(["--cookies", self.cookies_file])
                
            subprocess.run(cmd_audio, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            
            if not os.path.exists(audio_part):
                logger.warning("Impossibile scaricare audio frammento, uso default per fine tempo.")
                return start_sec, start_sec + 480.0  # 8 minuti default
                
            self.progress.emit(80)
            self.status_message.emit("Rilevamento silenzio...")
            
            if self._abort: return 0.0, 0.0
            
            # 4. Trova la pausa con ffmpeg
            end_sec = self._find_meditation_end(audio_part, start_sec)
            
            self.progress.emit(100)
            self.status_message.emit("Meditazione individuata con successo.")
            return start_sec, end_sec

    def _find_meditation_start(self, vtt_path: str) -> float:
        with open(vtt_path, 'r', encoding='utf-8') as f:
            content = f.read()

        time_pat = re.compile(r'(\d+:\d{2}:\d{2}\.\d{3})\s-->\s(\d+:\d{2}:\d{2}\.\d{3})')
        blocks = content.split('\n\n')

        segments = []
        for b in blocks:
            lines = b.split('\n')
            for i, line in enumerate(lines):
                tm = time_pat.search(line)
                if tm:
                    s_str, e_str = tm.groups()
                    h, m, s = s_str.split(':')
                    s_sec = int(h)*3600 + int(m)*60 + float(s)
                    h, m, s = e_str.split(':')
                    e_sec = int(h)*3600 + int(m)*60 + float(s)
                    text = " ".join(lines[i+1:]).replace('<c>', '').replace('</c>', '')
                    text = re.sub(r'<[^>]+>', '', text).strip()
                    segments.append({'start': s_sec, 'end': e_sec, 'text': text})
                    break

        # Raggruppa gli alleluia
        clusters = []
        current_cluster = []
        for s in segments:
            txt = s['text'].lower()
            if 'allelu' in txt or 'alelu' in txt:
                if not current_cluster:
                    current_cluster.append(s)
                else:
                    if s['start'] - current_cluster[-1]['end'] < 45.0:
                        current_cluster.append(s)
                    else:
                        clusters.append(current_cluster)
                        current_cluster = [s]
        if current_cluster:
            clusters.append(current_cluster)

        # Filtra solo i cluster "importanti" (almeno 3 menzioni)
        major_clusters = [c for c in clusters if len(c) >= 3]
        
        if len(major_clusters) >= 2:
            return major_clusters[1][-1]['end']
        elif len(major_clusters) == 1:
            return major_clusters[0][-1]['end']
        elif len(clusters) >= 2:
            return clusters[1][-1]['end']
        elif len(clusters) == 1:
            return clusters[0][-1]['end']
        
        raise RuntimeError("Impossibile trovare nessun Alleluia nei sottotitoli.")

    def _find_meditation_end(self, audio_part: str, global_start_sec: float) -> float:
        # ffmpeg silencedetect. noise=-30dB, duration 5s
        cmd = [
            "ffmpeg", "-i", audio_part,
            "-af", "silencedetect=noise=-30dB:d=5.0",
            "-f", "null", "-"
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore',
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )
        
        output = result.stderr
        
        # Ignoriamo le pause nei primi 240 secondi (4 minuti) 
        # perché l'omelia dura di solito 7/8 minuti.
        min_homily_duration = 240.0 
        
        for line in output.split('\n'):
            if "silence_start:" in line:
                # Esempio: [silencedetect @ 0x...] silence_start: 350
                parts = line.split("silence_start:")
                if len(parts) > 1:
                    try:
                        val = float(parts[1].split()[0])
                        if val > min_homily_duration:
                            # Trovata la prima pausa adatta
                            return global_start_sec + val
                    except ValueError:
                        pass
        
        # Fallback se non trova nessuna pausa lunga (imposta a +8 minuti come default)
        logger.warning("Nessuna pausa lunga trovata, uso fallback 8 minuti.")
        return global_start_sec + 480.0
