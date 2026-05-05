import sys
import os
from pathlib import Path
from datetime import datetime

# Aggiungi la root del progetto al path
sys.path.insert(0, str(Path(__file__).parent.parent))

import yt_dlp
from core.database import PrayerDatabase
from config.settings import AppSettings

def list_top_5():
    settings = AppSettings()
    db = PrayerDatabase(settings.db_path)
    
    CHANNEL_URL = "https://www.youtube.com/@santegidio/streams"
    keywords = ["preghiera", "memoria"]
    
    print(f"Ricerca video su {CHANNEL_URL}...")
    
    ydl_opts = {
        'quiet': True,
        'extract_flat': 'in_playlist',
        'playlistend': 50,
    }
    if settings.cookies_file and os.path.exists(settings.cookies_file):
        ydl_opts['cookiefile'] = settings.cookies_file

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(CHANNEL_URL, download=False)
        if 'entries' not in result:
            print("Nessun video trovato.")
            return
        
        videos = result['entries']
        # Sort newest first
        videos.sort(key=lambda x: x.get('upload_date') or '00000000', reverse=True)
        
        filtered = []
        today_str = datetime.now().strftime("%Y%m%d")
        
        for v in videos:
            title = v.get('title', '').lower()
            video_id = v.get('id')
            
            # 1. Keywords
            if not any(k in title for k in keywords):
                continue
                
            # 2. Language exclude
            if any(lang in title for lang in ["prayer", "prière", "oracion", "oração", "english", "español", "français"]):
                continue
                
            # 3. Already processed
            if db.is_video_processed(video_id):
                # print(f"Già processato: {v.get('title')} ({video_id})")
                continue
                
            # 4. Upcoming
            if v.get('live_status') == 'upcoming' or "in programma" in title:
                continue
                
            # 5. Future (safety check)
            upload_date = v.get('upload_date')
            if upload_date and upload_date > today_str:
                continue
                
            filtered.append(v)
            if len(filtered) >= 5:
                break
                
        if not filtered:
            print("Nessun nuovo video da trascrivere trovato con gli attuali filtri.")
        else:
            print("\nPrimi 5 video da trascrivere:")
            for i, v in enumerate(filtered):
                date = v.get('upload_date', 'N/D')
                if date != 'N/D':
                    date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
                print(f"{i+1}. [{date}] {v.get('title')} ({v.get('id')})")

if __name__ == "__main__":
    list_top_5()
