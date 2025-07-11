from collections import defaultdict, Counter
import sqlite3
import time

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from models import Config, TrackInfo


class MusicDatabase:
    def __init__(self, config: Config):
        self.config = config

        # In-Memory cache
        self._track_cache = {}
        self._stats_cache = None
        self._cache_time = 0

        # SQLite setup
        self.conn = sqlite3.connect(
            config.db_path,
            isolation_level='DEFERRED',
            check_same_thread=False,
            timeout=30.0
        )

        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()

        self._configure_performance()
        self._create_tables()

    def _configure_performance(self):
        """ Sets up SQLITE for most performance. """
        self.cursor.executescript("""
            PRAGMA journal_mode = DELETE;
            PRAGMA synchronous = NORMAL;
            PRAGMA cache_size = -64000;
            PRAGMA temp_store = MEMORY;
            PRAGMA page_size = 16384;
            PRAGMA optimize;
        """)

    def _create_tables(self):
        """ Creates all tables if they don't exist. """
        self.cursor.executescript('''
            CREATE TABLE IF NOT EXISTS tracks(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                album TEXT,
                track_number INTEGER,
                total_tracks INTEGER,
                disc_number INTEGER DEFAULT 1,
                total_discs INTEGER,
                duration INTEGER NOT NULL,
                audio_file_path TEXT NOT NULL UNIQUE,
                album_art_path TEXT,
                lyrics_file_path TEXT,
                date_added DATETIME DEFAULT CURRENT_TIMESTAMP,
                fingerprint_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS fingerprints(
                hash INTEGER NOT NULL,
                track_id INTEGER NOT NULL,
                time_offset INTEGER NOT NULL,
                PRIMARY KEY (hash, track_id, time_offset)
            ) WITHOUT ROWID;

            CREATE INDEX IF NOT EXISTS idx_fingerprint_hash
                ON fingerprints(hash);

            CREATE INDEX IF NOT EXISTS idx_fingerprint_track
                ON fingerprints(track_id);

            CREATE INDEX IF NOT EXISTS idx_track_lookup
                ON tracks(title, artist, album);

            CREATE INDEX IF NOT EXISTS idx_track_disc
                ON tracks(album, disc_number, track_number);
        ''')

        self.conn.commit()

    def add_track(self, metadata: TrackInfo) -> int:
        """ Adds a new track to the database. """
        self.cursor.execute(
            "SELECT id FROM tracks WHERE audio_file_path = ?",
            (metadata.audio_file_path,)
        )
        existing = self.cursor.fetchone()

        if existing:
            print(f'Track already exists: {metadata.title} by {metadata.artist}')
            return -1

        # Insert new track
        self.cursor.execute("""
                   INSERT INTO tracks (
                       title, artist, album, duration, audio_file_path,
                       album_art_path, lyrics_file_path, track_number, total_tracks,
                       disc_number, total_discs
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               """, (
            metadata.title,
            metadata.artist,
            metadata.album,
            metadata.duration,
            metadata.audio_file_path,
            metadata.album_art_path,
            metadata.lyrics_file_path,
            metadata.track_number,
            metadata.total_tracks,
            metadata.disc_number if hasattr(metadata, 'disc_number') else 1,
            metadata.total_discs if hasattr(metadata, 'total_discs') else None
        ))

        track_id = self.cursor.lastrowid
        self.conn.commit()

        # Clear cache
        self._track_cache.pop(track_id, None)
        self._stats_cache = None

        return track_id

    def delete_track(self, track_id: int) -> None:
        """ Deletes a track from the database. """
        # Delete fingerprints first
        self.cursor.execute("DELETE FROM fingerprints WHERE track_id = ?", (track_id,))

        # Delete track
        self.cursor.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
        self.conn.commit()

        # Clear cache
        self._track_cache.pop(track_id, None)
        self._stats_cache = None

    def get_track(self, track_id: int) -> TrackInfo | None:
        """ Gets a track from the database. """
        # Check cache first
        if track_id in self._track_cache:
            return self._track_cache[track_id]

        self.cursor.execute("SELECT * FROM tracks WHERE id = ?", (track_id,))
        row = self.cursor.fetchone()

        if not row:
            return None

        track_info = TrackInfo(
            title=row['title'],
            artist=row['artist'],
            album=row['album'],
            duration=row['duration'],
            audio_file_path=row['audio_file_path'],
            album_art_path=row['album_art_path'],
            lyrics_file_path=row['lyrics_file_path'],
            track_number=row['track_number'],
            total_tracks=row['total_tracks'],
            disc_number=row['disc_number'],
            total_discs=row['total_discs']
        )

        # Cache for future use
        self._track_cache[track_id] = track_info

        return track_info

    def track_exists(self, title: str, artist: str = None, album: str = None) -> bool:
        """ Check if a track exists in the database. """
        query = "SELECT EXISTS(SELECT 1 FROM tracks WHERE title = ? AND artist = ?"
        params = [title, artist]

        if album:
            query += " AND album = ?"
            params.append(album)

        query += ")"

        self.cursor.execute(query, params)
        return self.cursor.fetchone()[0] == 1

    def search_tracks(self, query: str) -> list[TrackInfo]:
        """ Search for tracks in the database across title, artist and album. """
        sql = """
            SELECT * FROM tracks
            WHERE title LIKE ? OR artist LIKE ? OR album LIKE ?
            ORDER BY
                CASE
                    WHEN title LIKE ? THEN 1
                    WHEN artist LIKE ? THEN 2
                    ELSE 3
                END
        """

        pattern = f"%{query}%"
        self.cursor.execute(sql, (pattern, pattern, pattern, pattern, pattern))

        return [
            TrackInfo(
                title=row['title'],
                artist=row['artist'],
                album=row['album'],
                duration=row['duration'],
                audio_file_path=row['audio_file_path'],
                album_art_path=row['album_art_path'],
                lyrics_file_path=row['lyrics_file_path'],
                track_number=row['track_number'],
                total_tracks=row['total_tracks'],
                disc_number=row['disc_number'],
                total_discs=row['total_discs']
            )
            for row in self.cursor.fetchall()
        ]

    def get_album_tracks(self, album: str, artist: str = None) -> list[TrackInfo]:
        """ Get all tracks from an album, properly ordered by disc and track number. """
        if artist:
            sql = """
                SELECT * FROM tracks 
                WHERE album = ? AND artist = ?
                ORDER BY disc_number, track_number
            """
            params = (album, artist)
        else:
            sql = """
                SELECT * FROM tracks 
                WHERE album = ?
                ORDER BY disc_number, track_number
            """
            params = (album,)

        self.cursor.execute(sql, params)

        return [
            TrackInfo(
                title=row['title'],
                artist=row['artist'],
                album=row['album'],
                duration=row['duration'],
                audio_file_path=row['audio_file_path'],
                album_art_path=row['album_art_path'],
                lyrics_file_path=row['lyrics_file_path'],
                track_number=row['track_number'],
                total_tracks=row['total_tracks'],
                disc_number=row['disc_number'],
                total_discs=row['total_discs']
            )
            for row in self.cursor.fetchall()
        ]

    def add_fingerprints(self, track_id: int, fingerprints: list[tuple]) -> None:
        """ Store fingerprints in the database. """
        if not self.get_track(track_id):
            raise ValueError(f'Track {track_id} does not exist')

        self.cursor.execute("BEGIN")

        try:
            self.cursor.execute("DELETE FROM fingerprints WHERE track_id = ?", (track_id,))

            self.cursor.executemany(
                "INSERT INTO fingerprints (hash, track_id, time_offset) VALUES (?, ?, ?)",
                [(fp[0], track_id, int(fp[1])) for fp in fingerprints]
            )

            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def add_fingerprints_batch(self, track_id: int, fingerprints: list[tuple[int, int]]) -> None:
        """ Add fingerprints in batches. """
        if not fingerprints:
            return

        MAX_BATCH_SIZE = 5000
        MAX_RETRIES = 3

        for attempt in range(MAX_RETRIES):
            try:
                # Start transaction
                self.cursor.execute("BEGIN EXCLUSIVE TRANSACTION")

                # Delete existing fingerprints for this track
                self.cursor.execute("DELETE FROM fingerprints WHERE track_id = ?", (track_id,))

                # Insert in small chunks
                for i in range(0, len(fingerprints), MAX_BATCH_SIZE):
                    chunk = fingerprints[i:i + MAX_BATCH_SIZE]
                    data = [(fp[0], track_id, fp[1]) for fp in chunk]

                    self.cursor.executemany(
                        "INSERT INTO fingerprints (hash, track_id, time_offset) VALUES (?, ?, ?)",
                        data
                    )

                    # Commit after EACH chunk
                    self.conn.commit()

                    # Brief pause to prevent overload
                    if i + MAX_BATCH_SIZE < len(fingerprints):
                        time.sleep(0.01)
                        self.cursor.execute("BEGIN EXCLUSIVE TRANSACTION")

                # Update count
                self.cursor.execute(
                    "UPDATE tracks SET fingerprint_count = ? WHERE id = ?",
                    (len(fingerprints), track_id)
                )

                self.conn.commit()
                print(f'Added {len(fingerprints)} fingerprints for track {track_id}')
                return

            except sqlite3.DatabaseError as e:
                self.conn.rollback()
                print(f'Attempt {attempt + 1} failed: {e}')

                if attempt < MAX_RETRIES - 1:
                    time.sleep(1)
                    # Check database integrity
                    try:
                        result = self.cursor.execute("PRAGMA integrity_check").fetchone()
                        if result[0] != 'ok':
                            raise Exception("Database corrupted!")
                    except:
                        raise
                else:
                    raise

    def find_matches(self, query_hashes: list[tuple]) -> list[tuple]:
        """ Find matches from the query hashes with the confidence scores. """
        if not query_hashes:
            return []

        start_time = time.time()

        # Create hash lookup
        hash_to_times = defaultdict(list)
        for hash_val, time_offset in query_hashes:
            hash_to_times[hash_val].append(time_offset)

        unique_hashes = list(hash_to_times.keys())
        print(f'Searching for {len(unique_hashes)} unique hashes from {len(query_hashes)} total')

        if len(unique_hashes) > 1000:
            matches = self._find_matches_temp_table(hash_to_times)
        else:
            matches = self._find_matches_batched(hash_to_times)

        results = self._process_matches(matches, hash_to_times, len(query_hashes))

        elapsed = time.time() - start_time
        print(f'Match completed in {elapsed:.3f} seconds')

        return results

    def _find_matches_temp_table(self, hash_to_times: dict) -> list[tuple]:
        """ Use a temporary table to find matches. """
        self.cursor.execute("""
            CREATE TEMP TABLE IF NOT EXISTS query_hashes(
                hash INTEGER PRIMARY KEY
            )
        """)

        # Clear and populate temp table
        self.cursor.execute("DELETE FROM query_hashes")
        self.cursor.executemany(
            "INSERT INTO query_hashes (hash) VALUES (?)",
            [(h,) for h in hash_to_times.keys()]
        )

        self.cursor.execute("""
            SELECT f.hash, f.track_id, f.time_offset
            FROM fingerprints f
            INNER JOIN query_hashes q ON f.hash = q.hash
            ORDER BY f.track_id, f.hash
        """)

        return self.cursor.fetchall()

    def _find_matches_batched(self, hash_to_times: dict) -> list[tuple]:
        """ Batched processing for smaller hash sets. """
        all_matches = []
        unique_hashes = list(hash_to_times.keys())

        BATCH_SIZE = 500
        for i in range(0, len(unique_hashes), BATCH_SIZE):
            batch = unique_hashes[i:i + BATCH_SIZE]
            placeholders = ','.join('?' * len(batch))

            self.cursor.execute("""
                SELECT hash, track_id, time_offset
                FROM fingerprints
                WHERE hash in ({placeholders})
                ORDER BY track_id, hash
            """, batch)

            all_matches.extend(self.cursor.fetchall())

        return all_matches

    def _process_matches(self, matches: list, hash_to_times: dict, total_query_hashes: int) -> list[tuple]:
        """ Process matches to find best tracks. """
        track_time_diffs = defaultdict(list)

        for match in matches:
            hash_val = match['hash']
            track_id = match['track_id']
            db_time = match['time_offset']

            # Calculate time differences for all query occurrences of this hash
            for query_time in hash_to_times[hash_val]:
                time_diff = db_time - query_time
                track_time_diffs[track_id].append(time_diff)

        track_scores = []
        for track_id, time_diffs in track_time_diffs.items():
            if len(time_diffs) < self.config.min_absolute_matches:
                continue

            # Count occurrences of each time difference
            diff_counts = Counter(time_diffs)
            most_common_diff, aligned_count = diff_counts.most_common(1)[0]

            # Calculate confidence
            # This score is how many matches align with the same time offset
            alignment_score = aligned_count / len(time_diffs)

            # What percentage of the query matches
            coverage_score = aligned_count / total_query_hashes

            confidence = (alignment_score * 0.6 + coverage_score * 0.4)

            if aligned_count > 100:
                confidence *= 1.2
            elif aligned_count > 50:
                confidence *= 1.1

            confidence = min(confidence, 1.0)

            if confidence >= self.config.min_match_confidence:
                track_scores.append((track_id, confidence, aligned_count, most_common_diff))

        track_scores.sort(key=lambda x: (x[1], x[2]), reverse=True)

        results = []
        for track_id, confidence, match_count, time_offset in track_scores[:10]:
            track_info = self.get_track(track_id)
            if track_info:
                print(f'Track {track_id} matched {match_count} with confidence {confidence}')
                results.append((track_info, confidence))

        return results

    def get_stats(self) -> dict:
        if self._stats_cache and (time.time() - self._cache_time) < 60:
            return self._stats_cache

        stats = {}

        self.cursor.execute("""
            SELECT 
                (SELECT COUNT(*) FROM tracks) as total_tracks,
                (SELECT COUNT(*) FROM fingerprints) as total_fingerprints,
                (SELECT COUNT(DISTINCT hash) FROM fingerprints) as unique_hashes,
                (SELECT SUM(fingerprint_count) FROM tracks) as total_fps_from_tracks,
                (SELECT COUNT(DISTINCT album) FROM tracks) as total_albums,
                (SELECT COUNT(DISTINCT artist) FROM tracks) as total_artists,
                (SELECT MAX(disc_number) FROM tracks) as max_disc_number,
                (SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()) as db_size
        """)

        row = self.cursor.fetchone()

        stats['total_tracks'] = row['total_tracks']
        stats['total_fingerprints'] = row['total_fingerprints']
        stats['unique_hashes'] = row['unique_hashes']
        stats['total_albums'] = row['total_albums']
        stats['total_artists'] = row['total_artists']
        stats['max_disc_number'] = row['max_disc_number'] or 1
        stats['db_size_mb'] = row['db_size'] / 1024 / 1024

        if stats['total_tracks'] > 0:
            stats['avg_fingerprints_per_track'] = stats['total_fingerprints'] / stats['total_tracks']
        else:
            stats['avg_fingerprints_per_track'] = 0

        self._stats_cache = stats
        self._cache_time = time.time()

        return stats

    def optimize_database(self):
        """ Optimize database for best performance. """
        print("Optimizing database...")

        self.cursor.executescript("""
            ANALYZE;
            VACUUM;
            PRAGMA optimize;
        """)

        print("Database optimization complete")

    def checkpoint(self):
        """ Force write to disk. """
        self.cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def vacuum(self):
        """ Clean up database. """
        self.cursor.execute("VACUUM")

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.conn.commit()

        self.conn.close()
