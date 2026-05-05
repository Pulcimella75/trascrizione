import sys
import os
from pathlib import Path
import yt_dlp

# Aggiungi root progetto
sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import AppSettings

def debug_yt_fetch():
    settings = AppSettings()
    url = "https://www.youtube.com/@santegidio/streams"
    
    ydl_opts = {
        'quiet': True,
        'extract_flat': 'in_playlist',
        'playlistend': 10,
    }
    if settings.cookies_file and os.path.exists(settings.cookies_file):
        ydl_opts['cookiefile'] = settings.cookies_file

    print(f"Fetching from {url}...")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(url, download=False)
        entries = result.get('entries', [])
        print(f"Trovati {len(entries)} video.")
        for i, v in enumerate(entries):
            print(f"{i}: ID={v.get('id')} | Date={v.get('upload_date')} | Title={v.get('title')}")

if __name__ == "__main__":
    debug_yt_fetch()
