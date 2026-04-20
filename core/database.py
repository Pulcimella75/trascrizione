import sqlite3
import os
from datetime import datetime
from core.logger import get_logger

logger = get_logger("Database")

class PrayerDatabase:
    """Gestisce il salvataggio delle preghiere su SQLite."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()
        
    def _get_connection(self):
        return sqlite3.connect(self.db_path)
        
    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS prayers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT,
                    prayer_type TEXT,
                    scripture_ref TEXT,
                    scripture_text TEXT,
                    meditation_author TEXT,
                    meditation_text TEXT,
                    video_id TEXT
                )
            ''')
            
            # Migrazione: verifica se la colonna video_id esiste
            cursor.execute("PRAGMA table_info(prayers)")
            columns = [column[1] for column in cursor.fetchall()]
            
            if 'video_id' not in columns:
                try:
                    cursor.execute("ALTER TABLE prayers ADD COLUMN video_id TEXT")
                    logger.info("Aggiunta colonna video_id alla tabella prayers.")
                except sqlite3.OperationalError as e:
                    logger.error(f"Errore durante l'aggiunta della colonna video_id: {e}")
            
            # Crea un indice unico per video_id per garantire l'integrità e velocizzare le ricerche
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_prayers_video_id ON prayers(video_id)")
            
            conn.commit()

    def add_prayer(self, date: str, prayer_type: str, scripture_ref: str, 
                   scripture_text: str, author: str, meditation: str, video_id: str = None) -> int:
        """Aggiunge una nuova preghiera al db e restituisce il suo id."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO prayers (date, prayer_type, scripture_ref, scripture_text, meditation_author, meditation_text, video_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (date, prayer_type, scripture_ref, scripture_text, author, meditation, video_id))
            conn.commit()
            return cursor.lastrowid

    def is_video_processed(self, video_id: str) -> bool:
        """Verifica se un video è già stato elaborato."""
        if not video_id:
            return False
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT 1 FROM prayers WHERE video_id = ?', (video_id,))
            return cursor.fetchone() is not None

    def get_all_prayers(self) -> list:
        """Restituisce tutte le preghiere sotto forma di lista di dizionari, ordinate per data decrescente."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM prayers ORDER BY date DESC, id DESC')
            return [dict(row) for row in cursor.fetchall()]
            
    def get_prayer(self, prayer_id: int):
        """Restituisce una preghiera dato il suo ID."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM prayers WHERE id = ?', (prayer_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_prayer(self, prayer_id: int):
        """Elimina una preghiera dal db per ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM prayers WHERE id = ?', (prayer_id,))
            conn.commit()
