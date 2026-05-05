import os
import datetime
import json
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QTreeWidget, QTreeWidgetItem, QLabel, QProgressBar,
                             QMessageBox, QHeaderView, QComboBox, QSpinBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QIcon, QColor, QFont

import yt_dlp
from core.database import PrayerDatabase
from config.settings import AppSettings
from core.logger import get_logger
from core.downloader import sanitize_filename, YouTubeDownloaderWorker

logger = get_logger("VideoLibrary")

HISTORY_FILE = "video_history.json"

class LibrarySyncWorker(QThread):
    """Sincronizza un intervallo di tempo specifico scaricando i dati da YouTube finché non completa il mese."""
    video_found = pyqtSignal(dict)
    finished = pyqtSignal()
    status = pyqtSignal(str)

    def __init__(self, target_month_range, settings):
        """target_month_range: (year, month)"""
        super().__init__()
        self.target_year, self.target_month = target_month_range
        self.settings = settings
        self._is_aborted = False

    def abort(self): self._is_aborted = True

    def run(self):
        self.status.emit(f"Sincronizzazione {self.target_month}/{self.target_year}...")
        
        ydl_opts = {
            'quiet': True,
            'extract_flat': False, # Ci servono le date subito per decidere quando fermarci
            'playlistend': 500,
            'headers': { 'Accept-Language': 'it-IT,it;q=0.9' }
        }
        if self.settings.cookies_file and os.path.exists(self.settings.cookies_file):
            ydl_opts['cookiefile'] = self.settings.cookies_file

        url = "https://www.youtube.com/@santegidio/streams"
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Purtroppo yt-dlp flat extract non ci dà le date.
            # Dobbiamo scansionare i video uno ad uno. 
            # Per efficienza, prendiamo prima la lista flat e poi fetchiamo finché non superiamo il mese target.
            flat_opts = ydl_opts.copy()
            flat_opts['extract_flat'] = 'in_playlist'
            
            with yt_dlp.YoutubeDL(flat_opts) as ydl_flat:
                res = ydl_flat.extract_info(url, download=False)
                entries = res.get('entries', [])
                
            old_videos_count = 0
            for v in entries:
                if self._is_aborted: break
                
                v_id = v.get('id')
                try:
                    # Fetch approfondito per avere la data reale
                    # Nota: scaricare i metadata è veloce
                    info = ydl.extract_info(f"https://www.youtube.com/watch?v={v_id}", download=False)
                    u_date = info.get('upload_date')
                    if u_date:
                        dt = datetime.datetime.strptime(u_date, "%Y%m%d")
                        
                        # LOGICA DI STOP
                        # Se il video è del mese target, lo emettiamo
                        if dt.year == self.target_year and dt.month == self.target_month:
                            self.video_found.emit(info)
                        
                        # Se abbiamo superato il mese target andando nel passato ripetutamente, FERMIAMO
                        # Usiamo un contatore perché YouTube a volte mischia eventi Live programmati (che hanno date future/passate sballate)
                        if dt.year < self.target_year or (dt.year == self.target_year and dt.month < self.target_month):
                            old_videos_count += 1
                            if old_videos_count > 10:
                                self.status.emit("Raggiunto limite temporale. Stop.")
                                break
                        else:
                            # Se troviamo un video recente o target, resettiamo il counter
                            old_videos_count = 0
                    
                except Exception as e:
                    logger.warning(f"Errore sync video {v_id}: {e}")

        self.finished.emit()

