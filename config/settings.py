"""
config/settings.py
Gestione persistente delle impostazioni dell'applicazione.
Salva e carica un file JSON nella directory dell'app.
"""

import json
import os
from pathlib import Path


_DEFAULT_SETTINGS = {
    "model_dir": str(Path.home() / "faster_whisper_models"),
    "output_dir": str(Path.home() / "Documents" / "Trascrizioni"),
    "temp_dir": str(Path.home() / "AppData" / "Local" / "Temp" / "trascrizione_app"),
    "default_model": "large-v2",
    "default_language": "auto",
    "custom_words": [],
    "cookies_file": "",       # percorso file cookies.txt per YouTube
    "last_output_dir": "",
    "last_model_dir": "",
    "window_geometry": None,
    "db_path": r"G:\Il mio Drive\Preghiere\prayers.db",
}

_SETTINGS_FILE = Path(__file__).parent.parent / "settings.json"


class AppSettings:
    """Singleton per la gestione delle impostazioni dell'applicazione."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._data = {}
            cls._instance._load()
        return cls._instance

    def _load(self):
        if _SETTINGS_FILE.exists():
            try:
                with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self._data = {**_DEFAULT_SETTINGS, **loaded}
            except (json.JSONDecodeError, OSError):
                self._data = dict(_DEFAULT_SETTINGS)
        else:
            self._data = dict(_DEFAULT_SETTINGS)

    def save(self):
        try:
            with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except OSError as e:
            print(f"[Settings] Errore salvataggio: {e}")

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value):
        self._data[key] = value
        self.save()

    # ── Shortcut properties ──────────────────────────────────────────────────

    @property
    def model_dir(self) -> str:
        return self._data["model_dir"]

    @model_dir.setter
    def model_dir(self, value: str):
        self._data["model_dir"] = value
        self.save()

    @property
    def output_dir(self) -> str:
        return self._data["output_dir"]

    @output_dir.setter
    def output_dir(self, value: str):
        self._data["output_dir"] = value
        self.save()

    @property
    def temp_dir(self) -> str:
        return self._data["temp_dir"]

    @temp_dir.setter
    def temp_dir(self, value: str):
        self._data["temp_dir"] = value
        self.save()

    @property
    def default_model(self) -> str:
        return self._data["default_model"]

    @default_model.setter
    def default_model(self, value: str):
        self._data["default_model"] = value
        self.save()

    @property
    def default_language(self) -> str:
        return self._data["default_language"]

    @default_language.setter
    def default_language(self, value: str):
        self._data["default_language"] = value
        self.save()

    @property
    def custom_words(self) -> list:
        return self._data.get("custom_words", [])

    @custom_words.setter
    def custom_words(self, value: list):
        self._data["custom_words"] = value
        self.save()

    @property
    def cookies_file(self) -> str:
        return self._data.get("cookies_file", "")

    @cookies_file.setter
    def cookies_file(self, value: str):
        self._data["cookies_file"] = value
        self.save()

    @property
    def db_path(self) -> str:
        return self._data.get("db_path", r"G:\Il mio Drive\Preghiere\prayers.db")

    @db_path.setter
    def db_path(self, value: str):
        self._data["db_path"] = value
        self.save()

    def ensure_dirs(self):
        """Crea le directory necessarie se non esistono."""
        for d in [self.model_dir, self.output_dir, self.temp_dir]:
            Path(d).mkdir(parents=True, exist_ok=True)
        # Assicurati anche che la directory del db esista
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
