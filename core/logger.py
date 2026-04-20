"""
core/logger.py
Sistema di logging centralizzato per l'applicazione.
Salva i log in 'debug.log' e li stampa in console.
"""

import logging
import os
import sys
from pathlib import Path

# Percorso del file log nella root del progetto
LOG_FILE = Path(__file__).parent.parent / "debug.log"

def setup_logging():
    """Inizializza il logger globale."""
    logger = logging.getLogger("TrascrizioneApp")
    logger.setLevel(logging.DEBUG)

    # Formato: [DATA ORA] [LIVELLO] [MODULO] Messaggio
    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Handler per file (sovrascrive a ogni avvio per non accumulare GB)
    file_handler = logging.FileHandler(LOG_FILE, mode='w', encoding='utf-8')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    # Handler per console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    logger.info("Sistema di logging inizializzato.")
    logger.info(f"File log: {LOG_FILE}")
    return logger

def get_logger(module_name: str):
    """Restituisce un sotto-logger per un modulo specifico."""
    return logging.getLogger(f"TrascrizioneApp.{module_name}")
