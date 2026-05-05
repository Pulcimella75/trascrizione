"""
core/downloader.py
Versione Ultra-Resiliente per YouTube (2026)
Include fix per: 403 Forbidden, nsig extraction failed, empty files, e format discovery.
"""

import os
import re
import shutil
import time
import glob
import wave
from pathlib import Path
from PyQt5.QtCore import QThread, pyqtSignal
from core.logger import get_logger

logger = get_logger("Downloader")

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?Settings:"<>|]', "_", name)

def strip_ansi(text: str) -> str:
    return re.sub(r'\x1b\[[0-9;]*[mGKHF]', '', text)

class YouTubeDownloaderWorker(QThread):
    progress = pyqtSignal(int)
    status   = pyqtSignal(str)
    finished = pyqtSignal(str, str)
    error    = pyqtSignal(str)

    def __init__(self, url: str, temp_dir: str, cookies_file: str = "", parent=None):
        super().__init__(parent)
        self.url = url
        self.temp_dir = temp_dir
        self.cookies_file = cookies_file
        self.final_wav_path = ""
        self.v_id = self.get_v_id(url)

    @staticmethod
    def get_v_id(url: str) -> str:
        """Estrae l'ID del video YouTube dall'URL."""
        if "v=" in url:
            return url.split("v=")[1].split("&")[0]
        elif "youtu.be/" in url:
            return url.split("youtu.be/")[1].split("?")[0]
        return "unknown"

    @staticmethod
    def check_if_downloaded(url: str, temp_dir: str) -> str:
        """Ritorna il percorso del file se già scaricato, altrimenti stringa vuota."""
        v_id = YouTubeDownloaderWorker.get_v_id(url)
        if v_id == "unknown": return ""

        if not os.path.exists(temp_dir): return ""

        prefix = f"[{v_id}]"
        for f in os.listdir(temp_dir):
            if f.startswith(prefix) and f.endswith(".wav"):
                f_path = os.path.join(temp_dir, f)
                if YouTubeDownloaderWorker.is_audio_file_valid(f_path):
                    return f_path
        return ""

    @staticmethod
    def is_audio_file_valid(file_path: str) -> bool:
        """Valida che il file WAV sia integro e contiene audio significativo."""
        try:
            if not os.path.exists(file_path):
                return False
            if os.path.getsize(file_path) < 100000:  # Almeno 100KB
                return False
            with wave.open(file_path, 'rb') as wav_file:
                frames = wav_file.getnframes()
                rate = wav_file.getframerate()
                if rate <= 0 or frames <= 0:
                    return False
                duration = frames / float(rate)
                if duration < 5:  # Almeno 5 secondi di audio
                    return False
            return True
        except Exception:
            return False

    def run(self):
        try:
            self._download()
        except Exception as e:
            self.error.emit(strip_ansi(str(e)))

    def _cleanup_output_family(self, output_template: str, final_wav: str):
        """Pulisce tutti i file parziali o corrotti della stessa scarica."""
        base = output_template.replace("%(ext)s", "")
        for candidate in glob.glob(f"{base}*"):
            try:
                if os.path.isfile(candidate):
                    os.remove(candidate)
            except Exception:
                pass
        if os.path.exists(final_wav):
            try:
                os.remove(final_wav)
            except Exception:
                pass

    def _download(self):
        import yt_dlp
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # 1. Recupero Info con tentativi multipli
        self.status.emit("Analisi video (bypass YouTube protection)...")
        self.progress.emit(10)
        
        info = None
        # Lista di client da provare per l'estrazione info
        clients = ['tv_embedded', 'android', 'ios', 'mweb', 'web']
        
        for client in clients:
            self.status.emit(f"Analisi con client: {client}...")
            ydl_opts = {
                'quiet': True, 'no_warnings': True,
                'extractor_args': {'youtube': {'player_client': [client]}},
            }
            if self.cookies_file and os.path.isfile(self.cookies_file):
                ydl_opts['cookiefile'] = self.cookies_file
                
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(self.url, download=False)
                    if info:
                        logger.info(f"Info estratte con client '{client}' per {self.v_id}")
                        break
            except Exception as e:
                logger.warning(f"Client '{client}' fallito per {self.v_id}: {e}")
                continue

        if not info:
            raise Exception("Impossibile recuperare le informazioni del video. Verifica l'URL o usa un file cookies.txt")

        v_id = info.get('id', 'unknown')
        title = sanitize_filename(info.get('title', 'youtube_audio'))
        # Nome file: [ID] Titolo.wav
        safe_name = f"[{v_id}] {title}"
        output_template = os.path.join(self.temp_dir, f"{safe_name}.%(ext)s")
        final_wav = os.path.join(self.temp_dir, f"{safe_name}.wav")
        
        # 1.1 Controlla se esiste già (usa glob perché yt-dlp può usare un nome leggermente diverso)
        already = self.check_if_downloaded(self.url, self.temp_dir)
        if already:
            logger.info(f"File già presente (skip download): {already}")
            self.final_wav_path = already
            self.status.emit(f"File già presente: {os.path.basename(already)}")
            self.progress.emit(100)
            self.finished.emit(self.url, already)
            return

        # Se esiste il nome calcolato ma non valido, pulisci
        if os.path.exists(final_wav):
            self._cleanup_output_family(output_template, final_wav)

        # 2. Configurazione Download (Strategia Fallback: Audio -> Video -> Any)
        self.status.emit(f"Download in corso: {title}")
        
        # Formati da provare in ordine di successo stimato
        format_list = [
            'bestaudio/best',                # Solo audio (preferito)
            'best[height<=480]',             # Video bassa risoluzione (molto stabile)
            'best'                           # Qualsiasi cosa
        ]
        
        def progress_hook(d):
            if d['status'] == 'downloading':
                p = d.get('_percent_str', '0%').replace('%','')
                try: val = int(float(p))
                except: val = 0
                self.progress.emit(20 + int(val * 0.7))
                self.status.emit(f"Download: {d.get('_percent_str', '...')}")

        success = False
        last_err = ""

        for fmt in format_list:
            self.status.emit(f"Tentativo formato: {fmt}...")
            opts = {
                'format': fmt,
                'outtmpl': output_template,
                'quiet': False,
                'no_warnings': False,
                'progress_hooks': [progress_hook],
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'wav',
                    'preferredquality': '0',
                }],
                'postprocessor_args': ['-ar', '16000', '-ac', '1'],
                'nocheckcertificate': True,
            }
            if self.cookies_file and os.path.isfile(self.cookies_file):
                opts['cookiefile'] = self.cookies_file

            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([self.url])

                    # Cerca il WAV con glob (il nome esatto puo' variare per chars speciali nel titolo)
                    v_id_prefix = f"[{v_id}]"
                    wav_candidates = glob.glob(os.path.join(self.temp_dir, f"{v_id_prefix}*.wav"))
                    found_wav = ""
                    for candidate in wav_candidates:
                        if self.is_audio_file_valid(candidate):
                            found_wav = candidate
                            break

                    if found_wav:
                        final_wav = found_wav
                        logger.info(f"WAV trovato e valido: {found_wav}")
                        success = True
                        break
                    else:
                        # Log dei file presenti per debug
                        all_files = glob.glob(os.path.join(self.temp_dir, f"{v_id_prefix}*"))
                        logger.warning(f"Formato '{fmt}': WAV non valido. File trovati: {all_files}")
                        self._cleanup_output_family(output_template, final_wav)
            except Exception as e:
                last_err = str(e)
                logger.error(f"Errore download formato '{fmt}' per {v_id}: {e}")
                self._cleanup_output_family(output_template, final_wav)
                continue

        if not success:
            raise Exception(f"Tutti i tentativi di download sono falliti.\n{last_err}")

        self.final_wav_path = final_wav

        self.progress.emit(100)
        self.status.emit("Download completato!")
        self.finished.emit(self.url, final_wav)

    def _get_title_safe(self) -> str:
        """Utility per recuperare il titolo sanificato senza info scaricate (euristica)."""
        # Questo è un fallback se l'agente non ha ancora le info.
        # Ma l'agente può passare le info se necessario.
        return sanitize_filename(self.url.split("=")[-1])
