import sqlite3
import json
import os

db_path = r"G:\Il mio Drive\Preghiere\prayers.db"

if not os.path.exists(db_path):
    print(f"ERRORE: Database non trovato in {db_path}")
    # Provo a cercare nel workspace se per caso è lì
    db_path = "prayers.db"

try:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Prendiamo le ultime preghiere aggiustate manualmente
    cursor.execute("SELECT * FROM prayers WHERE manual_adjustment = 1 ORDER BY date DESC LIMIT 20")
    rows = cursor.fetchall()
    
    analysis = []
    
    for row in rows:
        p_id = row['id']
        title = row['scripture_ref'] or row['prayer_type']
        v_start = row['video_start']
        v_end = row['video_end']
        full_json = row['full_data_json']
        
        if not full_json: continue
        
        segments = json.loads(full_json)
        
        # Troviamo i segmenti vicini all'inizio utente
        start_context = [s for s in segments if abs(s['start'] - v_start) < 20]
        # Troviamo i segmenti vicini alla fine utente
        end_context = [s for s in segments if abs(s['end'] - v_end) < 20]
        
        analysis.append({
            "id": p_id,
            "title": title,
            "user_start": v_start,
            "user_end": v_end,
            "start_segments": start_context,
            "end_segments": end_context
        })
        
    print(json.dumps(analysis, indent=2))
    
except Exception as e:
    print(f"Errore durante l'analisi: {e}")
