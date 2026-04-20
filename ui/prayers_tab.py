import sys
from datetime import datetime

from PyQt5.QtCore import Qt, QDate, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, 
    QLineEdit, QTextEdit, QPushButton, QComboBox, 
    QDateEdit, QTableWidget, QTableWidgetItem, 
    QMessageBox, QSplitter, QLabel, QHeaderView,
    QGroupBox, QDialog, QPlainTextEdit, QProgressBar,
    QSpinBox, QDoubleSpinBox
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
        self.table.itemSelectionChanged.connect(self._on_table_selection)
        self.btn_delete = QPushButton("🗑 Elimina Selezionata")
        self.btn_delete.clicked.connect(self._on_delete_prayer)
        table_layout.addWidget(QLabel("<b>Archivio Preghiere</b>"))
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
        self.date_edit.setDate(QDate.currentDate())
        self.le_scripture_ref.clear()
        self.te_scripture_text.clear()
        self.le_author.clear()
        self.te_meditation.clear()

    def load_table_data(self):
        self.table.setRowCount(0)
        prayers = self.db.get_all_prayers()
        self.table.setRowCount(len(prayers))
        for row, p in enumerate(prayers):
            self.table.setItem(row, 0, QTableWidgetItem(str(p["id"])))
            self.table.setItem(row, 1, QTableWidgetItem(p["date"]))
            self.table.setItem(row, 2, QTableWidgetItem(p["prayer_type"]))
            self.table.setItem(row, 3, QTableWidgetItem(p["scripture_ref"]))
            self.table.setItem(row, 4, QTableWidgetItem(p["meditation_author"]))

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
        if dialog.exec() == QDialog.DialogCode.Accepted:
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
            QMessageBox.information(self, "Successo", "Porzione meditazione aggiornata!")

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
