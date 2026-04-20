"""
core/downloader.py
Versione Ultra-Resiliente per YouTube (2026)
Include fix per: 403 Forbidden, nsig extraction failed, empty files, e format discovery.
"""

import os
import re
import shutil
import time
from pathlib import Path
from PyQt5.QtCore import QThread, pyqtSignal

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

    def run(self):
        try:
            self._download()
        except Exception as e:
            self.error.emit(strip_ansi(str(e)))

    def _download(self):
        import yt_dlp
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # 1. Recupero Info con tentativi multipli
        self.status.emit("Analisi video (bypass YouTube protection)...")
        self.progress.emit(10)
        
        info = None
        # Lista di client da provare per l'estrazione info
        clients = ['android', 'ios', 'mweb', 'web']
        
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
                    if info: break
            except:
                continue

        if not info:
            raise Exception("Impossibile recuperare le informazioni del video. Verifica l'URL o usa un file cookies.txt")

        title = sanitize_filename(info.get('title', 'youtube_audio'))
        output_template = os.path.join(self.temp_dir, f"{title}.%(ext)s")
        final_wav = os.path.join(self.temp_dir, f"{title}.wav")
        
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
                'quiet': True,
                'no_warnings': True,
                'progress_hooks': [progress_hook],
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'wav',
                    'preferredquality': '0',
                }],
                'postprocessor_args': ['-ar', '16000', '-ac', '1'],
                # Importante: alcuni server bloccano il re-download se interrotto
                'nocheckcertificate': True,
                'ignoreerrors': True,
            }
            if self.cookies_file and os.path.isfile(self.cookies_file):
                opts['cookiefile'] = self.cookies_file

            try:
                # Pulisci file corrotti precedenti
                for f in Path(self.temp_dir).glob(f"{title}.*"):
                    try: os.remove(f)
                    except: pass
                
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ret_code = ydl.download([self.url])
                    if ret_code == 0 and os.path.exists(final_wav) and os.path.getsize(final_wav) > 10000:
                        success = True
                        break
            except Exception as e:
                last_err = str(e)
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
