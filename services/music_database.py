from dataclasses import fields
import sqlite3

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from models import Config, TrackInfo


class MusicDatabase:
    def __init__(self, config: Config):
        self.config = config

        # SQLite setup
        self.conn = sqlite3.connect(config.db_path)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()

        self.cursor.execute("PRAGMA foreign_keys = ON")

        self.setup()

    def setup(self):
        """ Creates all tables and indexes. """
        try:
            self._create_tables()
        except sqlite3.Error as e:
            print(f'Database error: {e}')
            raise

    def _create_tables(self):
        """ Creates all tables if they don't exist. """
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS tracks(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                album TEXT,
                track_number INTEGER,
                total_tracks INTEGER,
                duration INTEGER NOT NULL,
                audio_file_path TEXT NOT NULL,
                album_art_path TEXT,
                lyrics_file_path TEXT,
                date_added DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS fingerprints (
                hash TEXT NOT NULL,
                track_id INTEGER NOT NULL,
                time_offset INTEGER NOT NULL,
                FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
            )
        ''')

        self.cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_fingerprint_hash ON fingerprints(hash)
        ''')

        self.conn.commit()

    def add_track(self, metadata: TrackInfo) -> int:
        """ Adds a new track to the database. """
        if self.track_exists(metadata.title, metadata.artist, metadata.album):
            print(f'Track {metadata.title} by {metadata.artist} already exists')
            return -1

        query = ("INSERT INTO tracks (title, artist, album, duration, audio_file_path, album_art_path, "
                 "lyrics_file_path, track_number, total_tracks) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)")
        params = [metadata.title, metadata.artist, metadata.album, metadata.duration, metadata.audio_file_path,
                  metadata.album_art_path, metadata.lyrics_file_path, metadata.track_number, metadata.total_tracks]

        self.cursor.execute(query, params)
        self.conn.commit()
        return self.cursor.lastrowid

    def delete_track(self, track_id: int) -> None:
        """ Deletes a track from the database. """
        query = "DELETE FROM tracks WHERE id = ?"

        self.cursor.execute(query, (track_id,))
        self.conn.commit()

    def get_track(self, track_id: int) -> TrackInfo:
        """ Gets a track from the database. """
        query = "SELECT * FROM tracks WHERE id = ?"

        self.cursor.execute(query, (track_id,))
        row = self.cursor.fetchone()

        return TrackInfo(
            title=row['title'],
            artist=row['artist'],
            album=row['album'],
            duration=row['duration'],
            audio_file_path=row['audio_file_path'],
            album_art_path=row['album_art_path'],
            lyrics_file_path=row['lyrics_file_path'],
            track_number=row['track_number'],
            total_tracks=row['total_tracks']
        )

    def update_track(self, track_id: int, updates: dict) -> None:
        """ Updates a track in the database with fields dictated in updates dictionary. """
        if not updates:
            return

        ALLOWED_FIELDS = set([field.name for field in fields(TrackInfo)])

        valid_updates = {k : v for k, v in updates.items() if k in ALLOWED_FIELDS}

        if not valid_updates:
            raise ValueError('No valid fields to update')

        invalid_keys = set(updates.keys()) - ALLOWED_FIELDS
        if invalid_keys:
            print(f'Warning: Invalid fields: {invalid_keys}')

        # Dynamically make a update clause based on valid inputs
        set_clauses = [f'{key} = ?' for key in valid_updates.keys()]
        query = f"UPDATE tracks SET {', '.join(set_clauses)} WHERE id = ?"
        params = list(valid_updates.values()) + [track_id]

        self.cursor.execute(query, params)
        self.conn.commit()

    def track_exists(self, title: str, artist: str = None, album: str = None) -> bool:
        """ Check if a track exists in the database. """
        query = "SELECT EXISTS(SELECT 1 FROM tracks WHERE title = ? AND artist = ?"
        params = [title, artist]

        if album is not None:
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
                total_tracks=row['total_tracks']
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

    def find_matches(self, query_hashes: list[tuple]) -> list[tuple[TrackInfo, float]]:
        """ Find matches from the query hashes with the confidence scores. """
        if not query_hashes:
            return []

        hash_values = [h[0] for h in query_hashes]

        placeholders = ','.join('?' * len(hash_values))
        sql = f"""
            SELECT hash, track_id, time_offset 
            FROM fingerprints
            WHERE hash IN ({placeholders})
        """

        self.cursor.execute(sql, hash_values)
        matches = self.cursor.fetchall()

        # First, let's store matches by track
        track_matches = {}
        track_total_matches = {}
        for db_match in matches:
            track_id = db_match['track_id']
            db_time = db_match['time_offset']

            track_total_matches[track_id] = track_total_matches.get(track_id, 0) + 1

            for query_hash, query_time in query_hashes:
                if query_hash == db_match['hash']:
                    time_diff = int(db_time) - int(query_time)

                    if track_id not in track_matches:
                        track_matches[track_id] = {}

                    if time_diff not in track_matches[track_id]:
                        track_matches[track_id][time_diff] = []

                    # We are grouping by time difference
                    track_matches[track_id][time_diff].append((db_time, query_time))
                    break

        track_scores = []
        for track_id, time_diffs in track_matches.items():
            # Get the time_diff with the most matches
            best_diff = max(time_diffs.keys(), key=lambda d: len(time_diffs[d]))
            aligned_matches = time_diffs[best_diff]

            if len(aligned_matches) < self.config.min_absolute_matches:
                continue

            # Calculate confidence
            confidence = self._calculate_match_confidence(
                aligned_matches=len(aligned_matches),
                total_query_hashes=len(query_hashes),
                total_db_matches=track_total_matches[track_id],
                time_spread=max(m[1] for m in aligned_matches) - min(m[1] for m in aligned_matches)
            )

            track_scores.append((track_id, confidence, best_diff))

        # Filter by minimum confidence
        valid_matches = [t for t in track_scores if t[1] >= self.config.min_match_confidence]

        # Sort by confidence
        valid_matches.sort(key=lambda x: x[1], reverse=True)

        # Load track info
        results = []
        for track_id, confidence, best_diff in valid_matches:
            track_info = self.get_track(track_id)
            if track_info:
                results.append((track_info, confidence))

        return results

    def _calculate_match_confidence(self, aligned_matches: int,
                                    total_query_hashes: int,
                                    total_db_matches: int,
                                    time_spread: float = 0) -> float:
        """ Calculate the confidence score of the matches based on time consistency. """
        match_rate = aligned_matches / total_query_hashes

        # What % of found matches are properly aligned
        alignment_quality = aligned_matches / total_db_matches

        # Penalize poor judgment
        if alignment_quality < 0.5:
            match_rate *= 0.5
        elif alignment_quality > 0.8:
            match_rate *= 1.15

        # Absolute match bonus / penalty
        if aligned_matches > 20:
            match_rate *= 1.2
        elif aligned_matches < 5:
            match_rate *= 0.5

        # Time spread bonus
        if time_spread > 100:
            match_rate *= 1.1

        return min(match_rate, 1.0)

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.conn.commit()

        self.conn.close()
