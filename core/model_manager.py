"""
core/model_manager.py
Scarica e gestisce i modelli faster-whisper.
Usa il metodo nativo per garantire integrità del download su Windows.
"""

import os
import shutil
from pathlib import Path
from PyQt5.QtCore import QThread, pyqtSignal

# Mappa modelli compatibili
AVAILABLE_MODELS = {
    "tiny":           "tiny",
    "base":           "base",
    "small":          "small",
    "medium":         "medium",
    "large-v2":       "large-v2",
    "large-v3":       "large-v3",
    "large-v3-turbo": "large-v3-turbo",
}

MODEL_SIZES_MB = {
    "tiny":           39,
    "base":           74,
    "small":          244,
    "medium":         769,
    "large-v2":       1500,
    "large-v3":       1550,
    "large-v3-turbo": 809,
}

def get_local_models(model_dir: str) -> list[str]:
    """Restituisce i nomi dei modelli integri e pronti all'uso."""
    if not os.path.isdir(model_dir):
        return []
    found = []
    for name in AVAILABLE_MODELS:
        # Percorso standard creato da download_model
        model_path = os.path.join(model_dir, name)
        bin_path = os.path.join(model_path, "model.bin")
        if os.path.isdir(model_path) and os.path.isfile(bin_path):
            if os.path.getsize(bin_path) > 10 * 1024 * 1024:
                found.append(name)
    return found

class ModelDownloaderWorker(QThread):
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, model_name: str, model_dir: str, parent=None):
        super().__init__(parent)
        self.model_name = model_name
        self.model_dir = model_dir

    def run(self):
        try:
            from faster_whisper.utils import download_model
            
            os.makedirs(self.model_dir, exist_ok=True)
            self.status.emit(f"Inizializzazione download {self.model_name}...")
            self.progress.emit(5)
            
            # Utilizziamo il path specifico per il modello
            output_dir = os.path.join(self.model_dir, self.model_name)
            
            # Il metodo download_model di faster-whisper è il più affidabile
            # perché verifica i checksum automaticamente.
            download_model(
                self.model_name,
                output_dir=output_dir,
            )
            
            self.progress.emit(100)
            self.status.emit(f"Modello {self.model_name} pronto.")
            self.finished.emit(self.model_name)
            
        except Exception as e:
            # Pulisci in caso di errore per evitare stati inconsistenti
            dest = os.path.join(self.model_dir, self.model_name)
            if os.path.isdir(dest):
                shutil.rmtree(dest, ignore_errors=True)
            self.error.emit(f"Errore download: {str(e)}")

class ModelDeleter(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, model_name: str, model_dir: str, parent=None):
        super().__init__(parent)
        self.model_name = model_name
        self.model_dir = model_dir

    def run(self):
        path = Path(self.model_dir) / self.model_name
        try:
            if path.is_dir():
                shutil.rmtree(path)
            self.finished.emit(self.model_name)
        except Exception as e:
            self.error.emit(str(e))
