import yt_dlp
import json

URL = "https://www.youtube.com/@santegidio/streams"
ydl_opts = {
    'quiet': True,
    'extract_flat': 'in_playlist',
    'playlistend': 10,
}

with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    result = ydl.extract_info(URL, download=False)
    if 'entries' in result:
        for i, entry in enumerate(result['entries']):
            print(f"{i}: {entry.get('title')} - {entry.get('upload_date')} - {entry.get('id')}")
    else:
        print("No entries found")
