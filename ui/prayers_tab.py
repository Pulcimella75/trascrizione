import sys
from datetime import datetime

from PyQt5.QtCore import Qt, QDate, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, 
    QLineEdit, QTextEdit, QPushButton, QComboBox, 
    QDateEdit, QTableWidget, QTableWidgetItem, 
    QMessageBox, QSplitter, QLabel, QHeaderView,
    QGroupBox, QDialog, QPlainTextEdit, QProgressBar,
    QSpinBox, QDoubleSpinBox, QSlider
)
import json

from core.database import PrayerDatabase
from core.cei_scraper import fetch_cei_text
from core.prayer_agent import PrayerAgentWorker
from config.settings import AppSettings

class AgentOptionsDialog(QDialog):
    """Dialog per impostare le opzioni dell'agente prima dell'avvio."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Opzioni Agente")
        self.setFixedWidth(300)
        
        layout = QVBoxLayout(self)
        
        form_layout = QFormLayout()
        self.spin_count = QSpinBox()
        self.spin_count.setRange(1, 100)
        self.spin_count.setValue(5)
        form_layout.addRow("Numero video da elaborare:", self.spin_count)
        
        layout.addLayout(form_layout)
        
        buttons = QHBoxLayout()
        self.btn_ok = QPushButton("Avvia")
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel = QPushButton("Annulla")
        self.btn_cancel.clicked.connect(self.reject)
        
        buttons.addStretch()
        buttons.addWidget(self.btn_cancel)
        buttons.addWidget(self.btn_ok)
        layout.addLayout(buttons)

    def get_count(self):
        return self.spin_count.value()

class AgentLogDialog(QDialog):
    """Finestra di log per l'attività dell'agente."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Agente di Trascrizione Preghiere")
        self.resize(600, 400)
        
        layout = QVBoxLayout(self)
        
        self.status_label = QLabel("Inizializzazione...")
        self.status_label.setStyleSheet("font-weight: bold; color: #2a5cbf;")
        layout.addWidget(self.status_label)
        
        self.log_area = QPlainTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setPlaceholderText("I log dell'agente appariranno qui...")
        layout.addWidget(self.log_area)
        
        self.btn_close = QPushButton("Chiudi / Interrompi")
        self.btn_close.clicked.connect(self.reject)
        layout.addWidget(self.btn_close)

    def append_log(self, text):
        self.log_area.appendPlainText(text)
        self.log_area.verticalScrollBar().setValue(self.log_area.verticalScrollBar().maximum())

