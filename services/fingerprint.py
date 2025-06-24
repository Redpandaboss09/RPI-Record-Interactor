from dejavu import Dejavu
import numpy as np
from models import TrackInfo, Config
from protocols import MetadataSource
import threading
import time
from queue import Queue, Empty
from typing import Optional
import sqlite3
from contextlib import contextmanager
import os


class FingerprintService(MetadataSource):
    """ Audio fingerprinting service using Dejavu with SQLite. """

    def __init__(self, config: Config, db_config: dict):
        self.config = config
        self.db_config = db_config

        # Ensure database is set up before initializing Dejavu
        self._setup_database()

        # Initialize Dejavu
        try:
            self.dejavu = Dejavu(db_config)
            print("Dejavu initialized successfully")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Dejavu: {e}")

        # Recognition state
        self.recognition_queue: Queue = Queue(maxsize=2)
        self.current_track: Optional[TrackInfo] = None
        self.last_song_id: Optional[int] = None

        # Threading
        self.recognition_thread: Optional[threading.Thread] = None
        self.running = False

        # Recognition parameters
        self.recognition_interval = 0.5  # Check queue every 0.5 seconds
        self.confidence_threshold = 10  # Minimum confidence (adjust based on testing)
        self.min_recognition_seconds = 3.0  # Minimum audio length to attempt recognition

    def _setup_database(self):
        """ Ensure all required tables exist. """
        db_path = self.db_config['database']['name']

        # Create database file if it doesn't exist
        conn = sqlite3.connect(db_path)

        # Check if we have a schema file
        schema_file = 'database/schema_sqlite.sql'
        if os.path.exists(schema_file):
            print(f"Running schema from {schema_file}")
            with open(schema_file, 'r') as f:
                conn.executescript(f.read())
        else:
            # Fallback: create tables directly
            print("No schema file found, creating tables directly")
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS track_metadata (
                    dejavu_song_id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    album TEXT,
                    album_art_path TEXT,
                    lyrics_file TEXT,
                    duration REAL,
                    date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_track_artist ON track_metadata(artist)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_track_album ON track_metadata(album)
            """)

        conn.commit()
        conn.close()
        print(f"Database setup complete: {os.path.abspath(db_path)}")

    def start(self) -> None:
        """ Start the background recognition thread. """
        if self.running:
            return

        self.running = True
        self.recognition_thread = threading.Thread(
            target=self._recognition_loop,
            name="FingerprintRecognition",
            daemon=True
        )
        self.recognition_thread.start()
        print("Fingerprint recognition service started")

    def stop(self) -> None:
        """ Stop the recognition thread. """
        if not self.running:
            return

        self.running = False
        if self.recognition_thread:
            self.recognition_thread.join(timeout=5.0)
        print("Fingerprint recognition service stopped")

    def _recognition_loop(self) -> None:
        """ Background thread that processes recognition requests. """
        while self.running:
            try:
                # Get audio chunk from queue (with timeout)
                audio_chunk = self.recognition_queue.get(timeout=self.recognition_interval)

                # Process recognition
                self._process_recognition(audio_chunk)

            except Empty:
                # No audio to process, continue
                continue
            except Exception as e:
                print(f"Recognition error: {e}")
                time.sleep(1.0)  # Brief pause on error

    def submit_audio(self, audio_data: np.ndarray) -> None:
        """ Submit audio for recognition (non-blocking). """
        if not self.running:
            return

        try:
            # Convert to format Dejavu expects
            # Ensure it's mono and float32
            if audio_data.ndim > 1:
                audio_data = np.mean(audio_data, axis=1)

            # Non-blocking put - drops old data if queue is full
            self.recognition_queue.put_nowait(audio_data)
        except:
            # Queue full, skip this chunk
            pass

    def _process_recognition(self, audio_data: np.ndarray) -> None:
        """ Perform the actual recognition. """
        try:
            # Dejavu expects specific format
            # Convert float32 [-1, 1] to int16 [-32768, 32767]
            audio_int16 = (audio_data * 32767).astype(np.int16)

            # Recognize using Dejavu
            results = self.dejavu.recognize(audio_int16, self.config.sample_rate)

            if results and results.get('song_id') is not None:
                song_id = results['song_id']
                confidence = results.get('input_confidence', 0)

                # Check confidence threshold
                if confidence >= self.confidence_threshold:
                    # Check if it's a different track
                    if song_id != self.last_song_id:
                        self.last_song_id = song_id
                        self._handle_track_change(song_id)

        except Exception as e:
            print(f"Recognition processing error: {e}")

    def _handle_track_change(self, song_id: int) -> None:
        """ Handle when a new track is detected. """
        # Load track metadata from database
        track_info = self._load_track_metadata(song_id)

        if track_info:
            self.current_track = track_info
            print(f"Now playing: {track_info.title} by {track_info.artist}")
        else:
            print(f"Recognized song ID {song_id} but no metadata found")

    @contextmanager
    def _get_db_connection(self):
        """ Get a database connection. """
        conn = None
        try:
            # SQLite connection
            db_path = self.db_config['database']['name']
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row  # Enable column access by name
            yield conn
        finally:
            if conn:
                conn.close()

    def _load_track_metadata(self, song_id: int) -> Optional[TrackInfo]:
        """ Load track metadata from database. """
        try:
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT title, artist, album, album_art_path, 
                           lyrics_file, duration
                    FROM track_metadata
                    WHERE dejavu_song_id = ?
                """, (song_id,))

                row = cursor.fetchone()
                if row:
                    return TrackInfo(
                        id=str(song_id),
                        title=row['title'],
                        artist=row['artist'],
                        album=row['album'],
                        duration=row['duration']
                    )

        except Exception as e:
            print(f"Error loading track metadata: {e}")

        return None

    def get_track_info(self, track_id: str) -> Optional[TrackInfo]:
        """ Get current track info (MetadataSource protocol method). """
        return self.current_track

    def get_current_track(self) -> Optional[TrackInfo]:
        """ Get the currently recognized track. """
        return self.current_track

    def fingerprint_file(self, filepath: str, track_info: TrackInfo) -> bool:
        """ Add a new song to the fingerprint database. """
        try:
            # Fingerprint the file
            song_id = self.dejavu.fingerprint_file(filepath)

            if song_id:
                # Store metadata in our table
                with self._get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT OR REPLACE INTO track_metadata 
                        (dejavu_song_id, title, artist, album, duration)
                        VALUES (?, ?, ?, ?, ?)
                    """, (song_id, track_info.title, track_info.artist,
                          track_info.album, track_info.duration))
                    conn.commit()

                print(f"Fingerprinted: {track_info.title} (ID: {song_id})")
                return True

        except Exception as e:
            print(f"Error fingerprinting {filepath}: {e}")

        return False

    def fingerprint_directory(self, directory: str, extensions: list = None):
        """ Fingerprint all audio files in a directory. """
        if extensions is None:
            extensions = [".mp3", ".wav", ".flac", ".m4a"]

        # Use Dejavu's built-in directory fingerprinting
        self.dejavu.fingerprint_directory(directory, extensions)
        print(f"Fingerprinted directory: {directory}")