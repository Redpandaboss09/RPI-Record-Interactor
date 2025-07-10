import requests

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from models import Config

class LRCLIBGatherer:
    def __init__(self, config: Config):
        self.config = config

        self.headers = {
            'User-Agent': f'{self.config.origin_name} ({self.config.origin_url})'
        }

    def gather_lyric_single(self, track_name: str, artist_name: str, album_name: str, duration: int) -> str:
        """ Fetches synced lyrics from LRCLIB API for a single track. """
        url = 'https://lrclib.net/api/get?'
        params = {
            'artist_name': artist_name,
            'track_name': track_name,
            'album_name': album_name,
            'duration': duration
        }

        response = requests.get(url, params=params, headers=self.headers)

        return response.json()['syncedLyrics']

    def store_in_existing_db(self, track_name: str, artist_name: str, album_name: str, lyrics: str) -> None:
        pass