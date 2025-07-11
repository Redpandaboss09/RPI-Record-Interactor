import logging
import time

import requests
from tqdm import tqdm

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from models import Config
from services.music_database import MusicDatabase


class LRCLIBGatherer:
    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger(__name__)

        self.headers = {
            'User-Agent': f'{self.config.origin_name} ({self.config.origin_url})'
        }

        self.request_delay = 0.5
        self.last_request_time = 0

    def gather_lyrics_all(self) -> None:
        """ Gathers the lyrics for all songs in the database. """
        with MusicDatabase(self.config) as db:
            db.cursor.execute("""
                SELECT id, title, artist, album, duration, audio_file_path
                FROM tracks
                WHERE lyrics_file_path IS NULL
                ORDER BY album, disc_number, track_number
            """)

            tracks = db.cursor.fetchall()

            if not tracks:
                print('All tracks already have lyrics.')
                return

            print(f'Found {len(tracks)} tracks without lyrics.')
            successful = 0
            failed = 0
            already_exists = 0

            with tqdm(tracks, desc="Fetching lyrics") as pbar:
                for track in pbar:
                    pbar.set_description(f"Processing: {track['title'][:30]}...")

                    # Check if .lrc already exists
                    lrc_path = Path(track['audio_file_path']).with_suffix('.lrc')

                    if lrc_path.exists():
                        # Just update the database
                        db.cursor.execute(
                            "UPDATE tracks SET lyrics_file_path = ? WHERE id = ?",
                            (str(lrc_path), track['id'])
                        )
                        already_exists += 1
                    else:
                        self._rate_limit()

                        lyrics = self._gather_lyric_single(
                            track_name=track['title'],
                            artist_name=track['artist'],
                            album_name=track['album'] or "",
                            duration=track['duration']
                        )

                        if lyrics:
                            # Save .lrc file
                            lrc_path.write_text(lyrics, encoding='utf-8')

                            # Update database
                            db.cursor.execute(
                                "UPDATE tracks SET lyrics_file_path = ? WHERE id = ?",
                                (str(lrc_path), track['id'])
                            )
                            successful += 1
                        else:
                            failed += 1

                    pbar.set_postfix({
                        "✓": successful,
                        "✗": failed,
                        "→": already_exists
                    })

            db.conn.commit()

            print(f"\nComplete!")
            print(f"  Downloaded: {successful}")
            print(f"  Failed: {failed}")
            print(f"  Already existed: {already_exists}")

    def _gather_lyric_single(self, track_name: str, artist_name: str, album_name: str, duration: int) -> str | None:
        """ Fetches synced lyrics from LRCLIB API for a single track. """
        url = 'https://lrclib.net/api/get?'
        params = {
            'artist_name': artist_name,
            'track_name': track_name,
            'album_name': album_name,
            'duration': duration
        }

        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            response.raise_for_status()

            data = response.json()

            # Prefer synced lyrics, fall back to plain
            return data.get('syncedLyrics') or data.get('plainLyrics')

        except Exception as e:
            self.logger.error(f"Failed to fetch lyrics for {track_name}: {e}")
            return None

    def _rate_limit(self):
        """ Simple rate limiting. """
        current_time = time.time()
        time_since_last = current_time - self.last_request_time

        if time_since_last < self.request_delay:
            time.sleep(self.request_delay - time_since_last)

        self.last_request_time = time.time()
