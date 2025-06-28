"""
Offline-first fingerprint service using cached music collection.
Works entirely offline after initial caching.
"""

import logging
import threading
import time
import json
import sqlite3
import numpy as np
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
import queue

try:
    import acoustid

    ACOUSTID_AVAILABLE = True
except ImportError:
    ACOUSTID_AVAILABLE = False

from ..protocols import MetadataSource
from ..models import TrackInfo

logger = logging.getLogger(__name__)


@dataclass
class OfflineFingerprintService(MetadataSource):
    """ Fingerprint service that works offline using cached collection. """

    cache_db_path: str = "../music_collection.sql"
    allow_online_fallback: bool = False  # Set True only if you want online fallback
    acoustid_api_key: Optional[str] = None  # Only needed if online fallback enabled

    recognition_thread: Optional[threading.Thread] = field(default=None, init=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False)
    _audio_queue: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=10), init=False)
    _current_track: Optional[TrackInfo] = field(default=None, init=False)
    _last_recognition_time: float = field(default=0, init=False)
    _recognition_buffer: List[np.ndarray] = field(default_factory=list, init=False)
    _cached_fingerprints: Dict = field(default_factory=dict, init=False)

    def __post_init__(self):
        """ Initialize the service. """
        self._load_cached_fingerprints()

    def _load_cached_fingerprints(self):
        """ Load all cached fingerprints into memory for fast matching. """
        if not Path(self.cache_db_path).exists():
            logger.warning(f"Cache database not found: {self.cache_db_path}")
            logger.info("Run the caching script first to build your collection")
            return

        conn = sqlite3.connect(self.cache_db_path)
        cursor = conn.cursor()

        # Load all tracks
        cursor.execute("""
            SELECT id, fingerprint, title, artist, album, album_art_local, 
                   duration, metadata
            FROM tracks
        """)

        tracks_loaded = 0
        for row in cursor.fetchall():
            track_id, fingerprint, title, artist, album, album_art, duration, metadata_json = row

            if fingerprint:
                self._cached_fingerprints[fingerprint] = {
                    'id': track_id,
                    'title': title,
                    'artist': artist,
                    'album': album,
                    'album_art_local': album_art,
                    'duration': duration,
                    'metadata': json.loads(metadata_json) if metadata_json else {}
                }
                tracks_loaded += 1

        conn.close()
        logger.info(f"Loaded {tracks_loaded} tracks from cache")

    def recognize_audio(self, audio_data: np.ndarray, sample_rate: int = 44100) -> Optional[Dict]:
        """ Recognize audio using cached fingerprints. """
        try:
            # Generate fingerprint
            if not ACOUSTID_AVAILABLE:
                logger.error("acoustid not available - install pyacoustid")
                return None

            # Convert audio format
            if audio_data.dtype != np.int16:
                if audio_data.dtype in [np.float32, np.float64]:
                    audio_data = (audio_data * 32767).astype(np.int16)

            # Generate fingerprint
            duration, fp = acoustid.fingerprint_raw(
                samplerate=sample_rate,
                channels=1,
                pcm=audio_data.tobytes()
            )

            # Check against cached fingerprints
            # In a real implementation, you'd use a proper fingerprint matching algorithm
            # For now, we'll do exact match on first N bytes
            # TODO FIX ABOVE
            fp_key = fp[:100]

            if fp_key in self._cached_fingerprints:
                cached = self._cached_fingerprints[fp_key]
                logger.info(f"Cache hit: {cached['title']} by {cached['artist']}")

                return {
                    'title': cached['title'],
                    'artist': cached['artist'],
                    'album': cached['album'],
                    'album_art_local': cached['album_art_local'],
                    'duration': cached['duration'],
                    'confidence': 0.95,  # High confidence for exact match
                    'metadata': cached['metadata']
                }

            # No cache hit
            if self.allow_online_fallback and self.acoustid_api_key:
                logger.info("No cache hit, trying online...")
                return self._online_recognition(fp, duration)
            else:
                logger.debug("No match found in cached collection")
                return None

        except Exception as e:
            logger.error(f"Recognition error: {e}")
            return None

    def _online_recognition(self, fingerprint: str, duration: int) -> Optional[Dict]:
        """ Fall back to online recognition if enabled. """
        try:
            results = acoustid.lookup(
                self.acoustid_api_key,
                fingerprint,
                duration,
                meta='recordings releasegroups'
            )

            for score, recording_id, title, artist in results:
                if score > 0.5:
                    return {
                        'title': title,
                        'artist': artist,
                        'confidence': score,
                        'is_online_result': True
                    }

        except Exception as e:
            logger.error(f"Online recognition failed: {e}")

        return None

    def get_collection_stats(self) -> Dict:
        """ Get statistics about cached collection. """
        conn = sqlite3.connect(self.cache_db_path)
        cursor = conn.cursor()

        stats = {}

        cursor.execute("SELECT COUNT(*) FROM tracks")
        stats['total_tracks'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(DISTINCT album) FROM tracks")
        stats['total_albums'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(DISTINCT artist) FROM tracks")
        stats['total_artists'] = cursor.fetchone()[0]

        cursor.execute("""
            SELECT artist, COUNT(*) as count 
            FROM tracks 
            GROUP BY artist 
            ORDER BY count DESC 
            LIMIT 5
        """)
        stats['top_artists'] = cursor.fetchall()

        conn.close()
        return stats

    def start_recognition(self):
        """ Start background recognition thread. """
        if not self._cached_fingerprints:
            logger.error("No cached fingerprints loaded!")
            return

        if self.recognition_thread and self.recognition_thread.is_alive():
            logger.warning("Recognition already running")
            return

        self._stop_event.clear()
        self.recognition_thread = threading.Thread(target=self._recognition_loop)
        self.recognition_thread.daemon = True
        self.recognition_thread.start()
        logger.info("Recognition thread started")

    def _recognition_loop(self):
        """ Background recognition loop. """
        buffer_duration = 10.0  # seconds
        sample_rate = 44100

        while not self._stop_event.is_set():
            try:
                # Get audio from queue
                audio_chunk = self._audio_queue.get(timeout=0.1)
                self._recognition_buffer.append(audio_chunk)

                # Calculate buffer duration
                total_samples = sum(len(chunk) for chunk in self._recognition_buffer)
                duration = total_samples / sample_rate

                if duration >= buffer_duration:
                    # Combine buffer
                    audio_data = np.concatenate(self._recognition_buffer)

                    # Recognize
                    result = self.recognize_audio(audio_data, sample_rate)

                    if result:
                        self._handle_recognition(result)

                    # Keep last 5 seconds
                    keep_samples = int(5 * sample_rate)
                    if len(audio_data) > keep_samples:
                        self._recognition_buffer = [audio_data[-keep_samples:]]
                    else:
                        self._recognition_buffer = []

            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Recognition loop error: {e}")

    def _handle_recognition(self, result: Dict):
        """ Handle successful recognition. """
        # Update play statistics
        if 'id' in result:
            self._update_play_stats(result['id'])

        # Create track info
        self._current_track = TrackInfo(
            title=result.get('title', 'Unknown'),
            artist=result.get('artist', 'Unknown Artist'),
            album=result.get('album', 'Unknown Album'),
            album_art_path=result.get('album_art_local'),
            lyrics_path=None,  # Could add lyrics support
            duration=result.get('duration', 0),
            recognition_confidence=result.get('confidence', 0)
        )

        self._last_recognition_time = time.time()

        logger.info(f"Recognized: {self._current_track.title} by {self._current_track.artist}")

    def _update_play_stats(self, track_id: int):
        """ Update play count and last played time. """
        try:
            conn = sqlite3.connect(self.cache_db_path)
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE tracks 
                SET play_count = play_count + 1,
                    last_played = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (track_id,))

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to update play stats: {e}")

    def queue_audio(self, audio_data: np.ndarray):
        """ Queue audio for recognition. """
        try:
            self._audio_queue.put_nowait(audio_data.copy())
        except queue.Full:
            try:
                self._audio_queue.get_nowait()
                self._audio_queue.put_nowait(audio_data.copy())
            except:
                pass

    def get_current_track(self) -> Optional[TrackInfo]:
        """ Get current track info. """
        if self._current_track and (time.time() - self._last_recognition_time) > 45:
            self._current_track = None
        return self._current_track

    def stop_recognition(self):
        """ Stop recognition thread. """
        self._stop_event.set()
        if self.recognition_thread:
            self.recognition_thread.join(timeout=2.0)