"""
Lyrics service using LRCLIB API.
Fetches synchronized lyrics and manages LRC files.
"""

import requests
import sqlite3
import time
import logging
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class LyricsResult:
    """ Result from LRCLIB API. """
    id: int
    track_name: str
    artist_name: str
    album_name: Optional[str]
    duration: float
    instrumental: bool
    plain_lyrics: Optional[str]
    synced_lyrics: Optional[str]

    @property
    def has_synced_lyrics(self) -> bool:
        return bool(self.synced_lyrics and self.synced_lyrics.strip())

    @property
    def has_plain_lyrics(self) -> bool:
        return bool(self.plain_lyrics and self.plain_lyrics.strip())


class LRCLIBService:
    """ Service for fetching lyrics from LRCLIB API. """

    BASE_URL = "https://lrclib.net/api"

    def __init__(self, lyrics_dir: Path = Path("music_data/lyrics"), cache_db: str = "music_collection.db"):
        self.lyrics_dir = lyrics_dir
        self.lyrics_dir.mkdir(exist_ok=True)
        self.cache_db = cache_db

        # Rate limiting
        self.last_request_time = 0
        self.min_request_interval = 0.5  # LRCLIB is generous but let's be respectful

    def search_lyrics(self, track_name: str, artist_name: str,
                      album_name: Optional[str] = None,
                      duration: Optional[float] = None) -> Optional[LyricsResult]:
        """
        Search for lyrics using LRCLIB API.

        LRCLIB API: GET /api/search
        Parameters:
        - track_name: Track name (required if artist_name isn't provided)
        - artist_name: Artist name (required if track_name isn't provided)
        - album_name: Album name (optional)
        - duration: Track duration in seconds (optional, helps matching)
        """
        self._rate_limit()

        # Build query parameters
        params = {}
        if track_name:
            params['track_name'] = track_name
        if artist_name:
            params['artist_name'] = artist_name
        if album_name:
            params['album_name'] = album_name

        try:
            response = requests.get(
                f"{self.BASE_URL}/search",
                params=params,
                timeout=10
            )

            if response.status_code == 200:
                results = response.json()

                if not results:
                    return None

                # If we have duration, find best match
                if duration and len(results) > 1:
                    best_match = self._find_best_duration_match(results, duration)
                    if best_match:
                        return self._parse_result(best_match)

                # Otherwise return first result
                return self._parse_result(results[0])

            elif response.status_code == 404:
                logger.info(f"No lyrics found for {artist_name} - {track_name}")
                return None
            else:
                logger.error(f"LRCLIB API error: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error fetching from LRCLIB: {e}")
            return None

    def get_lyrics_by_id(self, track_id: int) -> Optional[LyricsResult]:
        """ Get lyrics by LRCLIB track ID. """
        self._rate_limit()

        try:
            response = requests.get(
                f"{self.BASE_URL}/get/{track_id}",
                timeout=10
            )

            if response.status_code == 200:
                return self._parse_result(response.json())
            else:
                return None

        except Exception as e:
            logger.error(f"Error fetching lyrics by ID: {e}")
            return None

    def fetch_and_save_lyrics(self, track_name: str, artist_name: str,
                              album_name: Optional[str] = None,
                              duration: Optional[float] = None) -> Optional[str]:
        """
        Fetch lyrics and save to LRC file.
        Returns path to saved file if successful.
        """
        # Check if we already have lyrics
        existing_path = self._check_existing_lyrics(artist_name, track_name)
        if existing_path:
            logger.info(f"Lyrics already exist at {existing_path}")
            return str(existing_path)

        # Search for lyrics
        result = self.search_lyrics(track_name, artist_name, album_name, duration)

        if not result:
            return None

        if result.instrumental:
            # Create instrumental LRC
            lrc_content = self._create_instrumental_lrc(
                artist_name, track_name, album_name, duration
            )
        elif result.has_synced_lyrics:
            # Use synced lyrics (already in LRC format)
            lrc_content = result.synced_lyrics
        elif result.has_plain_lyrics:
            # Convert plain lyrics to basic LRC
            lrc_content = self._create_lrc_from_plain(
                result.plain_lyrics, artist_name, track_name,
                album_name, duration
            )
        else:
            return None

        # Save to file
        filename = f"{self._sanitize_filename(artist_name)} - {self._sanitize_filename(track_name)}.lrc"
        file_path = self.lyrics_dir / filename

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(lrc_content)
            logger.info(f"Saved lyrics to {file_path}")
            return str(file_path)
        except Exception as e:
            logger.error(f"Error saving lyrics: {e}")
            return None

    def update_track_lyrics(self, track_id: int, lyrics_path: str):
        """ Update track in database with lyrics path. """
        conn = sqlite3.connect(self.cache_db)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE tracks
            SET lyrics_local = ?
            WHERE id = ?
        """, (lyrics_path, track_id))

        conn.commit()
        conn.close()

    def fetch_lyrics_for_recent_tracks(self, hours: float = 0.25):
        """
        Fetch lyrics only for recently added tracks.
        Default: 15 minutes (0.25 hours) to catch just the current session.
        """
        conn = sqlite3.connect(self.cache_db)
        cursor = conn.cursor()

        # Get tracks added within the time window that don't have lyrics
        cursor.execute("""
            SELECT id, title, artist, album, duration
            FROM tracks
            WHERE (lyrics_local IS NULL OR lyrics_local = '')
            AND datetime(added_date) > datetime('now', ? || ' hours')
            ORDER BY artist, album, track_number
        """, (-hours,))

        tracks = cursor.fetchall()

        if not tracks:
            print("No new tracks need lyrics")
            conn.close()
            return

        print(f"Found {len(tracks)} recently added tracks without lyrics")

        success_count = 0
        instrumental_count = 0

        for i, (track_id, title, artist, album, duration) in enumerate(tracks, 1):
            print(f"\n[{i}/{len(tracks)}] {artist} - {title}")

            lyrics_path = self.fetch_and_save_lyrics(
                title, artist, album, duration
            )

            if lyrics_path:
                self.update_track_lyrics(track_id, lyrics_path)

                # Check if instrumental
                with open(lyrics_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if '[instrumental]' in content.lower():
                        instrumental_count += 1
                        print("  -> Instrumental track")
                    else:
                        success_count += 1
                        print(f"  -> Saved lyrics")
            else:
                print("  -> No lyrics found")

        conn.close()

        print(f"\nSummary:")
        print(f"  Tracks with lyrics: {success_count}")
        print(f"  Instrumental tracks: {instrumental_count}")
        print(f"  Not found: {len(tracks) - success_count - instrumental_count}")

    def fetch_lyrics_for_album(self, album_name: str):
        """
        Fetch lyrics for all tracks in a specific album.
        """
        conn = sqlite3.connect(self.cache_db)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, title, artist, album, duration
            FROM tracks
            WHERE album = ?
            AND (lyrics_local IS NULL OR lyrics_local = '')
            ORDER BY track_number
        """, (album_name,))

        tracks = cursor.fetchall()

        if not tracks:
            print(f"No tracks without lyrics found for album: {album_name}")
            conn.close()
            return

        print(f"Fetching lyrics for {len(tracks)} tracks from: {album_name}")

        # Use the same logic as fetch_lyrics_for_all_tracks
        success_count = 0
        instrumental_count = 0

        for i, (track_id, title, artist, album, duration) in enumerate(tracks, 1):
            print(f"\n[{i}/{len(tracks)}] {title}")

            lyrics_path = self.fetch_and_save_lyrics(
                title, artist, album, duration
            )

            if lyrics_path:
                self.update_track_lyrics(track_id, lyrics_path)

                # Check if instrumental
                with open(lyrics_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if '[instrumental]' in content.lower():
                        instrumental_count += 1
                        print("  -> Instrumental track")
                    else:
                        success_count += 1
                        print(f"  -> Saved lyrics")
            else:
                print("  -> No lyrics found")

        conn.close()

        print(f"\nAlbum lyrics summary:")
        print(f"  Tracks with lyrics: {success_count}")
        print(f"  Instrumental tracks: {instrumental_count}")
        print(f"  Not found: {len(tracks) - success_count - instrumental_count}")

    def fetch_lyrics_for_all_tracks(self, limit: Optional[int] = None):
        """
        Fetch lyrics for all tracks in database that don't have them.
        """
        conn = sqlite3.connect(self.cache_db)
        cursor = conn.cursor()

        query = """
            SELECT id, title, artist, album, duration
            FROM tracks
            WHERE lyrics_local IS NULL OR lyrics_local = ''
            ORDER BY artist, album, track_number
        """

        if limit:
            query += f" LIMIT {limit}"

        cursor.execute(query)
        tracks = cursor.fetchall()

        print(f"Found {len(tracks)} tracks without lyrics")

        success_count = 0
        instrumental_count = 0

        for i, (track_id, title, artist, album, duration) in enumerate(tracks, 1):
            print(f"\n[{i}/{len(tracks)}] {artist} - {title}")

            lyrics_path = self.fetch_and_save_lyrics(
                title, artist, album, duration
            )

            if lyrics_path:
                self.update_track_lyrics(track_id, lyrics_path)

                # Check if instrumental
                with open(lyrics_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if '[instrumental]' in content.lower():
                        instrumental_count += 1
                        print("  -> Instrumental track")
                    else:
                        success_count += 1
                        print(f"  -> Saved lyrics")
            else:
                print("  -> No lyrics found")

        conn.close()

        print(f"\nSummary:")
        print(f"  Tracks with lyrics: {success_count}")
        print(f"  Instrumental tracks: {instrumental_count}")
        print(f"  Not found: {len(tracks) - success_count - instrumental_count}")

    def _rate_limit(self):
        """ Simple rate limiting. """
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)
        self.last_request_time = time.time()

    def _parse_result(self, data: Dict) -> LyricsResult:
        """ Parse API response into LyricsResult. """
        return LyricsResult(
            id=data.get('id'),
            track_name=data.get('trackName', ''),
            artist_name=data.get('artistName', ''),
            album_name=data.get('albumName'),
            duration=data.get('duration', 0),
            instrumental=data.get('instrumental', False),
            plain_lyrics=data.get('plainLyrics'),
            synced_lyrics=data.get('syncedLyrics')
        )

    def _find_best_duration_match(self, results: List[Dict],
                                  target_duration: float) -> Optional[Dict]:
        """ Find result with closest duration match. """
        if not results:
            return None

        # Allow 5 second tolerance
        tolerance = 5.0

        best_match = None
        best_diff = float('inf')

        for result in results:
            result_duration = result.get('duration', 0)
            if result_duration:
                diff = abs(result_duration - target_duration)
                if diff < best_diff and diff <= tolerance:
                    best_diff = diff
                    best_match = result

        return best_match or results[0]  # Fallback to first if no good match

    def _check_existing_lyrics(self, artist: str, title: str) -> Optional[Path]:
        """ Check if we already have lyrics for this track. """
        filename = f"{self._sanitize_filename(artist)} - {self._sanitize_filename(title)}.lrc"
        file_path = self.lyrics_dir / filename

        if file_path.exists():
            return file_path

        return None

    def _create_instrumental_lrc(self, artist: str, title: str,
                                 album: Optional[str], duration: Optional[float]) -> str:
        """ Create LRC for instrumental track. """
        lrc = f"[ar:{artist}]\n[ti:{title}]\n"
        if album:
            lrc += f"[al:{album}]\n"
        if duration:
            lrc += f"[length:{int(duration)}]\n"
        lrc += "[by:LRCLIB]\n\n"
        lrc += "[00:00.00][Instrumental]\n"

        return lrc

    def _create_lrc_from_plain(self, plain_lyrics: str, artist: str, title: str,
                               album: Optional[str], duration: Optional[float]) -> str:
        """ Convert plain lyrics to basic LRC format. """
        lines = plain_lyrics.strip().split('\n')

        # Build header
        lrc = f"[ar:{artist}]\n[ti:{title}]\n"
        if album:
            lrc += f"[al:{album}]\n"
        if duration:
            lrc += f"[length:{int(duration)}]\n"
        lrc += "[by:LRCLIB (unsynced)]\n\n"

        # Add timing
        if duration and duration > 0 and len(lines) > 1:
            # Distribute evenly with intro
            intro_time = 5.0
            outro_time = 5.0
            singing_duration = max(0, duration - intro_time - outro_time)
            time_per_line = singing_duration / len(lines) if lines else 0

            for i, line in enumerate(lines):
                if line.strip():
                    timestamp = intro_time + (i * time_per_line)
                    minutes = int(timestamp // 60)
                    seconds = timestamp % 60
                    lrc += f"[{minutes:02d}:{seconds:05.2f}]{line}\n"
        else:
            # No timing - all at start
            for line in lines:
                if line.strip():
                    lrc += f"[00:00.00]{line}\n"

        return lrc

    def _sanitize_filename(self, text: str) -> str:
        """ Remove invalid filename characters. """
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            text = text.replace(char, '_')
        return text.strip()

def add_lyrics_to_track_info(track_info, lyrics_service: LRCLIBService):
    """ Helper to add lyrics path to TrackInfo object. """
    if track_info and track_info.title and track_info.artist:
        lyrics_path = lyrics_service._check_existing_lyrics(
            track_info.artist,
            track_info.title
        )
        if lyrics_path:
            track_info.lyrics_path = str(lyrics_path)
    return track_info
