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
                    video_id TEXT,
                    video_start REAL,
                    video_end REAL,
                    full_data_json TEXT,
                    manual_adjustment INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'TRASCRITTO'
                )
            ''')
            
            # Migrazione: verifica se le colonne esistono
            cursor.execute("PRAGMA table_info(prayers)")
            columns = [column[1] for column in cursor.fetchall()]
            
            new_cols = [
                ('video_id', 'TEXT'),
                ('video_start', 'REAL'),
                ('video_end', 'REAL'),
                ('full_data_json', 'TEXT'),
                ('manual_adjustment', 'INTEGER DEFAULT 0'),
                ('status', "TEXT DEFAULT 'TRASCRITTO'"),
            ]
            
            for col_name, col_type in new_cols:
                if col_name not in columns:
                    try:
                        cursor.execute(f"ALTER TABLE prayers ADD COLUMN {col_name} {col_type}")
                        logger.info(f"Aggiunta colonna {col_name} alla tabella prayers.")
                    except sqlite3.OperationalError as e:
                        logger.error(f"Errore aggiunta colonna {col_name}: {e}")
            
            # Imposta status='TRASCRITTO' per i record esistenti che ce l'hanno NULL
            cursor.execute("UPDATE prayers SET status = 'TRASCRITTO' WHERE status IS NULL")

            # Crea un indice unico per video_id
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_prayers_video_id ON prayers(video_id)")
            conn.commit()

    def add_prayer(self, date: str, prayer_type: str, scripture_ref: str, 
                   scripture_text: str, author: str, meditation: str, 
                   video_id: str = None, v_start: float = 0.0, v_end: float = 0.0, 
                   full_json: str = None) -> int:
        """Aggiunge una nuova preghiera al db e restituisce il suo id."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO prayers (date, prayer_type, scripture_ref, scripture_text, 
                                   meditation_author, meditation_text, video_id, 
                                   video_start, video_end, full_data_json, manual_adjustment)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            ''', (date, prayer_type, scripture_ref, scripture_text, author, meditation, 
                  video_id, v_start, v_end, full_json))
            conn.commit()
            return cursor.lastrowid

    def update_prayer_bounds(self, prayer_id: int, start: float, end: float, text: str):
        """Aggiorna i limiti temporali e il testo della meditazione per una preghiera esistente."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE prayers SET video_start = ?, video_end = ?, meditation_text = ?, manual_adjustment = 1
                WHERE id = ?
            ''', (start, end, text, prayer_id))
            conn.commit()

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

    def set_status(self, prayer_id: int, status: str):
        """Aggiorna lo status di una preghiera. Valori validi: TRASCRITTO, ESCLUSO."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE prayers SET status = ? WHERE id = ?', (status, prayer_id))
            conn.commit()

    def mark_excluded(self, video_id: str):
        """Marca un video come ESCLUSO nel DB (se già presente) o lo inserisce come escluso."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Se esiste già (trascritto per errore), aggiorna status
            cursor.execute('UPDATE prayers SET status = ? WHERE video_id = ?', ('ESCLUSO', video_id))
            if cursor.rowcount == 0:
                # Inserisce una riga-tombstone così is_video_processed() lo considera già visto
                cursor.execute(
                    '''INSERT OR IGNORE INTO prayers 
                       (video_id, prayer_type, status, date, scripture_ref, scripture_text,
                        meditation_author, meditation_text, manual_adjustment)
                       VALUES (?, 'ESCLUSO', 'ESCLUSO', '', '', '', '', '', 0)''',
                    (video_id,)
                )
            conn.commit()
            logger.info(f"Video {video_id} marcato come ESCLUSO.")

    def purge_liturgies(self, blacklist_terms: list) -> int:
        """Segna come ESCLUSO tutte le preghiere il cui prayer_type contiene un termine della blacklist.
        Ritorna il numero di record aggiornati."""
        count = 0
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for term in blacklist_terms:
                cursor.execute(
                    "UPDATE prayers SET status = 'ESCLUSO' WHERE LOWER(prayer_type) LIKE ? AND status != 'ESCLUSO'",
                    (f"%{term.lower()}%",)
                )
                count += cursor.rowcount
            conn.commit()
        logger.info(f"purge_liturgies: aggiornati {count} record.")
        return count

    def get_prayers_by_status(self, status: str = None) -> list:
        """Restituisce le preghiere filtrate per status. Se status=None, tutte tranne ESCLUSO."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if status is None:
                cursor.execute("SELECT * FROM prayers WHERE status != 'ESCLUSO' ORDER BY date DESC, id DESC")
            else:
                cursor.execute('SELECT * FROM prayers WHERE status = ? ORDER BY date DESC, id DESC', (status,))
            return [dict(row) for row in cursor.fetchall()]
