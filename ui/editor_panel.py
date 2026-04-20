"""
ui/editor_panel.py
Pannello editor rich-text per il testo trascritto.
Supporta formattazione (grassetto, corsivo, sottolineato, allineamento,
dimensione font, intestazioni) e salvataggio TXT/DOCX.
"""

import os
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import (
    QFont, QTextCharFormat, QTextCursor, QColor,
    QTextBlockFormat, QKeySequence,
)
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QToolBar, QAction,
    QTextEdit, QPushButton, QLabel, QComboBox, QSpinBox,
    QFileDialog, QMessageBox, QSizePolicy, QInputDialog,
    QGroupBox,
)

from config.settings import AppSettings
from core.exporter import export_txt, export_docx


class FormattingToolbar(QToolBar):
    """Toolbar di formattazione per il QTextEdit."""

    def __init__(self, editor: QTextEdit, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setMovable(False)
        self._building = False
        self._build()
        self.editor.currentCharFormatChanged.connect(self._sync_format)
        self.editor.cursorPositionChanged.connect(self._sync_block_format)

    def _build(self):
        # ── Stile paragrafo ───────────────────────────────────────────────
        self.combo_style = QComboBox()
        self.combo_style.setFixedWidth(140)
        self.combo_style.addItems([
            "Testo normale", "Titolo 1", "Titolo 2", "Titolo 3",
        ])
        self.combo_style.currentIndexChanged.connect(self._apply_heading)
        self.addWidget(self.combo_style)
        self.addSeparator()

        # ── Font family ───────────────────────────────────────────────────
        self.combo_font = QComboBox()
        self.combo_font.setFixedWidth(130)
        self.combo_font.addItems([
            "Segoe UI", "Arial", "Times New Roman", "Courier New",
            "Georgia", "Verdana", "Calibri",
        ])
        self.combo_font.currentTextChanged.connect(self._apply_font_family)
        self.addWidget(self.combo_font)

        # ── Font size ─────────────────────────────────────────────────────
        self.spin_size = QSpinBox()
        self.spin_size.setFixedWidth(56)
        self.spin_size.setRange(6, 96)
        self.spin_size.setValue(12)
        self.spin_size.valueChanged.connect(self._apply_font_size)
        self.addWidget(self.spin_size)
        self.addSeparator()

        # ── Bold / Italic / Underline ─────────────────────────────────────
        self.act_bold = QAction("B", self)
        self.act_bold.setCheckable(True)
        self.act_bold.setShortcut(QKeySequence.Bold)
        self.act_bold.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.act_bold.triggered.connect(self._toggle_bold)
        self.addAction(self.act_bold)

        self.act_italic = QAction("I", self)
        self.act_italic.setCheckable(True)
        self.act_italic.setShortcut(QKeySequence.Italic)
        f = QFont("Segoe UI", 11)
        f.setItalic(True)
        self.act_italic.setFont(f)
        self.act_italic.triggered.connect(self._toggle_italic)
        self.addAction(self.act_italic)

        self.act_underline = QAction("U", self)
        self.act_underline.setCheckable(True)
        self.act_underline.setShortcut(QKeySequence.Underline)
        self.act_underline.triggered.connect(self._toggle_underline)
        self.addAction(self.act_underline)
        self.addSeparator()

        # ── Allineamento ──────────────────────────────────────────────────
        self.act_align_left    = QAction("⬛L", self)
        self.act_align_center  = QAction("⬛C", self)
        self.act_align_right   = QAction("⬛R", self)
        self.act_align_justify = QAction("⬛J", self)

        for act, tooltip, align in [
            (self.act_align_left,    "Allinea a sinistra",  Qt.AlignLeft),
            (self.act_align_center,  "Centra",              Qt.AlignHCenter),
            (self.act_align_right,   "Allinea a destra",    Qt.AlignRight),
            (self.act_align_justify, "Giustifica",          Qt.AlignJustify),
        ]:
            act.setCheckable(True)
            act.setToolTip(tooltip)
            act.setData(align)
            act.triggered.connect(self._apply_alignment)
            self.addAction(act)

        self._align_actions = [
            self.act_align_left, self.act_align_center,
            self.act_align_right, self.act_align_justify,
        ]
        self.addSeparator()

        # ── Colore testo ──────────────────────────────────────────────────
        self.act_color = QAction("🎨 Colore", self)
        self.act_color.triggered.connect(self._pick_color)
        self.addAction(self.act_color)

        # ── Cerca/Sostituisci ─────────────────────────────────────────────
        self.addSeparator()
        self.act_find = QAction("🔍 Cerca", self)
        self.act_find.setShortcut(QKeySequence.Find)
        self.act_find.triggered.connect(self._find_replace)
        self.addAction(self.act_find)

    # ── Applicazione formato ───────────────────────────────────────────────

    def _apply_heading(self, index: int):
        if self._building:
            return
        cursor = self.editor.textCursor()
        sizes = [12, 22, 18, 15]
        weights = [QFont.Normal, QFont.Bold, QFont.Bold, QFont.Bold]
        fmt = QTextCharFormat()
        fmt.setFontPointSize(sizes[index])
        fmt.setFontWeight(weights[index])
        cursor.mergeCharFormat(fmt)
        self.editor.mergeCurrentCharFormat(fmt)

    def _apply_font_family(self, family: str):
        if self._building:
            return
        fmt = QTextCharFormat()
        fmt.setFontFamily(family)
        self.editor.mergeCurrentCharFormat(fmt)

    def _apply_font_size(self, size: int):
        if self._building:
            return
        fmt = QTextCharFormat()
        fmt.setFontPointSize(size)
        self.editor.mergeCurrentCharFormat(fmt)

    def _toggle_bold(self, checked: bool):
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Bold if checked else QFont.Normal)
        self.editor.mergeCurrentCharFormat(fmt)

    def _toggle_italic(self, checked: bool):
        fmt = QTextCharFormat()
        fmt.setFontItalic(checked)
        self.editor.mergeCurrentCharFormat(fmt)

    def _toggle_underline(self, checked: bool):
        fmt = QTextCharFormat()
        fmt.setFontUnderline(checked)
        self.editor.mergeCurrentCharFormat(fmt)

    def _apply_alignment(self):
        action = self.sender()
        align = action.data()
        self.editor.setAlignment(align)
        for act in self._align_actions:
            act.setChecked(act is action)

    def _pick_color(self):
        from PyQt5.QtWidgets import QColorDialog
        color = QColorDialog.getColor(
            self.editor.textColor(), self.editor, "Scegli colore testo")
        if color.isValid():
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            self.editor.mergeCurrentCharFormat(fmt)

    def _find_replace(self):
        from PyQt5.QtWidgets import QDialog, QFormLayout, QDialogButtonBox
        dlg = QDialog(self.editor)
        dlg.setWindowTitle("Cerca e Sostituisci")
        dlg.setMinimumWidth(360)
        form = QFormLayout(dlg)
        from PyQt5.QtWidgets import QLineEdit
        find_edit    = QLineEdit()
        replace_edit = QLineEdit()
        form.addRow("Cerca:", find_edit)
        form.addRow("Sostituisci con:", replace_edit)
        btns = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec_() == QDialog.Accepted:
            text = self.editor.toPlainText()
            new_text = text.replace(find_edit.text(), replace_edit.text())
            if new_text != text:
                # mantieni HTML ma sostituisci nel testo plain
                html = self.editor.toHtml()
                html = html.replace(find_edit.text(), replace_edit.text())
                self.editor.setHtml(html)

    # ── Sincronizzazione stato ─────────────────────────────────────────────

    def _sync_format(self, fmt: QTextCharFormat):
        self._building = True
        self.act_bold.setChecked(fmt.fontWeight() >= QFont.Bold)
        self.act_italic.setChecked(fmt.fontItalic())
        self.act_underline.setChecked(fmt.fontUnderline())
        size = fmt.fontPointSize()
        if size > 0:
            self.spin_size.setValue(int(size))
        family = fmt.fontFamily()
        idx = self.combo_font.findText(family)
        if idx >= 0:
            self.combo_font.setCurrentIndex(idx)
        self._building = False

    def _sync_block_format(self):
        self._building = True
        align = self.editor.alignment()
        for act in self._align_actions:
            act.setChecked(act.data() == align)
        self._building = False


