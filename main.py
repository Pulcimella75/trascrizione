"""
main.py
Entry point dell'applicazione di trascrizione.
Avvio: python main.py
"""

import sys
import os
from pathlib import Path

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont, QFontDatabase
from PyQt5.QtCore import Qt

# Aggiungi la root del progetto al path per import assoluti
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import AppSettings
from core.logger import setup_logging
from ui.main_window import MainWindow


def load_stylesheet(app: QApplication) -> None:
    qss_path = Path(__file__).parent / "assets" / "style.qss"
    if qss_path.exists():
        with open(qss_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())


def main():
    # Fix per crash di ctranslate2 (faster-whisper) all'interno dei QThread su Windows
    # Questo previene il blocco improvviso senza errori durante il caricamento del modello
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
    os.environ["CT2_USE_EXPERIMENTAL_PACKED_GEMM"] = "0"
    
    # Inizializza Logging
    setup_logging()

    # Abilita Hi-DPI su Windows
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("Trascrizione Audio & Video")
    app.setOrganizationName("Trascrizione")

    # Font di sistema
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    # Tema dark
    load_stylesheet(app)

    # Inizializzazione impostazioni
    settings = AppSettings()
    settings.ensure_dirs()

    # Finestra principale
    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