class VideoHistoryTab(QWidget):
    request_transcription = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = AppSettings()
        self.db = PrayerDatabase(self.settings.db_path)
        self.library_data = self._load_library()
        self.sync_worker = None
        self.max_months = 24  # Numero iniziale di mesi visibili
        self._build_ui()
        self._populate_full_tree()

    def _load_library(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except: return {}
        return {}

    def _save_library(self):
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(self.library_data, f, indent=4, ensure_ascii=False)

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # --- Riga 1: titolo + aggiorna mese corrente ---
        header = QHBoxLayout()
        title = QLabel("Libreria Video Storica")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #d32f2f;")
        header.addWidget(title)

        self.btn_sync_current = QPushButton("\U0001f504 Aggiorna Mese Corrente")
        self.btn_sync_current.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold; padding: 6px 12px; border-radius: 4px;")
        self.btn_sync_current.clicked.connect(self.sync_current_month)
        header.addWidget(self.btn_sync_current)

        header.addStretch()
        self.status_lbl = QLabel("Pronto.")
        header.addWidget(self.status_lbl)
        layout.addLayout(header)

        # --- Riga 2: picker anno/mese libero ---
        picker_row = QHBoxLayout()
        picker_row.addWidget(QLabel("Anno:"))
        self.spin_year = QSpinBox()
        now = datetime.datetime.now()
        self.spin_year.setRange(2015, now.year)
        self.spin_year.setValue(now.year)
        self.spin_year.setFixedWidth(70)
        picker_row.addWidget(self.spin_year)

        picker_row.addWidget(QLabel("Mese:"))
        self.combo_month_name = QComboBox()
        MONTH_NAMES = ["Gennaio","Febbraio","Marzo","Aprile","Maggio","Giugno",
                       "Luglio","Agosto","Settembre","Ottobre","Novembre","Dicembre"]
        for i, m in enumerate(MONTH_NAMES, 1):
            self.combo_month_name.addItem(m, i)
        self.combo_month_name.setCurrentIndex(now.month - 1)
        self.combo_month_name.setFixedWidth(120)
        picker_row.addWidget(self.combo_month_name)

        self.btn_sync_selected_month = QPushButton("\U0001f504 Sincronizza Mese")
        self.btn_sync_selected_month.setStyleSheet("background-color: #455a64; color: white; font-weight: bold; padding: 6px 12px; border-radius: 4px;")
        self.btn_sync_selected_month.clicked.connect(self.sync_selected_month)
        picker_row.addWidget(self.btn_sync_selected_month)

        self.btn_run_agent_month = QPushButton("\u25b6 Avvia Agente su Mese")
        self.btn_run_agent_month.setStyleSheet("background-color: #1a7340; color: white; font-weight: bold; padding: 6px 12px; border-radius: 4px;")
        self.btn_run_agent_month.setToolTip("Scarica e trascrive automaticamente tutti i video del mese selezionato")
        self.btn_run_agent_month.clicked.connect(self.on_run_agent_on_month)
        picker_row.addWidget(self.btn_run_agent_month)

        picker_row.addStretch()
        layout.addLayout(picker_row)


        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Mese / Titolo Video", "Data", "Stato"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.setStyleSheet("QTreeWidget::item { padding: 5px; }")
        layout.addWidget(self.tree)

        footer = QHBoxLayout()
        btn_transcribe = QPushButton("🚀 Trascrivi Selezionati")
        btn_transcribe.setMinimumHeight(40)
        btn_transcribe.setStyleSheet("background-color: #34a853; color: white; font-weight: bold;")
        btn_transcribe.clicked.connect(self.on_transcribe_clicked)
        
        btn_load_more = QPushButton("⏬ Carica altri mesi precedenti")
        btn_load_more.setMinimumHeight(40)
        btn_load_more.setStyleSheet("background-color: #607d8b; color: white; font-weight: bold;")
        btn_load_more.clicked.connect(self.load_older_months)
        
        footer.addWidget(btn_load_more)
        footer.addStretch()
        footer.addWidget(btn_transcribe)
        layout.addLayout(footer)

    def _populate_full_tree(self):
        """Crea la struttura dei mesi e inserisce i video caricati dalla libreria."""
        self.tree.clear()
        self.month_items = {}

        month_keys = self._get_recent_month_keys(self.max_months)
        for year, month in month_keys:
            key = (year, month)
            m_item = QTreeWidgetItem(self.tree)
            m_item.setText(0, f"{self._get_month_name(month)} {year}")
            m_item.setText(2, "0 video")
            m_item.setFont(0, QFont("Segoe UI", 11, QFont.Bold))
            m_item.setBackground(0, QColor("#fef2f2"))
            m_item.setForeground(2, QColor("#6b738f"))
            self.month_items[key] = m_item

        self._refresh_month_selector(month_keys)

        for _, info in sorted(self.library_data.items(), key=lambda kv: kv[1].get('upload_date', ''), reverse=True):
            u_date = info.get('upload_date')
            if not u_date:
                continue
            dt = datetime.datetime.strptime(u_date, "%Y%m%d")
            self._add_video_to_tree(info, dt)

        self._update_month_badges()

    def _add_video_to_tree(self, info, dt):
        key = (dt.year, dt.month)
        if key not in self.month_items:
            return

        title = info.get('title', '')
        title_low = title.lower()

        # Filtra via video non pertinenti
        if not any(k in title_low for k in ["preghiera", "memoria", "liturgia", "veglia"]):
            return
        if any(k in title_low for k in ["prayer", "pri\u00e8re", "ora\u00e7\u00e3o", "english", "fran\u00e7ais"]):
            return
        # Liturgie blacklistate: non mostrare nel tree
        if self.settings.is_title_blacklisted(title):
            return

        parent = self.month_items[key]

        exists = False
        for i in range(parent.childCount()):
            child_data = parent.child(i).data(0, Qt.UserRole)
            if child_data and child_data.get('id') == info.get('id'):
                exists = True
                break
        if exists:
            return

        v_item = QTreeWidgetItem(parent)
        v_item.setText(0, info.get('title'))
        v_item.setText(1, dt.strftime("%d/%m/%Y"))
        v_item.setData(0, Qt.UserRole, info)

        v_id = info.get('id')
        url = f"https://www.youtube.com/watch?v={v_id}"
        is_downloaded = bool(YouTubeDownloaderWorker.check_if_downloaded(url, self.settings.temp_dir))
        is_processed = self.db.is_video_processed(v_id)

        if is_processed:
            v_item.setText(2, "\u2705 Trascritto")
            v_item.setForeground(2, QColor("#34a853"))
        elif is_downloaded:
            v_item.setText(2, "\u2b07\ufe0f Scaricato")
            v_item.setForeground(2, QColor("#2a5cbf"))
        else:
            v_item.setText(2, "\u23f3 Da fare")
            v_item.setForeground(2, QColor("#ea4335"))

        f = v_item.font(0)
        f.setBold(True)
        v_item.setFont(0, f)

    def sync_month(self, key):
        if self.sync_worker and self.sync_worker.isRunning():
            QMessageBox.warning(self, "Occupato", "Una sincronizzazione è già in corso.")
            return
            
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.sync_worker = LibrarySyncWorker(key, self.settings)
        self.sync_worker.video_found.connect(self.on_video_found)
        self.sync_worker.status.connect(self.status_lbl.setText)
        self.sync_worker.finished.connect(self.on_sync_finished)
        self.sync_worker.start()

    def on_video_found(self, info):
        v_id = info.get('id')
        self.library_data[v_id] = info
        u_date = info.get('upload_date')
        if u_date:
            dt = datetime.datetime.strptime(u_date, "%Y%m%d")
            self._add_video_to_tree(info, dt)
            self._update_month_badges()
        self._save_library()

    def sync_current_month(self):
        now = datetime.datetime.now()
        key = (now.year, now.month)
        self.sync_month(key)

    def sync_selected_month(self):
        year = self.spin_year.value()
        month = self.combo_month_name.currentData()
        if not month:
            return
        # Assicura che il mese sia nel tree
        key = (year, month)
        if key not in self.month_items:
            # Espandi il tree aggiungendo il mese mancante
            m_item = self._ensure_month_in_tree(year, month)
        self.sync_month((year, month))

    def _ensure_month_in_tree(self, year, month):
        """Aggiunge un mese al tree se non esiste ancora."""
        key = (year, month)
        if key in self.month_items:
            return self.month_items[key]
        m_item = QTreeWidgetItem(self.tree)
        m_item.setText(0, f"{self._get_month_name(month)} {year}")
        m_item.setText(2, "0 video")
        m_item.setFont(0, QFont("Segoe UI", 11, QFont.Bold))
        m_item.setBackground(0, QColor("#fef2f2"))
        m_item.setForeground(2, QColor("#6b738f"))
        self.month_items[key] = m_item
        return m_item

    def load_older_months(self):
        self.max_months += 12 # Aumenta lo storico di 1 anno
        self._populate_full_tree()

    def on_sync_finished(self):
        self.progress.setVisible(False)
        self.status_lbl.setText("Sincronizzazione completata.")

    def on_transcribe_clicked(self):
        selected = self.tree.selectedItems()
        videos = [it.data(0, Qt.UserRole) for it in selected if it.data(0, Qt.UserRole)]
        # Non trascrivere video in blacklist o già trascritti
        videos = [
            v for v in videos
            if not self.settings.is_title_blacklisted(v.get('title', ''))
            and not self.db.is_video_processed(v.get('id', ''))
        ]
        if not videos:
            QMessageBox.information(self, "Nessun video", "Nessun video selezionabile (già trascritti o esclusi dalla blacklist).")
            return
        self.request_transcription.emit(videos)
        self.window().tabs.setCurrentIndex(0)

    def on_run_agent_on_month(self):
        """Raccoglie i video del mese selezionato dalla libreria e li manda all'agente."""
        year = self.spin_year.value()
        month = self.combo_month_name.currentData()
        month_name = f"{self._get_month_name(month)} {year}"

        # Recupera i video del mese dal tree (già in libreria)
        m_item = self.month_items.get((year, month))
        videos = []
        if m_item:
            for i in range(m_item.childCount()):
                child = m_item.child(i)
                info = child.data(0, Qt.UserRole)
                if info:
                    v_id = info.get('id', '')
                    title = info.get('title', '')
                    # Salta blacklisted e già trascritti
                    if self.settings.is_title_blacklisted(title):
                        continue
                    if self.db.is_video_processed(v_id):
                        continue
                    videos.append(info)

        if not videos:
            # Il mese potrebbe non essere stato sincronizzato: sincronizzo prima e poi riavvio
            reply = QMessageBox.question(
                self, f"Nessun video — {month_name}",
                f"Non ci sono video da trascrivere per {month_name}.\n"
                "Vuoi prima sincronizzare il mese per recuperarli da YouTube?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                # Dopo la sync, l'utente può ricliccare il pulsante
                self.sync_month((year, month))
            return

        reply = QMessageBox.question(
            self, f"Avvia Agente — {month_name}",
            f"Verranno trascritti {len(videos)} video di {month_name}:\n\n"
            + "\n".join(f"  • {v.get('title', '')[:70]}" for v in videos[:8])
            + (f"\n  ... e altri {len(videos)-8}" if len(videos) > 8 else "")
            + "\n\nContinuare?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        # Emette il segnale verso PrayersTab che gestisce l'agente
        self.request_transcription.emit(videos)

    def _get_month_name(self, n):
        return ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
                "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"][n-1]

    def _get_recent_month_keys(self, n):
        now = datetime.datetime.now()
        year = now.year
        month = now.month
        keys = []
        for _ in range(max(0, n)):
            keys.append((year, month))
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        return keys

    def _refresh_month_selector(self, month_keys):
        """Non più necessario: il picker è libero. Mantenuto per compatibilità."""
        pass

    def _update_month_badges(self):
        for _, item in self.month_items.items():
            count = item.childCount()
            item.setText(2, "1 video" if count == 1 else f"{count} video")