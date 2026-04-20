import os
import re
import yt_dlp
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
    
    # Regex per estrarre la citazione biblica dalla descrizione
    # Cerca pattern come "Vangelo: Mt 5, 1-12" o "Lettura: Lc 1, 1-5" o semplicemente citazioni
    BIBLICAL_REF_PATTERNS = [
        re.compile(r'(?:Vangelo|Lettura|Brano|Testo):\s*([A-Za-z0-9\s,.-]+)', re.IGNORECASE),
        re.compile(r'([1-3]?\s?[A-Z][a-z]+\.?\s\d+[\s,:]+\d+(?:-\d+)?)')
    ]

    def __init__(self, max_videos: int = 5, parent=None):
        super().__init__(parent)
        self.settings = AppSettings()
        self.db = PrayerDatabase(self.settings.db_path)
        self.max_videos = max_videos
        self._is_aborted = False

    def abort(self):
        self._is_aborted = True

    def run(self):
        processed_count = 0
        try:
            self.status_message.emit("Ricerca nuovi video sul canale Sant'Egidio...")
            videos = self._fetch_recent_videos()
            
            if not videos:
                self.status_message.emit("Nessun video trovato sul canale.")
                self.finished.emit(0)
                return

            # Filtra: "preghiera" nel titolo e lingua italiana (escludendo altre lingue comuni)
            # SALTA video in programma (live future) e video di oggi
            filtered_videos = []
            today_str = datetime.now().strftime("%Y%m%d")
            
            for v in videos:
                title = v.get('title', '').lower()
                video_id = v.get('id')
                
                # 1. Deve contenere "preghiera" o "memoria"
                if "preghiera" not in title and "memoria" not in title:
                    continue
                
                # 2. Solo italiano (escludi titoli con lingue straniere)
                if any(lang in title for lang in ["english", "español", "français", "português", "deutsch"]):
                    continue
                
                # 3. Salta se già processato
                if self.db.is_video_processed(video_id):
                    continue

                # 4. Salta video in programma o live imminenti
                # yt-dlp flat_extract può dare live_status
                live_status = v.get('live_status')
                if live_status == 'upcoming' or "in programma" in title:
                    continue
                
                # 5. Salta video di oggi (parti da ieri)
                # Nota: v.get('upload_date') potrebbe mancare in flat_extract
                # Se manca, lo verificheremo dopo o lo consideriamo ok per ora
                upload_date = v.get('upload_date')
                if upload_date and upload_date >= today_str:
                    continue
                
                filtered_videos.append(v)

            if not filtered_videos:
                self.status_message.emit("Tutte le preghiere filtrate sono già state trascritte.")
                self.finished.emit(0)
                return

            self.status_message.emit(f"Trovati {len(filtered_videos)} video potenziali. Cerco di trascriverne {self.max_videos}...")
            
            for i, video in enumerate(filtered_videos):
                if self._is_aborted:
                    break
                
                if processed_count >= self.max_videos:
                    break
                
                try:
                    self._process_video(video, processed_count, self.max_videos)
                    # Se non ci sono errori, il video è stato scaricato e trascritto con successo
                    processed_count += 1
                except Exception as e:
                    err_msg = str(e)
                    if "live event will begin in" in err_msg or "upcoming" in err_msg:
                        self.log_message.emit(f"⏭ Video {video['id']} saltato (evento programmato).")
                        logger.info(f"Skipping upcoming event {video['id']}")
                    elif "video_of_today" in err_msg:
                        self.log_message.emit(f"⏭ Video {video['id']} saltato (è di oggi, partiamo da ieri).")
                        logger.info(f"Skipping video from today {video['id']}")
                    else:
                        logger.error(f"Errore durante l'elaborazione del video {video['id']}: {e}")
                        self.log_message.emit(f"❌ Errore video {video['id']}: {e}")

            self.status_message.emit(f"Completato! Elaborate {processed_count} preghiere.")
            self.finished.emit(processed_count)

        except Exception as e:
            logger.error(f"Errore agente preghiere: {e}", exc_info=True)
            self.error.emit(str(e))

    def _fetch_recent_videos(self) -> list:
        """Recupera gli ultimi 50 video dal canale per garantire di trovarne abbastanza."""
        ydl_opts = {
            'quiet': True,
            'extract_flat': 'in_playlist',
            'playlistend': 50,
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
        
        # Verifica rigorosa: salta i video di "oggi" come richiesto (parti da ieri)
        today_str = datetime.now().strftime("%Y%m%d")
        if upload_date >= today_str:
            raise ValueError("video_of_today")
            
        # 3. Estrai riferimento biblico dalla descrizione
        scripture_ref = self._extract_scripture_ref(description)
        scripture_text = ""
        if scripture_ref:
            self.log_message.emit(f"📖 Riferimento biblico trovato: {scripture_ref}")
            scripture_text = fetch_cei_text(scripture_ref)
        
        # 4. Scarica audio COMPLETO del video prima di identificare la meditazione
        self.status_message.emit(f"Download video/audio in corso...")
        self.log_message.emit(f"⏳ Download dell'audio (può richiedere tempo per dirette lunghe)...")
        downloader = YouTubeDownloaderWorker(video_url, self.settings.temp_dir, self.settings.cookies_file)
        downloader._download() # Esecuzione sincrona
        audio_path = downloader.final_wav_path
        
        if not audio_path or not os.path.exists(audio_path):
            raise RuntimeError("Download fallito: file WAV non trovato.")

        if self._is_aborted: return

        # 5. Trascrizione dell'intero audio (necessaria perché mancano i sottotitoli di base)
        self.status_message.emit(f"Trascrizione in corso (potrebbe richiedere diversi minuti)...")
        self.log_message.emit("🧠 Trascrizione completa in corso per individuare la meditazione...")
        transcriber = TranscriberWorker(
            file_path=audio_path,
            model_dir=self.settings.model_dir,
            model_name=self.settings.default_model,
            start_sec=0.0,
            end_sec=0.0,
            custom_words=self.settings.custom_words
        )
        
        # Connettiamo un segnale per dare feedback testuale e barra di progresso
        transcriber.progress.connect(self.progress.emit)
        transcriber.status_message.connect(self.status_message.emit)
        
        segments = transcriber._transcribe()
        if not segments:
            raise RuntimeError("Trascrizione fallita: nessun segmento restituito.")

        if self._is_aborted: return

        # 6. Analizza i segmenti per individuare gli "Alleluia" e la fine della meditazione
        self.status_message.emit("Ricerca meditazione nel testo trascritto...")
        start_sec, end_sec = self._find_meditation_bounds(segments, audio_path)
        self.log_message.emit(f"📍 Meditazione individuata: da {int(start_sec)}s a {int(end_sec)}s.")
        
        # Estrai solo i segmenti di testo che compongono la meditazione
        meditation_pieces = [s.text for s in segments if s.start >= start_sec and s.end <= end_sec]
        meditation_text = " ".join(meditation_pieces).strip()
        
        if not meditation_text:
            meditation_text = " ".join(s.text for s in segments) # Fallback totale
            self.log_message.emit("⚠️ Impossibile ritagliare la meditazione. Salvata trascrizione integrale.")

        if self._is_aborted: return

        # 7. Salva nel DB
        self.db.add_prayer(
            date=formatted_date,
            prayer_type=prayer_type,
            scripture_ref=scripture_ref or "",
            scripture_text=scripture_text or "",
            author=author,
            meditation=meditation_text,
            video_id=video_id
        )
        self.log_message.emit(f"✅ Salvato: {prayer_type} del {formatted_date}")

    def _get_full_info(self, url):
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
        }
        if self.settings.cookies_file and os.path.exists(self.settings.cookies_file):
            ydl_opts['cookiefile'] = self.settings.cookies_file

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    def _detect_prayer_type_and_author(self, title, description):
        prayer_type = "Preghiera"
        author = "Comunità di Sant'Egidio"
        
        # Estrai il Tipo: la prima parte del titolo fino al punto o trattino
        if '.' in title:
            prayer_type = title.split('.')[0].strip()
        elif '-' in title:
            prayer_type = title.split('-')[0].strip()
        else:
            prayer_type = title.strip()
            
        # Pulisci eventuali tag dal tipo
        if prayer_type.startswith("Preghiera"):
            # Capitalizza correttamente
            prayer_type = prayer_type[0].upper() + prayer_type[1:]

        # Estrai Autore: "Meditazione di [Nome Cognome]"
        import re
        # Regex che cattura tutto dopo "Meditazione di" fino a un trattino o fine stringa (permettendo i punti come in Mons.)
        match_author = re.search(r'Meditazione di\s+([^-|\n]+)', title, re.IGNORECASE)
        if match_author:
            a_text = match_author.group(1).strip()
            # Rimuovi la parte "su...", "sul...", "sulla..." che spesso segue il nome
            a_text = re.split(r'\s+su\s+|\s+sul\s+|\s+sulla\s+', a_text, flags=re.IGNORECASE)[0].strip()
            # Pulisci solo se il nome è rimasto troppo corto o strano, altrimenti tienilo
            author = a_text
        else:
            # Prova a cercare nella descrizione
            match_author_desc = re.search(r'Meditazione di\s+([^\n-]+)', description, re.IGNORECASE)
            if match_author_desc:
                a_text = match_author_desc.group(1).strip()
                a_text = re.split(r'\s+su\s+|\s+sul\s+|\s+sulla\s+', a_text, flags=re.IGNORECASE)[0].strip()
                author = a_text

        return prayer_type, author

    def _extract_scripture_ref(self, description):
        for pattern in self.BIBLICAL_REF_PATTERNS:
            match = pattern.search(description)
            if match:
                return match.group(1).strip()
        return None

    def _find_meditation_bounds(self, segments, audio_path: str):
        """Scansiona i segmenti trascritti per trovare le frasi chiave che delimitano la meditazione."""
        import subprocess
        import re
        start_sec = 0.0
        
        # --- 1. TROVA L'INIZIO ---
        # Cerchiamo l'ULTIMA occorrenza delle formule di fine lettura per essere sicuri di saltare tutto il brano biblico.
        # Definiamo regex flessibili per ignorare punteggiatura o variazioni comuni.
        start_regex = re.compile(r'(parola del signore|vangelo del signore|parola di dio|parola di salvezza)', re.IGNORECASE)
        last_found_index = -1
        
        for i, s in enumerate(segments):
            if start_regex.search(s.text):
                last_found_index = i
        
        if last_found_index != -1:
            start_sec = segments[last_found_index].end
            self.log_message.emit(f"📍 Trovata fine Lettura/Vangelo al secondo {int(start_sec)}.")
        else:
            # Fallback agli Alleluia se non troviamo la frase testuale
            clusters = []
            current_cluster = []
            for s in segments:
                txt = s.text.lower()
                if 'allelu' in txt or 'alelu' in txt:
                    if not current_cluster:
                        current_cluster.append(s)
                    else:
                        if s.start - current_cluster[-1].end < 45.0:
                            current_cluster.append(s)
                        else:
                            clusters.append(current_cluster)
                            current_cluster = [s]
            if current_cluster: clusters.append(current_cluster)
            major_clusters = [c for c in clusters if len(c) >= 3]
            
            if len(major_clusters) >= 2:
                start_sec = major_clusters[1][-1].end
            elif len(major_clusters) == 1:
                start_sec = major_clusters[0][-1].end
            elif len(clusters) >= 2:
                start_sec = clusters[1][-1].end
            elif len(clusters) == 1:
                start_sec = clusters[0][-1].end
            else:
                self.log_message.emit("⚠️ Nessun marker di inizio (Parola/Alleluia) individuato.")

        # --- 2. TROVA LA FINE ---
        # Impostiamo un limite massimo ragionevole (20 minuti dall'inizio della meditazione)
        end_sec = segments[-1].end
        
        # Metodo testuale: cerchiamo preghiere conclusive (Padre Nostro, Magnificat, ecc.)
        end_regex = re.compile(r"(padre nostro che sei|l'anima mia magnifica|benedetto il signore|gloria al padre|custodisci il tuo popolo)", re.IGNORECASE)
        found_end_textually = False
        
        # Cerchiamo la preghiera conclusiva partendo dalla fine verso l'inizio (per non prendere citazioni interne)
        for i in range(len(segments)-1, -1, -1):
            s = segments[i]
            if s.start > start_sec + 180.0: # almeno 3 minuti di meditazione
                if end_regex.search(s.text):
                    end_sec = s.start
                    found_end_textually = True
                    self.log_message.emit(f"📍 Trovata preghiera post-omelia al secondo {int(end_sec)}.")
                    break

        # Metodo Acustico (FFmpeg): se non abbiamo trovato cantici, cerchiamo il primo VERO silenzio lungo.
        # Portiamo a 10 secondi per evitare di tagliare durante le pause enfatiche.
        if not found_end_textually:
            cmd = [
                "ffmpeg", "-ss", str(start_sec), "-i", audio_path,
                "-af", "silencedetect=noise=-30dB:d=10.0",
                "-f", "null", "-"
            ]
            
            result = subprocess.run(
                cmd, capture_output=True, text=True, errors='ignore',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            )
            
            # Scorriamo i silenzi e prendiamo il primo che appare dopo almeno 6 minuti (l'omelia media)
            # o l'ultimo se non ce ne sono dopo i 6 minuti.
            min_homily_duration = 360.0 
            possible_ends = []
            
            for line in result.stderr.split('\n'):
                if "silence_start:" in line:
                    parts = line.split("silence_start:")
                    if len(parts) > 1:
                        try:
                            val = float(parts[1].split()[0])
                            possible_ends.append(start_sec + val)
                        except ValueError: pass
            
            # Filtriamo quelli ragionevoli e prendiamo il primo
            for p_end in possible_ends:
                if p_end > start_sec + min_homily_duration:
                    end_sec = p_end
                    break
            else:
                # Se non ce ne sono dopo 6 minuti, prendiamo l'ultimo disponibile (se ne esistono)
                if possible_ends:
                    end_sec = possible_ends[-1]

        return start_sec, end_sec