class PrayersTab(QWidget):
    """Tab per l'archiviazione e gestione delle preghiere e meditazioni."""
    
    def __init__(self):
        super().__init__()
        self.settings = AppSettings()
        self.db = PrayerDatabase(self.settings.db_path)
        self.current_prayer_id = None
        self.current_prayer_data = None
        self._all_prayers = []
        self._init_ui()
        self.load_table_data()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("<h2>Gestione Preghiere e Meditazioni</h2>"))
        header_layout.addStretch()
        self.btn_agent = QPushButton("🚀 Avvia Agente Automatico")
        self.btn_agent.setObjectName("btn_primary")
        self.btn_agent.setMinimumHeight(40)
        self.btn_agent.clicked.connect(self._on_launch_agent)
        header_layout.addWidget(self.btn_agent)
        main_layout.addLayout(header_layout)

        splitter = QSplitter(Qt.Vertical)
        
        # --- TOP WIDGET: Form ---
        form_widget = QWidget()
        form_layout = QVBoxLayout(form_widget)
        group_box = QGroupBox("Dettagli Preghiera / Meditazione")
        g_layout = QFormLayout(group_box)
        
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.combo_type = QComboBox()
        self.combo_type.addItems(["Lodi", "Vespri", "Compieta", "Ufficio delle Letture", "Meditazione", "Altro"])
        self.combo_type.setEditable(True)
        
        ref_layout = QHBoxLayout()
        self.le_scripture_ref = QLineEdit()
        self.btn_fetch_cei = QPushButton("📖 Cerca Testo CEI")
        self.btn_fetch_cei.clicked.connect(self._on_fetch_cei)
        ref_layout.addWidget(self.le_scripture_ref)
        ref_layout.addWidget(self.btn_fetch_cei)
        
        self.te_scripture_text = QTextEdit()
        self.te_scripture_text.setMaximumHeight(100)
        self.le_author = QLineEdit()
        self.te_meditation = QTextEdit()
        
        g_layout.addRow("Data:", self.date_edit)
        g_layout.addRow("Tipo:", self.combo_type)
        g_layout.addRow("Brano Scrittura:", ref_layout)
        g_layout.addRow("Testo Scrittura:", self.te_scripture_text)
        g_layout.addRow("Autore Meditazione:", self.le_author)
        g_layout.addRow("Testo Meditazione:", self.te_meditation)
        form_layout.addWidget(group_box)
        
        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("💾 Salva Preghiera")
        self.btn_save.clicked.connect(self._on_save_prayer)
        self.btn_clear = QPushButton("Reset Form")
        self.btn_clear.clicked.connect(self._clear_form)
        self.btn_adjust = QPushButton("📏 Aggiusta Meditazione")
        self.btn_adjust.setEnabled(False)
        self.btn_adjust.clicked.connect(self._on_adjust_meditation)
        
        btn_layout.addWidget(self.btn_adjust)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_clear)
        btn_layout.addWidget(self.btn_save)
        form_layout.addLayout(btn_layout)
        
        # --- BOTTOM WIDGET: Table ---
        table_widget = QWidget()
        table_layout = QVBoxLayout(table_widget)
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["ID", "Data", "Tipo", "Brano", "Autore"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.setSortingEnabled(True)
        self.table.itemSelectionChanged.connect(self._on_table_selection)
        self.btn_delete = QPushButton("🗑 Elimina Selezionata")
        self.btn_delete.clicked.connect(self._on_delete_prayer)
        table_layout.addWidget(QLabel("<b>Archivio Preghiere</b>"))

        filters_layout = QHBoxLayout()
        self.le_table_search = QLineEdit()
        self.le_table_search.setPlaceholderText("Cerca in tipo, brano, autore...")
        self.le_table_search.textChanged.connect(self._apply_table_filters)
        self.combo_table_type = QComboBox()
        self.combo_table_type.addItem("Tutti i tipi", "")
        self.combo_table_type.currentIndexChanged.connect(self._apply_table_filters)
        self.date_filter_from = QDateEdit()
        self.date_filter_from.setCalendarPopup(True)
        self.date_filter_from.setDisplayFormat("yyyy-MM-dd")
        self.date_filter_from.setDate(QDate(1900, 1, 1))
        self.date_filter_from.dateChanged.connect(self._apply_table_filters)
        self.date_filter_to = QDateEdit()
        self.date_filter_to.setCalendarPopup(True)
        self.date_filter_to.setDisplayFormat("yyyy-MM-dd")
        self.date_filter_to.setDate(QDate.currentDate())
        self.date_filter_to.dateChanged.connect(self._apply_table_filters)
        self.btn_reset_filters = QPushButton("Reset filtri")
        self.btn_reset_filters.clicked.connect(self._reset_table_filters)
        self.lbl_table_count = QLabel("0 righe")
        filters_layout.addWidget(self.le_table_search, 2)
        filters_layout.addWidget(self.combo_table_type)
        filters_layout.addWidget(QLabel("Dal"))
        filters_layout.addWidget(self.date_filter_from)
        filters_layout.addWidget(QLabel("Al"))
        filters_layout.addWidget(self.date_filter_to)
        filters_layout.addWidget(self.btn_reset_filters)
        filters_layout.addStretch()
        filters_layout.addWidget(self.lbl_table_count)
        table_layout.addLayout(filters_layout)

        table_layout.addWidget(self.table)
        t_btn_layout = QHBoxLayout()
        t_btn_layout.addStretch()
        t_btn_layout.addWidget(self.btn_delete)
        table_layout.addLayout(t_btn_layout)
        
        splitter.addWidget(form_widget)
        splitter.addWidget(table_widget)
        splitter.setSizes([400, 300])
        main_layout.addWidget(splitter)
        
    def _on_fetch_cei(self):
        reference = self.le_scripture_ref.text().strip()
        if not reference: return
        self.te_scripture_text.setHtml("<i>Ricerca in corso...</i>")
        self.btn_fetch_cei.setEnabled(False)
        try:
            text = fetch_cei_text(reference)
            self.te_scripture_text.setPlainText(text)
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile recuperare il testo:\n{e}")
        finally:
            self.btn_fetch_cei.setEnabled(True)

    def _on_save_prayer(self):
        date_str = self.date_edit.date().toString("yyyy-MM-dd")
        p_type = self.combo_type.currentText().strip()
        ref = self.le_scripture_ref.text().strip()
        s_text = self.te_scripture_text.toPlainText().strip()
        author = self.le_author.text().strip()
        meditation = self.te_meditation.toPlainText().strip()
        if not p_type or not meditation:
            QMessageBox.warning(self, "Attenzione", "Il tipo di preghiera e il testo della meditazione sono obbligatori.")
            return
        try:
            self.db.add_prayer(date_str, p_type, ref, s_text, author, meditation)
            self._clear_form()
            self.load_table_data()
        except Exception as e:
            QMessageBox.critical(self, "Errore Database", f"Impossibile salvare:\n{e}")

    def _clear_form(self):
        self.current_prayer_id = None
        self.current_prayer_data = None
        self.date_edit.setDate(QDate.currentDate())
        self.combo_type.setCurrentIndex(0)
        self.le_scripture_ref.clear()
        self.te_scripture_text.clear()
        self.le_author.clear()
        self.te_meditation.clear()
        self.btn_adjust.setEnabled(False)

    def load_table_data(self):
        self.table.setRowCount(0)
        # Carica solo preghiere con status != 'ESCLUSO'
        self._all_prayers = self.db.get_prayers_by_status()
        self._refresh_type_filter()
        self._apply_table_filters()

    def _refresh_type_filter(self):
        current = self.combo_table_type.currentData() if hasattr(self, "combo_table_type") else ""
        types = sorted({(p.get("prayer_type") or "").strip() for p in self._all_prayers if (p.get("prayer_type") or "").strip()})
        self.combo_table_type.blockSignals(True)
        self.combo_table_type.clear()
        self.combo_table_type.addItem("Tutti i tipi", "")
        for prayer_type in types:
            self.combo_table_type.addItem(prayer_type, prayer_type)
        idx = self.combo_table_type.findData(current)
        self.combo_table_type.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_table_type.blockSignals(False)

    def _apply_table_filters(self):
        search_text = self.le_table_search.text().strip().lower() if hasattr(self, "le_table_search") else ""
        selected_type = self.combo_table_type.currentData() if hasattr(self, "combo_table_type") else ""
        date_from = self.date_filter_from.date().toString("yyyy-MM-dd") if hasattr(self, "date_filter_from") else "1900-01-01"
        date_to = self.date_filter_to.date().toString("yyyy-MM-dd") if hasattr(self, "date_filter_to") else "2999-12-31"
        visible_prayers = []
        for p in self._all_prayers:
            p_date = p.get("date", "")
            if p_date < date_from or p_date > date_to:
                continue
            p_type = (p.get("prayer_type") or "").strip()
            if selected_type and p_type != selected_type:
                continue
            combined = " ".join([
                p_type,
                p.get("scripture_ref") or "",
                p.get("meditation_author") or ""
            ]).lower()
            if search_text and search_text not in combined:
                continue
            visible_prayers.append(p)

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(visible_prayers))
        from PyQt5.QtGui import QColor
        for row, p in enumerate(visible_prayers):
            items = [
                QTableWidgetItem(str(p["id"])),
                QTableWidgetItem(p["date"]),
                QTableWidgetItem(p["prayer_type"]),
                QTableWidgetItem(p["scripture_ref"]),
                QTableWidgetItem(p["meditation_author"])
            ]
            is_adj = p.get("manual_adjustment", 0) == 1
            for col, item in enumerate(items):
                if is_adj:
                    item.setBackground(QColor("#e0f2fe"))
                self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True)
        self.lbl_table_count.setText(f"{len(visible_prayers)} / {len(self._all_prayers)} righe")

    def _reset_table_filters(self):
        self.le_table_search.clear()
        self.combo_table_type.setCurrentIndex(0)
        self.date_filter_from.setDate(QDate(1900, 1, 1))
        self.date_filter_to.setDate(QDate.currentDate())
        self._apply_table_filters()

    def _on_table_selection(self):
        selected = self.table.selectedItems()
        if not selected:
            return
        row = selected[0].row()
        p_id_item = self.table.item(row, 0)
        if not p_id_item:
            return
        p_id = int(p_id_item.text())
        prayer = self.db.get_prayer(p_id)
        if prayer:
            self.current_prayer_id = p_id
            self.current_prayer_data = prayer
            self.date_edit.setDate(QDate.fromString(prayer["date"], "yyyy-MM-dd"))
            self.combo_type.setCurrentText(prayer["prayer_type"])
            self.le_scripture_ref.setText(prayer["scripture_ref"])
            self.te_scripture_text.setPlainText(prayer["scripture_text"])
            self.le_author.setText(prayer["meditation_author"])
            self.te_meditation.setPlainText(prayer["meditation_text"])
            
            # Abilita aggiustamento solo se c'è il transcript completo
            self.btn_adjust.setEnabled(prayer.get("full_data_json") is not None)

    def _on_adjust_meditation(self):
        if not self.current_prayer_data:
            return
            
        dialog = MeditationAdjustDialog(self.current_prayer_data, self)
        if dialog.exec_() == QDialog.Accepted:
            new_start = dialog.start_spin.value()
            new_end = dialog.end_spin.value()
            new_text = dialog.get_meditation_text()
            
            # Aggiorna DB
            self.db.update_prayer_bounds(self.current_prayer_id, new_start, new_end, new_text)
            # Ricarica UI
            self.te_meditation.setPlainText(new_text)
            self.current_prayer_data["meditation_text"] = new_text
            self.current_prayer_data["video_start"] = new_start
            self.current_prayer_data["video_end"] = new_end
            
            # Tenta ricalibrazione automatica dopo 10 inserimenti
            self._try_auto_recalibrate()
            
            QMessageBox.information(self, "Successo", "Porzione meditazione aggiornata!")

    def _try_auto_recalibrate(self):
        """Analizza le ultime 10 preghiere per trovare uno scarto medio e migliorare l'Agente."""
        prayers = self.db.get_prayers_by_status()  # esclude ESCLUSO
        if len(prayers) < 5: # iniziamo con 5 per dare feedback subito
            return
            
        total_offset = 0.0
        count = 0
        
        # Analizziamo le preghiere per cui abbiamo il dato originale ricalcolato
        # In questa versione semplificata, memorizziamo lo scarto tra video_start (utente) 
        # e quello che l'IA avrebbe trovato (basato sui marker nel JSON)
        for p in prayers[:10]:
            v_start = p.get("video_start")
            json_str = p.get("full_data_json")
            if v_start is not None and json_str:
                try:
                    segments = json.loads(json_str)
                    # Tenta di rifare il rilevamento "grezzo" (senza offset)
                    import re
                    start_regex = re.compile(r'(parola del signore|vangelo del signore|parola di dio|parola di salvezza|lode a te o cristo|rendiamo grazie a dio)', re.IGNORECASE)
                    raw_start = 0.0
                    for s in segments:
                        if s["start"] > 1080: break
                        if start_regex.search(s["text"]):
                            raw_start = s["end"]
                    
                    if raw_start > 0:
                        total_offset += (v_start - raw_start)
                        count += 1
                except: continue
        
        if count >= 3:
            avg_offset = total_offset / count
            self.settings.calibration_start_offset = avg_offset
            # Non mostriamo un popup ogni volta, per non disturbare, ma logghiamo
            print(f"[Calibrazione] Nuovo offset medio calcolato: {avg_offset:.2f}s")

    def _on_delete_prayer(self):
        selected = self.table.selectedItems()
        if not selected: return
        row = selected[0].row()
        p_id = int(self.table.item(row, 0).text())
        if QMessageBox.question(self, "Conferma", f"Eliminare ID {p_id}?") == QMessageBox.Yes:
            self.db.delete_prayer(p_id)
            self.load_table_data()

    def _on_launch_agent(self):
        opt = AgentOptionsDialog(self)
        if opt.exec_() != QDialog.Accepted:
            return
            
        count = opt.get_count()
        dlg = AgentLogDialog(self)
        self.agent_worker = PrayerAgentWorker(max_videos=count, parent=self)
        self.agent_worker.status_message.connect(dlg.status_label.setText)
        self.agent_worker.log_message.connect(dlg.append_log)
        self.agent_worker.finished.connect(lambda c: self._on_agent_finished(dlg, c))
        self.agent_worker.error.connect(lambda e: self._on_agent_error(dlg, e))
        dlg.rejected.connect(self.agent_worker.abort)
        self.agent_worker.start()
        dlg.exec_()

    def _on_agent_finished(self, dlg, count):
        self.load_table_data()
        QMessageBox.information(self, "Agente", f"Fatto! Preghiere aggiunte: {count}")
        dlg.accept()

    def _on_agent_error(self, dlg, err):
        QMessageBox.critical(self, "Errore", err)
        dlg.reject()

    def start_agent_manual(self, video_list):
        """Avvia l'agente su una lista specifica di video (proveniente dall'Archivio Video)."""
        if not video_list:
            return
            
        dlg = AgentLogDialog(self)
        # Inizializza il worker con la lista manuale
        self.agent_worker = PrayerAgentWorker(manual_videos=video_list, parent=self)
        
        self.agent_worker.status_message.connect(dlg.status_label.setText)
        self.agent_worker.log_message.connect(dlg.append_log)
        self.agent_worker.finished.connect(lambda c: self._on_agent_finished(dlg, c))
        self.agent_worker.error.connect(lambda e: self._on_agent_error(dlg, e))
        dlg.rejected.connect(self.agent_worker.abort)
        
        # Sposta l'utente su questo tab per vedere il progresso
        self.window().tabs.setCurrentIndex(2) 
        
        self.agent_worker.start()
        dlg.exec_()

