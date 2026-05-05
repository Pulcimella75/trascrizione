import os
import re
import yt_dlp
import json
from datetime import datetime
from PyQt5.QtCore import QThread, pyqtSignal

from core.database import PrayerDatabase
from core.cei_scraper import fetch_cei_text
from core.downloader import YouTubeDownloaderWorker
from core.meditation_extractor import MeditationFinderWorker
from core.transcriber import TranscriberWorker
from config.settings import AppSettings
from core.logger import get_logger

logger = get_logger("PrayerAgent")

class PrayerAgentWorker(QThread):
    """
    Agente che identifica preghiere non ancora trascritte sul canale Sant'Egidio,
    le scarica, individua la meditazione, le trascrive e le salva nel database.
    """
    progress = pyqtSignal(int)
    status_message = pyqtSignal(str)
    log_message = pyqtSignal(str)
    finished = pyqtSignal(int)  # Numero di preghiere elaborate
    error = pyqtSignal(str)

    CHANNEL_URL = "https://www.youtube.com/@santegidio/streams"
    MAX_DOWNLOAD_RETRIES = 2

    # Regex per estrarre la citazione biblica dalla descrizione
    BIBLICAL_REF_PATTERNS = [
        re.compile(r'(?:Vangelo|Lettura|Brano|Testo):\s*([A-Za-z0-9\s,.-]+)', re.IGNORECASE),
        re.compile(r'([1-3]?\s?[A-Z][a-z]+\.?\s\d+[\s,:]+\d+(?:-\d+)?)')
    ]

    def __init__(self, max_videos: int = 5, manual_videos: list = None, parent=None):
        super().__init__(parent)
        self.settings = AppSettings()
        self.db = PrayerDatabase(self.settings.db_path)
        self.max_videos = max_videos
        self.manual_videos = manual_videos
        self._is_aborted = False

    def abort(self):
        self._is_aborted = True

    def run(self):
        processed_count = 0
        try:
            candidates = []
            
            if self.manual_videos:
                self.status_message.emit("Preparazione video selezionati...")
                candidates = self.manual_videos
                logger.info(f"Avvio agente in modalità MANUALE su {len(candidates)} video.")
            else:
                self.status_message.emit("Ricerca nuovi video sul canale Sant'Egidio...")
                videos = self._fetch_recent_videos()
                
                if not videos:
                    self.status_message.emit("Nessun video trovato sul canale.")
                    self.finished.emit(0)
                    return

                # Scansione approfondita dei candidati (metadata completi per avere le date reali)
                self.status_message.emit("Analisi approfondita video recenti...")
                checked_count = 0
                keywords = ["preghiera", "memoria"]
                
                for v in videos:
                    if self._is_aborted: break
                    title = v.get('title', '').lower()
                    video_id = v.get('id')
                    
                    # 1. Filtri preliminari rapidi (Titolo e Lingua)
                    if not any(k in title for k in keywords): continue
                    if any(lang in title for lang in ["prayer", "prière", "oracion", "oração", "english", "español", "français"]): continue

                    # 2. Filtro blacklist (liturgie eucaristiche, messe, ecc.)
                    raw_title = v.get('title', '')
                    if self.settings.is_title_blacklisted(raw_title):
                        logger.info(f"🚫 Blacklist: saltato '{raw_title[:60]}'")
                        self.log_message.emit(f"🚫 Escluso (blacklist): {raw_title[:60]}")
                        continue

                    if self.db.is_video_processed(video_id): continue
                    
                    # 3. Recupero metadati completi per avere la data reale
                    try:
                        full_v = self._get_full_info(f"https://www.youtube.com/watch?v={video_id}")
                        u_date = full_v.get('upload_date', '00000000')
                        
                        # Logghiamo per debug
                        logger.info(f"📍 Candidato trovato: {title[:50]}... Data YouTube: {u_date}")
                        candidates.append(full_v)
                        checked_count += 1
                    except Exception as e:
                        logger.warning(f"Errore recupero info per {video_id}: {e}")
                    
                    if checked_count >= 15: break

            if not candidates:
                self.status_message.emit("Nessuna nuova preghiera trovata.")
                self.finished.emit(0)
                return

            # 3. Ordiniamo i candidati per data REALE (Dal più recente al più vecchio)
            candidates.sort(key=lambda x: x.get('upload_date', '00000000'), reverse=True)
            
            self.status_message.emit(f"Trovati {len(candidates)} video pronti. Inizio elaborazione...")
            
            for i, video in enumerate(candidates):
                if self._is_aborted: break
                if processed_count >= self.max_videos: break
                
                # Salta video ancora in programma (non ancora trasmessi)
                if video.get('live_status') == 'upcoming':
                    logger.info(f"Skipping upcoming event: {video['id']}")
                    continue

                try:
                    self._process_video(video, processed_count, self.max_videos)
                    processed_count += 1
                except Exception as e:
                    if str(e) == "video_of_future":
                        self.log_message.emit(f"⏭ Video {video['id']} saltato (data futura).")
                    else:
                        logger.error(f"Errore durante l'elaborazione del video {video['id']}: {e}")
                        self.log_message.emit(f"❌ Errore video {video['id']}: {e}")

            self.status_message.emit(f"Completato! Elaborate {processed_count} preghiere.")
            self.finished.emit(processed_count)

        except Exception as e:
            logger.error(f"Errore agente preghiere: {e}", exc_info=True)
            self.error.emit(str(e))

    def _fetch_recent_videos(self) -> list:
        ydl_opts = {
            'quiet': True,
            'extract_flat': 'in_playlist',
            'playlistend': 300,
        }
        if self.settings.cookies_file and os.path.exists(self.settings.cookies_file):
            ydl_opts['cookiefile'] = self.settings.cookies_file

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(self.CHANNEL_URL, download=False)
            if 'entries' in result:
                return result['entries']
        return []

    def _process_video(self, video_info, index, total):
        video_id = video_info['id']
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        video_title = video_info.get('title', 'Senza titolo')
        
        self.log_message.emit(f"🔄 Elaborazione {index+1}/{total}: {video_title}")
        
        # 1. Recupera metadati dettagliati (descrizione)
        self.status_message.emit(f"Recupero dettagli: {video_title}...")
        full_info = self._get_full_info(video_url)
        description = full_info.get('description', '')
        
        # 2. Identifica tipo, autore e data
        prayer_type, author = self._detect_prayer_type_and_author(video_title, description)
        upload_date = full_info.get('upload_date', datetime.now().strftime("%Y%m%d"))
        formatted_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
        
        # Verifica rigorosa: salta i video futuri
        today_str = datetime.now().strftime("%Y%m%d")
        if upload_date > today_str:
            raise ValueError("video_of_future")
            
        # 3. Estrai riferimento biblico dalla descrizione
        scripture_ref = self._extract_scripture_ref(description)
        scripture_text = ""
        if scripture_ref:
            self.log_message.emit(f"📖 Riferimento biblico trovato: {scripture_ref}")
            scripture_text = fetch_cei_text(scripture_ref)
        
        # 4. Scarica audio
        self.status_message.emit(f"Download audio in corso...")
        downloader = YouTubeDownloaderWorker(video_url, self.settings.temp_dir, self.settings.cookies_file)
        audio_path = ""
        for attempt in range(self.MAX_DOWNLOAD_RETRIES + 1):
            downloader._download()
            audio_path = downloader.final_wav_path
            if audio_path and os.path.exists(audio_path) and YouTubeDownloaderWorker.is_audio_file_valid(audio_path):
                break
            if audio_path and os.path.exists(audio_path):
                try:
                    os.remove(audio_path)
                except OSError:
                    pass
            if attempt >= self.MAX_DOWNLOAD_RETRIES:
                raise RuntimeError("Download fallito: file WAV corrotto/non valido.")
            self.log_message.emit(f"⚠️ File audio non valido, nuovo tentativo ({attempt + 1}/{self.MAX_DOWNLOAD_RETRIES})")

        if not audio_path or not os.path.exists(audio_path):
            raise RuntimeError("Download fallito: file WAV non trovato.")

        if self._is_aborted: return

        # 5. Trascrizione
        self.status_message.emit(f"Trascrizione in corso...")
        transcriber = TranscriberWorker(
            file_path=audio_path,
            model_dir=self.settings.model_dir,
            model_name=self.settings.default_model,
            start_sec=0.0,
            end_sec=0.0,
            custom_words=self.settings.custom_words
        )
        
        transcriber.progress.connect(self.progress.emit)
        transcriber.status_message.connect(self.status_message.emit)
        
        segments = transcriber._transcribe()
        if not segments:
            raise RuntimeError("Trascrizione fallita: nessun segmento restituito.")

        if self._is_aborted: return

        # 6. Analizza i segmenti con il nuovo sistema a markers LITURGICI
        self.status_message.emit("Ricerca meditazione nel testo trascritto...")
        start_sec, end_sec = self._find_meditation_bounds(segments, audio_path)
        self.log_message.emit(f"📍 Meditazione individuata: {int(start_sec)}s -> {int(end_sec)}s.")
        
        meditation_pieces = [s.text for s in segments if s.start >= start_sec and s.end <= end_sec]
        meditation_text = " ".join(meditation_pieces).strip()
        
        if not meditation_text:
            meditation_text = " ".join(s.text for s in segments)
            self.log_message.emit("⚠️ Fallback: salvata trascrizione integrale.")

        if self._is_aborted: return

        # 7. Salva nel DB
        import json
        segments_data = [
            {"start": s.start, "end": s.end, "text": s.text} 
            for s in segments
        ]
        full_json = json.dumps(segments_data)
        
        self.db.add_prayer(
            date=formatted_date,
            prayer_type=prayer_type,
            scripture_ref=scripture_ref or "",
            scripture_text=scripture_text or "",
            author=author,
            meditation=meditation_text,
            video_id=video_id,
            v_start=start_sec,
            v_end=end_sec,
            full_json=full_json
        )
        self.log_message.emit(f"✅ Salvato: {prayer_type} del {formatted_date}")

    def _get_full_info(self, url):
        ydl_opts = {'quiet': True, 'no_warnings': True}
        if self.settings.cookies_file and os.path.exists(self.settings.cookies_file):
            ydl_opts['cookiefile'] = self.settings.cookies_file
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    def _detect_prayer_type_and_author(self, title, description):
        prayer_type = "Preghiera"
        author = "Comunità di Sant'Egidio"
        if '.' in title: prayer_type = title.split('.')[0].strip()
        elif '-' in title: prayer_type = title.split('-')[0].strip()
        else: prayer_type = title.strip()
        if prayer_type.startswith("Preghiera"):
            prayer_type = prayer_type[0].upper() + prayer_type[1:]

        match_author = re.search(r'Meditazione di\s+([^-|\n]+)', title, re.IGNORECASE)
        if not match_author:
            match_author = re.search(r'Meditazione di\s+([^\n-]+)', description, re.IGNORECASE)
        
        if match_author:
            a_text = match_author.group(1).strip()
            a_text = re.split(r'\s+su\s+|\s+sul\s+|\s+sulla\s+', a_text, flags=re.IGNORECASE)[0].strip()
            author = a_text
        return prayer_type, author

    def _extract_scripture_ref(self, description):
        for pattern in self.BIBLICAL_REF_PATTERNS:
            match = pattern.search(description)
            if match: return match.group(1).strip()
        return None

    def _load_markers(self):
        """Carica i marker dinamici dal file di configurazione markers.json."""
        marker_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "markers.json")
        try:
            if os.path.exists(marker_path):
                with open(marker_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Errore caricamento markers: {e}")
        return {
            "start_markers": ["parola del signore", "vangelo del signore", "parola di dio"],
            "end_invocation_markers": ["preghiamo", "ti preghiamo", "ascoltaci", "amen"]
        }

    def _find_meditation_bounds(self, segments, audio_path: str):
        """Identifica inizio e fine basandosi sui marker testuali liturgici."""
        markers = self._load_markers()
        start_markers = [m.lower() for m in markers.get("start_markers", [])]
        invocation_markers = [m.lower() for m in markers.get("end_invocation_markers", [])]
        
        start_sec = 0.0
        end_sec = segments[-1].end
        start_idx = 0
        
        # 1. TROVA L'INIZIO (Post-Formula)
        for i, s in enumerate(segments):
            if s.start > 1200: break
            if any(m in s.text.lower() for m in start_markers):
                if i + 1 < len(segments):
                    start_idx = i + 1
                    start_sec = segments[start_idx].start
                    self.log_message.emit(f"📍 Inizio dopo formula: '{s.text}' ({int(s.end)}s)")
                    break
        else:
            self.log_message.emit("⚠️ Nessun marker liturgico trovato. Fallback 0s.")

        # 2. TROVA LA FINE (Pre-Invocazioni)
        for i in range(start_idx, len(segments)):
            text_low = segments[i].text.lower()
            if any(m in text_low for m in invocation_markers):
                if i > start_idx:
                    end_sec = segments[i-1].end
                    self.log_message.emit(f"📍 Fine prima di invocazione: '{segments[i].text}' ({int(end_sec)}s)")
                else:
                    end_sec = segments[i].start
                break
        
        return start_sec, end_sec