class EditorPanel(QWidget):
    """
    Pannello editor testo trascritto con toolbar di formattazione.

    Segnali:
        saved(str)   percorso file salvato
    """

    saved = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = AppSettings()
        self._current_source: str = ""
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Editor
        self.editor = QTextEdit()
        self.editor.setAcceptRichText(True)
        self.editor.setPlaceholderText(
            "Il testo trascritto apparirà qui.\n"
            "Puoi modificarlo e formattarlo liberamente."
        )

        # Toolbar sopra l'editor
        self.toolbar = FormattingToolbar(self.editor)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.editor)

        # Barra salvataggio
        save_bar = QGroupBox()
        save_bar.setFlat(True)
        save_layout = QHBoxLayout(save_bar)
        save_layout.setContentsMargins(8, 6, 8, 6)

        self.lbl_source = QLabel("Nessun file caricato")
        self.lbl_source.setStyleSheet("color: #5a6080; font-size: 12px;")
        save_layout.addWidget(self.lbl_source)
        save_layout.addStretch()

        self.btn_save_txt = QPushButton("💾  Salva TXT")
        self.btn_save_txt.setObjectName("btn_flat")
        self.btn_save_txt.clicked.connect(self._save_txt)

        self.btn_save_docx = QPushButton("📄  Salva DOCX")
        self.btn_save_docx.clicked.connect(self._save_docx)

        self.btn_clear = QPushButton("🗑  Pulisci")
        self.btn_clear.setObjectName("btn_flat")
        self.btn_clear.clicked.connect(self._clear)

        save_layout.addWidget(self.btn_save_txt)
        save_layout.addWidget(self.btn_save_docx)
        save_layout.addWidget(self.btn_clear)
        layout.addWidget(save_bar)

    # ── API pubblica ───────────────────────────────────────────────────────

    def append_text(self, text: str):
        """Aggiunge testo al fondo dell'editor."""
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.End)
        # Aggiungi uno spazio tra i segmenti
        if cursor.position() > 0:
            cursor.insertText(" ")
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()

    def set_text(self, text: str):
        """Imposta il testo completo (plain text)."""
        self.editor.setPlainText(text)

    def set_html(self, html: str):
        """Imposta il testo completo (HTML)."""
        self.editor.setHtml(html)

    def set_source(self, file_path: str):
        """Imposta il percorso del file sorgente corrente."""
        self._current_source = file_path
        name = os.path.basename(file_path) if file_path else "Nessun file"
        self.lbl_source.setText(f"Sorgente: {name}")

    def clear(self):
        self.editor.clear()
        self._current_source = ""
        self.lbl_source.setText("Nessun file caricato")

    # ── Salvataggio ───────────────────────────────────────────────────────

    def _default_name(self, ext: str) -> str:
        if self._current_source:
            stem = Path(self._current_source).stem
        else:
            stem = "trascrizione"
        return os.path.join(self._settings.output_dir, f"{stem}{ext}")

    def _save_txt(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Salva come TXT",
            self._default_name(".txt"),
            "Testo (*.txt)",
        )
        if not path:
            return
        try:
            saved = export_txt(self.editor.toHtml(), path)
            self._settings.set("last_output_dir", str(Path(saved).parent))
            self.saved.emit(saved)
            QMessageBox.information(self, "Salvato", f"File TXT salvato:\n{saved}")
        except Exception as e:
            QMessageBox.critical(self, "Errore", str(e))

    def _save_docx(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Salva come DOCX",
            self._default_name(".docx"),
            "Word Document (*.docx)",
        )
        if not path:
            return
        try:
            saved = export_docx(self.editor.toHtml(), path)
            self._settings.set("last_output_dir", str(Path(saved).parent))
            self.saved.emit(saved)
            QMessageBox.information(self, "Salvato", f"File DOCX salvato:\n{saved}")
        except Exception as e:
            QMessageBox.critical(self, "Errore", str(e))

    def _clear(self):
        reply = QMessageBox.question(
            self, "Pulisci editor",
            "Sei sicuro di voler cancellare il testo corrente?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.clear()