class MeditationAdjustDialog(QDialog):
    def __init__(self, prayer_data, parent=None):
        super().__init__(parent)
        self.prayer_data = prayer_data
        try:
            self.segments = json.loads(prayer_data["full_data_json"])
        except:
            self.segments = []
        
        # Mappa per trovare rapidamente i segmenti dai caratteri (indicativo)
        self.char_map = [] 
        
        self.setWindowTitle("📏 Aggiusta Porzione Meditazione")
        self.resize(1000, 700)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        info = QLabel(f"<b>Istruzioni:</b> Trascina gli slider o <b>clicca col tasto destro</b> sulle parole del testo per fissare i punti!")
        info.setStyleSheet("color: #2a5cbf; padding: 5px; background: #eef2ff; border-radius: 4px;")
        layout.addWidget(info)
        
        # Transcript visualizer (INTERATTIVO)
        self.text_preview = QTextEdit()
        self.text_preview.setReadOnly(True)
        self.text_preview.setContextMenuPolicy(Qt.CustomContextMenu)
        self.text_preview.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.text_preview)
        
        # Controls
        controls = QGroupBox("Limiti Temporali (Secondi)")
        c_layout = QFormLayout(controls)
        
        max_time = 3600
        if self.segments:
            max_time = self.segments[-1]["end"]
            
        # Slider Inizio
        self.slider_start = QSlider(Qt.Horizontal)
        self.slider_start.setRange(0, int(max_time))
        self.slider_start.setValue(int(self.prayer_data.get("video_start", 0)))
        self.slider_start.valueChanged.connect(self._on_slider_start_changed)
        
        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(0, max_time)
        self.start_spin.setValue(self.prayer_data.get("video_start", 0))
        self.start_spin.setSingleStep(1.0)
        self.start_spin.valueChanged.connect(self._on_spin_start_changed)
        
        # Slider Fine
        self.slider_end = QSlider(Qt.Horizontal)
        self.slider_end.setRange(0, int(max_time))
        self.slider_end.setValue(int(self.prayer_data.get("video_end", max_time)))
        self.slider_end.valueChanged.connect(self._on_slider_end_changed)

        self.end_spin = QDoubleSpinBox()
        self.end_spin.setRange(0, max_time)
        self.end_spin.setValue(self.prayer_data.get("video_end", max_time))
        self.end_spin.setSingleStep(1.0)
        self.end_spin.valueChanged.connect(self._on_spin_end_changed)
        
        c_layout.addRow("Inizio Meditazione:", self.slider_start)
        c_layout.addRow("", self.start_spin)
        c_layout.addRow("Fine Meditazione:", self.slider_end)
        c_layout.addRow("", self.end_spin)
        layout.addWidget(controls)
        
        btns = QHBoxLayout()
        btn_ok = QPushButton("Applica Modifiche")
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("Annulla")
        btn_cancel.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        layout.addLayout(btns)
        
        self._update_preview()

    def _on_slider_start_changed(self, val):
        self.start_spin.blockSignals(True)
        self.start_spin.setValue(float(val))
        self.start_spin.blockSignals(False)
        self._update_preview()

    def _on_spin_start_changed(self, val):
        self.slider_start.blockSignals(True)
        self.slider_start.setValue(int(val))
        self.slider_start.blockSignals(False)
        self._update_preview()

    def _on_slider_end_changed(self, val):
        self.end_spin.blockSignals(True)
        self.end_spin.setValue(float(val))
        self.end_spin.blockSignals(False)
        self._update_preview()

    def _on_spin_end_changed(self, val):
        self.slider_end.blockSignals(True)
        self.slider_end.setValue(int(val))
        self.slider_end.blockSignals(False)
        self._update_preview()

    def _update_preview(self):
        start = self.start_spin.value()
        end = self.end_spin.value()
        
        full_html = ""
        current_pos = 0
        self.char_map = []
        
        for i, s in enumerate(self.segments):
            text = s["text"]
            # Registriamo la posizione del segmento nell'HTML (approssimata)
            token = f"seg_{i}"
            
            color = "#64748b" # Grigio scuro
            bg = "transparent"
            weight = "normal"
            
            if s["start"] >= start and s["end"] <= end:
                color = "#166534" # Verde scuro
                bg = "#dcfce7"   # Verde chiaro
                weight = "bold"
            
            segment_html = f"<span id='{token}' style='background-color:{bg}; color:{color}; font-weight:{weight};'>{text}</span> "
            full_html += segment_html
        
        self.text_preview.setHtml(full_html)

    def _show_context_menu(self, pos):
        """Mostra menu per impostare inizio/fine basandosi sulla parola cliccata."""
        cursor = self.text_preview.cursorForPosition(pos)
        # Cerchiamo il segmento che corrisponde a questa posizione
        # Dato che l'HTML rende difficile mappare i caratteri, usiamo un trucco:
        # Troviamo la parola sotto il cursore e cerchiamola nei segmenti (vicino al minutaggio attuale)
        word = cursor.block().text()
        
        # Metodo più affidabile: usiamo l'indice del carattere nel documento
        char_idx = cursor.position()
        
        # Calcoliamo a quale segmento appartiene char_idx
        # Ricostruiamo il testo piano per mappare gli indici
        plain_text = ""
        seg_indices = []
        for s in self.segments:
            start_idx = len(plain_text)
            plain_text += s["text"] + " "
            end_idx = len(plain_text)
            seg_indices.append((start_idx, end_idx, s))
            
        target_seg = None
        for start, end, s in seg_indices:
            if start <= char_idx <= end:
                target_seg = s
                break
                
        if not target_seg: return

        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self)
        act_start = menu.addAction(f"Inizia qui ({int(target_seg['start'])}s)")
        act_end = menu.addAction(f"Finisci qui ({int(target_seg['end'])}s)")
        
        action = menu.exec_(self.text_preview.mapToGlobal(pos))
        if action == act_start:
            self.start_spin.setValue(target_seg["start"])
        elif action == act_end:
            self.end_spin.setValue(target_seg["end"])

    def get_meditation_text(self):
        start = self.start_spin.value()
        end = self.end_spin.value()
        pieces = [s["text"] for s in self.segments if s["start"] >= start and s["end"] <= end]
        return " ".join(pieces).strip()
