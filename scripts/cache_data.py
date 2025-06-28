"""
Enhanced music collection cache with improved album disambiguation.
Handles singles vs albums, standard vs deluxe editions intelligently.
"""

import os
import json
import sqlite3
from pathlib import Path
import acoustid
import musicbrainzngs
import requests
import logging
import re
import time
from collections import defaultdict
from typing import Dict, List, Tuple, Optional, Set

# Configure logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)
logging.getLogger('musicbrainzngs').setLevel(logging.ERROR)

# Configure MusicBrainz
musicbrainzngs.set_useragent("Music_Kiosk", "1.0", os.getenv("MUSIC_BRAINZ_EMAIL", "example@email.com"))


class AlbumCandidate:
    """ Represents a potential album for a set of tracks. """

    def __init__(self, release_id: str, release_data: dict):
        self.release_id = release_id
        self.title = release_data.get('title', '')
        self.artist = release_data.get('artist-credit-phrase', '')
        self.release_type = release_data.get('release-group', {}).get('type', '')
        self.track_count = sum(m.get('track-count', 0) for m in release_data.get('medium-list', []))
        self.date = release_data.get('date', '')
        self.country = release_data.get('country', '')
        self.is_deluxe = any(word in self.title.lower() for word in ['deluxe', 'special', 'expanded', 'anniversary'])

        # Track recording IDs in this release
        self.recording_ids = set()
        self.track_info = {}  # recording_id -> {track_number, disc_number, title}

        for medium in release_data.get('medium-list', []):
            disc_num = medium.get('position', 1)
            for track in medium.get('track-list', []):
                rec_id = track.get('recording', {}).get('id')
                if rec_id:
                    self.recording_ids.add(rec_id)
                    self.track_info[rec_id] = {
                        'track_number': int(track.get('position', 0)),
                        'disc_number': disc_num,
                        'title': track.get('title', ''),
                        'length': track.get('length', 0)
                    }

    def get_exclusivity_score(self, all_candidates: List['AlbumCandidate']) -> int:
        """ Calculate how many exclusive tracks this release has. """
        exclusive_tracks = self.recording_ids.copy()
        for other in all_candidates:
            if other.release_id != self.release_id:
                exclusive_tracks -= other.recording_ids
        return len(exclusive_tracks)

    def get_preference_score(self) -> int:
        """ Calculate preference score for this release. """
        score = 0

        # Strongly prefer albums over singles / EPs
        if self.release_type == 'Album':
            score += 1000
        elif self.release_type == 'EP':
            score += 200
        elif self.release_type == 'Single':
            score -= 500

        # Prefer deluxe / special editions
        if self.is_deluxe:
            score += 300

        # Prefer releases with more tracks
        score += self.track_count * 10

        # Slight preference for more recent releases
        if self.date:
            try:
                year = int(self.date[:4])
                score += (year - 1990) * 2  # Small boost for newer releases
            except:
                pass

        return score


class TrackFingerprint:
    """ Represents a fingerprinted track with all its potential metadata. """

    def __init__(self, fingerprint: str, duration: int, file_path: str):
        self.fingerprint = fingerprint
        self.duration = duration
        self.file_path = Path(file_path)
        self.filename = self.file_path.stem

        # AcoustID results
        self.acoustid_results = []  # List of (score, recording_id, title, artist)

        # All possible releases this track appears on
        self.release_candidates = {}  # release_id -> AlbumCandidate

        # Selected metadata
        self.selected_release_id = None
        self.selected_recording_id = None
        self.metadata = {}


class MusicCollectionCache:
    def __init__(self, acoustid_api_key: str, cache_db: str = "music_collection.db"):
        self.api_key = acoustid_api_key
        self.cache_db = cache_db
        self._init_database()
        self._load_album_overrides()

        # Track fingerprints being processed in current batch
        self.current_batch = {}  # fingerprint -> TrackFingerprint
        self.release_cache = {}  # release_id -> AlbumCandidate

    def _init_database(self):
        """ Initialize cache database with enhanced schema. """
        conn = sqlite3.connect(self.cache_db)
        cursor = conn.cursor()

        # Enhanced tracks table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT UNIQUE,
                acoustid_id TEXT,
                recording_id TEXT,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                album TEXT,
                album_mbid TEXT,
                release_type TEXT,
                duration INTEGER,
                track_number INTEGER,
                disc_number INTEGER DEFAULT 1,
                total_tracks INTEGER,
                year INTEGER,
                genres TEXT,
                album_art_url TEXT,
                album_art_local TEXT,
                lyrics_local TEXT,
                metadata JSON,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_played TIMESTAMP,
                play_count INTEGER DEFAULT 0,
                confidence REAL
            )
        """)

        # Album consolidation tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS album_consolidation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                base_album_name TEXT,
                artist TEXT,
                selected_release_id TEXT,
                selected_album_name TEXT,
                consolidation_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(base_album_name, artist)
            )
        """)

        # Create indexes for performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fingerprint ON tracks(fingerprint)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_album_artist ON tracks(album, artist)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_recording_id ON tracks(recording_id)")

        conn.commit()
        conn.close()

    def _load_album_overrides(self):
        """ Load manual album override data for fixing singles/album mismatches. """
        override_file = Path("album_overrides.json")
        if override_file.exists():
            with open(override_file) as f:
                self.album_overrides = json.load(f)
        else:
            self.album_overrides = {}

    def process_album_batch(self, audio_files: List[str], force_album: Optional[str] = None,
                            collection_name: str = "My Vinyl") -> Dict[str, any]:
        """
        Process a batch of audio files that should belong to the same album.
        Enhanced to track outliers throughout the process.
        """
        print(f"\nProcessing batch of {len(audio_files)} files")

        # Reset batch state
        self.current_batch = {}
        self.release_cache = {}
        self.majority_artist = None  # Reset majority artist

        # Step 1: Fingerprint all files
        print("\nStep 1: Fingerprinting all files...")
        for audio_file in audio_files:
            try:
                duration, fingerprint = acoustid.fingerprint_file(audio_file)
                track_fp = TrackFingerprint(fingerprint, duration, audio_file)
                track_fp.is_outlier = False  # Initialize outlier flag
                self.current_batch[fingerprint] = track_fp
                print(f"  ✓ {Path(audio_file).name}")
            except Exception as e:
                print(f"  ✗ {Path(audio_file).name}: {e}")

        # Step 2: Get AcoustID matches for all tracks
        print(f"\nStep 2: Getting AcoustID matches for {len(self.current_batch)} tracks...")
        for fp_hash, track_fp in self.current_batch.items():
            self._get_acoustid_matches(track_fp)
            time.sleep(0.1)  # Rate limiting

        # Step 3: Detect and retry outliers (enhanced version)
        print("\nStep 3: Checking for outlier tracks...")
        self._detect_and_retry_outliers()

        # Step 4: Fetch all release candidates
        print("\nStep 4: Fetching release information...")
        self._fetch_all_release_candidates()

        # Step 5: Determine the best album (enhanced version)
        print("\nStep 5: Determining best album match...")
        selected_release = self._determine_best_album(force_album)

        if selected_release:
            print(f"\n✓ Selected album: {selected_release.title}")
            print(f"  Type: {selected_release.release_type}")
            print(f"  Tracks: {selected_release.track_count}")
            print(f"  Artist: {selected_release.artist}")

            # Step 6: Apply metadata and store
            print("\nStep 6: Storing tracks with correct metadata...")
            self._apply_and_store_album_metadata(selected_release, collection_name)

            # Step 7: Fix any previously stored singles from this album
            print("\nStep 7: Checking for singles to consolidate...")
            self._consolidate_existing_singles(selected_release)
        else:
            print("\n✗ Could not determine album. Storing as individual tracks...")
            self._store_as_individual_tracks(collection_name)

        # Print summary
        self.print_statistics()

        return {
            'processed': len(self.current_batch),
            'selected_album': selected_release.title if selected_release else None,
            'selected_release_id': selected_release.release_id if selected_release else None
        }

    def _get_acoustid_matches(self, track_fp: TrackFingerprint):
        """ Get AcoustID matches for a track. """
        try:
            results = acoustid.match(self.api_key, track_fp.file_path)

            for score, recording_id, title, artist in results:
                if score > 0.5:  # Only consider good matches
                    track_fp.acoustid_results.append((score, recording_id, title, artist))

                    # Basic filename sanity check
                    filename_base = track_fp.filename.lower()
                    matched_title = title.lower()

                    # Skip if completely different (unless override is in place)
                    if not any(word in matched_title for word in filename_base.split()[:3]) and \
                            not any(word in filename_base for word in matched_title.split()[:3]):
                        continue

                    print(f"  → {title} by {artist} [{score:.0%}]")

                    # Only process the best match initially
                    if len(track_fp.acoustid_results) == 1:
                        track_fp.selected_recording_id = recording_id

        except Exception as e:
            print(f"  Error getting matches: {e}")

    def _detect_and_retry_outliers(self):
        """
        Detect tracks that seem to be from a different album/artist and retry them.
        Enhanced to mark outliers for special handling during album selection.
        """
        # First, get the most common artist across all tracks
        artist_counts = defaultdict(int)
        normalized_to_original = defaultdict(list)  # normalized -> [original strings]

        for track_fp in self.current_batch.values():
            if track_fp.acoustid_results:
                # Look at the best match
                _, _, title, artist = track_fp.acoustid_results[0]

                # Normalize the artist to get the primary artist
                normalized_artist = self._get_primary_artist(artist)
                artist_counts[normalized_artist] += 1
                normalized_to_original[normalized_artist].append(artist)

        if not artist_counts:
            return

        # Find the most common artist (majority)
        most_common_artist = max(artist_counts.items(), key=lambda x: x[1])[0]
        artist_threshold = len(self.current_batch) * 0.6  # At least 60% should be same artist

        if artist_counts[most_common_artist] < artist_threshold:
            print("  Warning: No clear majority artist found")
            return

        # Show all variations of the majority artist
        variations = set(normalized_to_original[most_common_artist])
        print(
            f"  Majority artist: {most_common_artist} ({artist_counts[most_common_artist]}/{len(self.current_batch)} tracks)")
        if len(variations) > 1:
            print(f"  Artist variations found: {', '.join(sorted(variations))}")

        # Store the majority artist for later use
        self.majority_artist = most_common_artist

        # Now check for outliers
        outliers = []
        for fp_hash, track_fp in self.current_batch.items():
            if not track_fp.acoustid_results:
                continue

            # Get the current best match
            score, recording_id, title, artist = track_fp.acoustid_results[0]

            # Normalize to primary artist for comparison
            normalized_artist = self._get_primary_artist(artist)

            # Is this a different artist?
            if normalized_artist != most_common_artist:
                print(f"  ⚠ Outlier detected: {track_fp.filename}")
                print(f"    Expected artist: {most_common_artist}")
                print(f"    Got: {title} by {artist}")
                outliers.append((fp_hash, track_fp))

        # Retry outliers with alternative matches
        for fp_hash, track_fp in outliers:
            print(f"\n  Retrying {track_fp.filename}...")

            # Mark this track as an outlier that was retried
            track_fp.is_outlier = True

            # Look for alternative matches in the acoustid results
            found_alternative = False

            for i, (score, recording_id, title, artist) in enumerate(track_fp.acoustid_results[1:], 1):
                normalized_alt = self._get_primary_artist(artist)
                if normalized_alt == most_common_artist:
                    print(f"    ✓ Found alternative match: {title} by {artist} [{score:.0%}]")
                    # Update to use this recording instead
                    track_fp.selected_recording_id = recording_id
                    # Move this to be the primary result
                    track_fp.acoustid_results[0], track_fp.acoustid_results[i] = \
                        track_fp.acoustid_results[i], track_fp.acoustid_results[0]
                    found_alternative = True
                    break

            if not found_alternative:
                # Try a more aggressive filename-based search
                print(f"    No alternative found in AcoustID results")

                # Check if the filename suggests it should match
                filename_words = set(track_fp.filename.lower().split())
                if len(filename_words) > 2:  # Reasonable filename
                    # Look through ALL results more carefully
                    for score, recording_id, title, artist in track_fp.acoustid_results:
                        title_words = set(title.lower().split())
                        # If we have significant word overlap, consider it
                        if len(filename_words & title_words) >= 2:
                            print(f"    ✓ Found filename-based match: {title} by {artist}")
                            track_fp.selected_recording_id = recording_id
                            track_fp.is_outlier = True
                            break

    def _get_primary_artist(self, artist_string: str) -> str:
        """
        Extract the primary artist from a string that may contain features.
        'Jim Bob feat. John Doe' -> 'jim bob'
        'Jim Bob & The Band feat. Someone' -> 'jim bob'
        """
        # Lowercase for comparison
        artist = artist_string.lower()

        # Remove featured artists - try multiple patterns
        patterns = [
            r'\s*\(?feat\..*$',
            r'\s*\(?featuring.*$',
            r'\s*\(?ft\..*$',
            r'\s*\(?with\s+.*$',
            r'\s*\[feat\..*\]$',
            r'\s*\[featuring.*\]$',
        ]

        for pattern in patterns:
            artist = re.sub(pattern, '', artist, flags=re.IGNORECASE)

        # Handle "Artist1 & Artist2" by taking the first part
        # But preserve "Artist & The Band" or "Artist & His Orchestra"
        if ' & ' in artist:
            parts = artist.split(' & ')
            # If the second part starts with "the" or "his/her", it's likely part of the band name
            if len(parts) == 2 and not any(parts[1].strip().startswith(word) for word in ['the', 'his', 'her']):
                artist = parts[0]

        # Remove "the" at the beginning for better matching
        if artist.startswith('the '):
            artist = artist[4:]

        # Clean up and normalize
        artist = artist.strip()
        artist = re.sub(r'\s+', ' ', artist)  # Multiple spaces to single

        return artist

    def _is_similar_artist(self, artist1: str, artist2: str) -> bool:
        """
        Check if two artist names are similar (handles variations like 'feat.' etc.).
        """
        # Use the same normalization as _get_primary_artist
        norm1 = self._get_primary_artist(artist1)
        norm2 = self._get_primary_artist(artist2)

        # Exact match after normalization
        if norm1 == norm2:
            return True

        # One contains the other (for cases like "Artist" vs "Artist & Band")
        if norm1 in norm2 or norm2 in norm1:
            return True

        return False

    def _fetch_all_release_candidates(self):
        """Fetch all unique releases that contain our tracks."""
        all_releases = set()

        # Collect all release IDs
        for track_fp in self.current_batch.values():
            if track_fp.selected_recording_id:
                try:
                    # Get recording with releases
                    result = musicbrainzngs.get_recording_by_id(
                        track_fp.selected_recording_id,
                        includes=['releases', 'artists']
                    )

                    recording = result['recording']

                    # Add all releases
                    for release in recording.get('release-list', []):
                        release_id = release.get('id')
                        if release_id:
                            all_releases.add(release_id)

                except Exception as e:
                    print(f"  Error fetching recording {track_fp.selected_recording_id}: {e}")

                time.sleep(0.2)  # Rate limiting

        # Fetch detailed info for each release
        print(f"  Found {len(all_releases)} unique releases to analyze")

        for release_id in all_releases:
            if release_id not in self.release_cache:
                try:
                    result = musicbrainzngs.get_release_by_id(
                        release_id,
                        includes=['recordings', 'release-groups', 'media', 'artist-credits']
                    )

                    release_data = result['release']
                    candidate = AlbumCandidate(release_id, release_data)
                    self.release_cache[release_id] = candidate

                    # Link to tracks
                    for track_fp in self.current_batch.values():
                        if track_fp.selected_recording_id in candidate.recording_ids:
                            track_fp.release_candidates[release_id] = candidate

                    time.sleep(0.2)  # Rate limiting

                except Exception as e:
                    print(f"  Error fetching release {release_id}: {e}")

    def _get_majority_artist(self) -> Optional[str]:
        """
        Get the majority artist from current batch, if there is one.
        Returns normalized artist name or None.
        """
        artist_counts = defaultdict(int)

        for track_fp in self.current_batch.values():
            if track_fp.acoustid_results:
                _, _, _, artist = track_fp.acoustid_results[0]
                normalized_artist = self._get_primary_artist(artist)
                artist_counts[normalized_artist] += 1

        if not artist_counts:
            return None

        # Find the most common artist
        most_common_artist, count = max(artist_counts.items(), key=lambda x: x[1])

        # Need at least 60% to be considered majority
        if count >= len(self.current_batch) * 0.6:
            return most_common_artist

        return None

    def _determine_best_album(self, force_album: Optional[str] = None) -> Optional[AlbumCandidate]:
        """
        Determine the best album for the batch of tracks.
        Enhanced to better handle outliers and avoid compilation albums.
        """
        if not self.release_cache:
            return None

        candidates = list(self.release_cache.values())

        # Filter to only album releases (not singles)
        album_candidates = [c for c in candidates if c.release_type in ['Album', 'EP']]

        if not album_candidates:
            print("  No album releases found, only singles")
            return None

        # Get majority artist (use stored value or recalculate)
        majority_artist = getattr(self, 'majority_artist', None) or self._get_majority_artist()

        # Count how many non-outlier tracks appear on each album
        non_outlier_coverage = defaultdict(int)
        outlier_coverage = defaultdict(int)

        for track_fp in self.current_batch.values():
            is_outlier = getattr(track_fp, 'is_outlier', False)
            for release_id in track_fp.release_candidates:
                if is_outlier:
                    outlier_coverage[release_id] += 1
                else:
                    non_outlier_coverage[release_id] += 1

        # Calculate scores
        scores = {}

        for candidate in album_candidates:
            score = 0

            # CRITICAL: Check if album artist matches our majority artist
            if majority_artist:
                candidate_primary_artist = self._get_primary_artist(candidate.artist)

                # Heavy penalty for Various Artists or mismatched artists
                if candidate.artist.lower() == 'various artists':
                    score -= 10000  # Massive penalty for compilation albums
                    print(f"  {candidate.title}: Penalized as Various Artists compilation")
                elif candidate_primary_artist != majority_artist:
                    score -= 5000  # Big penalty for wrong artist
                    print(f"  {candidate.title}: Wrong artist ({candidate.artist} vs {majority_artist})")
                else:
                    score += 2000  # Bonus for matching artist

            # NEW: Heavily weight albums that contain most of our non-outlier tracks
            non_outlier_count = non_outlier_coverage.get(candidate.release_id, 0)
            outlier_count = outlier_coverage.get(candidate.release_id, 0)

            # Give massive bonus for albums containing multiple non-outlier tracks
            score += non_outlier_count * 1000

            # Only give small bonus for outlier tracks (they might be on many albums)
            score += outlier_count * 50

            # Penalty if this album ONLY contains outlier tracks (likely a compilation)
            if non_outlier_count == 0 and outlier_count > 0:
                score -= 3000
                print(f"  {candidate.title}: Penalized - only contains retried outlier tracks")

            # Bonus for albums that contain most of our tracks
            total_coverage = non_outlier_count + outlier_count
            coverage_percentage = total_coverage / len(self.current_batch)
            if coverage_percentage > 0.8:  # Contains 80%+ of our tracks
                score += 2000
                print(f"  {candidate.title}: Bonus for high coverage ({coverage_percentage:.0%})")

            # Original preference score (deluxe, type, etc.)
            score += candidate.get_preference_score()

            # Override score
            if force_album and force_album.lower() in candidate.title.lower():
                score += 5000

            # NEW: Penalize albums that seem to be compilations based on pattern
            compilation_keywords = ['greatest hits', 'best of', 'collection', 'anthology',
                                    'compilation', 'various', 'sampler', 'mixtape']
            if any(keyword in candidate.title.lower() for keyword in compilation_keywords):
                score -= 2000
                print(f"  {candidate.title}: Penalized as likely compilation")

            scores[candidate.release_id] = score

        # Sort by score
        sorted_candidates = sorted(album_candidates,
                                   key=lambda c: scores[c.release_id],
                                   reverse=True)

        if sorted_candidates:
            best = sorted_candidates[0]

            # Print decision reasoning
            print(f"\nAlbum selection scores:")
            for c in sorted_candidates[:5]:  # Top 5
                non_outlier = non_outlier_coverage.get(c.release_id, 0)
                outlier = outlier_coverage.get(c.release_id, 0)
                print(f"  {c.title} by {c.artist}: {scores[c.release_id]} points")
                print(f"    → {non_outlier} regular tracks, {outlier} outlier tracks")

            # Final sanity check: if the best album has very low coverage, warn
            best_coverage = (non_outlier_coverage.get(best.release_id, 0) +
                             outlier_coverage.get(best.release_id, 0))
            if best_coverage < len(self.current_batch) * 0.5:
                print(f"\n⚠ Warning: Selected album only contains {best_coverage}/{len(self.current_batch)} tracks")

            return best

        return None

    def _apply_and_store_album_metadata(self, album_candidate: AlbumCandidate,
                                        collection_name: str):
        """Apply the selected album metadata to all tracks and store them."""
        conn = sqlite3.connect(self.cache_db)
        cursor = conn.cursor()

        # Download album art once
        album_art_local = self._download_album_art(album_candidate.release_id)

        # Get the primary album artist (without features)
        album_primary_artist = self._get_primary_artist(album_candidate.artist)

        stored_count = 0
        missing_tracks = []

        for track_fp in self.current_batch.values():
            if not track_fp.selected_recording_id:
                continue

            # Get track info from this album
            track_info = album_candidate.track_info.get(track_fp.selected_recording_id)

            if not track_info:
                # Track not on this album - might be exclusive to another edition
                print(f"  ⚠ {track_fp.filename} not found on selected album")
                missing_tracks.append(track_fp)
                continue

            # Get the best match from acoustid results
            best_match = track_fp.acoustid_results[0] if track_fp.acoustid_results else None
            if not best_match:
                continue

            score, recording_id, title, artist = best_match

            # Use album artist if it's not a Various Artists compilation
            if album_candidate.artist.lower() != 'various artists':
                # Keep featured artists in the title but use album artist as primary
                if 'feat.' in artist.lower() or 'ft.' in artist.lower():
                    # Extract the featured part
                    featured_match = re.search(r'(\s+(?:feat\.|ft\.|featuring)\s+.+)$', artist, re.IGNORECASE)
                    if featured_match and featured_match.group(1).lower() not in title.lower():
                        title = f"{title}{featured_match.group(1)}"
                artist = album_candidate.artist

            # Prepare metadata
            metadata = {
                'recording_id': recording_id,
                'mbid': recording_id,
                'release_id': album_candidate.release_id,
                'release_type': album_candidate.release_type,
                'confidence': score,
                'duration': track_fp.duration,
                'country': album_candidate.country
            }

            # Store track
            cursor.execute("""
                INSERT OR REPLACE INTO tracks 
                (fingerprint, acoustid_id, recording_id, title, artist, album, album_mbid,
                 release_type, duration, track_number, disc_number, total_tracks, 
                 year, album_art_local, metadata, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                track_fp.fingerprint,
                recording_id,  # Using recording_id as acoustid_id for compatibility
                recording_id,
                title,
                artist,
                album_candidate.title,
                album_candidate.release_id,
                album_candidate.release_type,
                track_fp.duration,
                track_info['track_number'],
                track_info['disc_number'],
                album_candidate.track_count,
                int(album_candidate.date[:4]) if album_candidate.date else None,
                album_art_local,
                json.dumps(metadata),
                score
            ))

            stored_count += 1
            print(f"  ✓ Track {track_info['track_number']}: {title}")

        # Try to handle missing tracks
        if missing_tracks:
            print(f"\nAttempting to match {len(missing_tracks)} missing tracks...")
            matched = self._handle_missing_tracks(missing_tracks, album_candidate, album_art_local, cursor)
            stored_count += matched

        # Record this album consolidation
        base_album = self._get_base_album_name(album_candidate.title)
        cursor.execute("""
            INSERT OR REPLACE INTO album_consolidation
            (base_album_name, artist, selected_release_id, selected_album_name)
            VALUES (?, ?, ?, ?)
        """, (base_album, album_candidate.artist, album_candidate.release_id,
              album_candidate.title))

        conn.commit()
        conn.close()

        print(f"\nStored {stored_count} tracks")

    def _handle_missing_tracks(self, missing_tracks: List[TrackFingerprint],
                               album_candidate: AlbumCandidate, album_art_local: str,
                               cursor: sqlite3.Cursor) -> int:
        """
        Try to match missing tracks by looking at alternative results or track numbers.
        Returns the number of tracks successfully matched.
        """
        # First, check which track numbers are missing
        found_track_numbers = set()
        for track_info in album_candidate.track_info.values():
            found_track_numbers.add(track_info['track_number'])

        all_track_numbers = set(range(1, album_candidate.track_count + 1))
        missing_numbers = sorted(all_track_numbers - found_track_numbers)

        if missing_numbers:
            print(f"  Missing track numbers: {missing_numbers}")

        matched_count = 0

        # Try to match missing tracks
        for track_fp in missing_tracks:
            matched = False

            # Strategy 1: Check alternative AcoustID results
            for score, recording_id, title, artist in track_fp.acoustid_results:
                # Check if this alternative recording is on a different release by same artist
                if self._is_similar_artist(artist, album_candidate.artist):
                    print(f"  Trying alternative: {title} by {artist}")

                    # Try to get track number from filename if it follows a pattern
                    track_num = self._extract_track_number_from_filename(track_fp.filename)

                    if track_num and track_num in missing_numbers:
                        print(f"    → Assigning to track {track_num} based on filename")

                        # Store with inferred track number
                        metadata = {
                            'recording_id': recording_id,
                            'mbid': recording_id,
                            'release_id': album_candidate.release_id,
                            'release_type': album_candidate.release_type,
                            'confidence': score * 0.8,  # Lower confidence for inferred
                            'duration': track_fp.duration,
                            'inferred_track_number': True
                        }

                        cursor.execute("""
                            INSERT OR REPLACE INTO tracks 
                            (fingerprint, acoustid_id, recording_id, title, artist, album, album_mbid,
                             release_type, duration, track_number, disc_number, total_tracks, 
                             year, album_art_local, metadata, confidence)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            track_fp.fingerprint,
                            recording_id,
                            recording_id,
                            title,
                            album_candidate.artist,  # Use album's artist
                            album_candidate.title,
                            album_candidate.release_id,
                            album_candidate.release_type,
                            track_fp.duration,
                            track_num,
                            1,  # Assume disc 1
                            album_candidate.track_count,
                            int(album_candidate.date[:4]) if album_candidate.date else None,
                            album_art_local,
                            json.dumps(metadata),
                            score * 0.8
                        ))

                        matched = True
                        matched_count += 1
                        missing_numbers.remove(track_num)
                        print(f"    ✓ Matched as track {track_num}")
                        break

            if not matched:
                print(f"    ✗ Could not match {track_fp.filename} to album")

        return matched_count

    def _extract_track_number_from_filename(self, filename: str) -> Optional[int]:
        """
        Try to extract track number from filename.
        Handles patterns like: "01 - Song.mp3", "Track 01.mp3", "1. Song.mp3"
        """
        # Remove extension
        name = Path(filename).stem

        # Common patterns
        patterns = [
            r'^(\d{1,2})\s*[-\.\s]',  # "01 - " or "01. " or "01 "
            r'^track\s*(\d{1,2})',  # "Track 01"
            r'^\[(\d{1,2})\]',  # "[01]"
            r'^#(\d{1,2})\s',  # "#1 "
        ]

        for pattern in patterns:
            match = re.match(pattern, name, re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1))
                except:
                    pass

        return None

    def _consolidate_existing_singles(self, album_candidate: AlbumCandidate):
        """Find and update any singles that should be part of this album."""
        conn = sqlite3.connect(self.cache_db)
        cursor = conn.cursor()

        # Get the primary artist for comparison
        album_primary_artist = self._get_primary_artist(album_candidate.artist)

        # Find tracks by the same artist that might be singles from this album
        cursor.execute("""
            SELECT id, recording_id, title, artist, album, release_type
            FROM tracks
            WHERE (release_type = 'Single' OR album LIKE '%Single%' OR total_tracks <= 3)
        """)

        potential_singles = cursor.fetchall()
        consolidated = 0

        for track_id, recording_id, title, track_artist, current_album, release_type in potential_singles:
            # Check if this is the same primary artist
            track_primary_artist = self._get_primary_artist(track_artist)
            if track_primary_artist != album_primary_artist:
                continue

            # Check if this recording is on our album
            if recording_id in album_candidate.recording_ids:
                track_info = album_candidate.track_info[recording_id]

                print(f"  Converting single to album track: {title}")
                print(f"    Was: {current_album}")
                print(f"    Now: {album_candidate.title} (Track {track_info['track_number']})")

                # Update to album version
                cursor.execute("""
                    UPDATE tracks
                    SET album = ?, album_mbid = ?, release_type = ?,
                        track_number = ?, disc_number = ?, total_tracks = ?,
                        album_art_local = ?, artist = ?
                    WHERE id = ?
                """, (
                    album_candidate.title,
                    album_candidate.release_id,
                    album_candidate.release_type,
                    track_info['track_number'],
                    track_info['disc_number'],
                    album_candidate.track_count,
                    self._download_album_art(album_candidate.release_id),
                    album_candidate.artist,  # Use album artist for consistency
                    track_id
                ))

                consolidated += 1

        if consolidated > 0:
            conn.commit()
            print(f"\n✓ Consolidated {consolidated} singles into album")

        conn.close()

    def _store_as_individual_tracks(self, collection_name: str):
        """Fallback: store tracks individually when album can't be determined."""
        for track_fp in self.current_batch.values():
            if track_fp.acoustid_results:
                # Just use the first (best) match
                score, recording_id, title, artist = track_fp.acoustid_results[0]

                # Get basic metadata
                metadata = self._fetch_full_metadata(recording_id)

                # Store with whatever metadata we have
                self._store_track(
                    title=title,
                    artist=artist,
                    metadata=metadata,
                    album_art_local=None,
                    collection_name=collection_name,
                    fingerprint=track_fp.fingerprint,
                    acoustid_id=recording_id
                )

    def cache_album_directory(self, album_dir: str, album_name: str = None,
                              collection_name: str = "My Vinyl"):
        """Cache an entire album directory using batch processing."""
        album_path = Path(album_dir)
        if not album_path.is_dir():
            print(f"Error: {album_dir} is not a directory")
            return

        # Find all audio files
        audio_files = []
        for ext in ['*.mp3', '*.flac', '*.wav', '*.m4a']:
            audio_files.extend(album_path.glob(ext))

        # Sort by filename to maintain track order
        audio_files.sort()

        if not audio_files:
            print(f"No audio files found in {album_dir}")
            return

        # Convert to string paths
        audio_file_paths = [str(f) for f in audio_files]

        # Process as a batch
        return self.process_album_batch(audio_file_paths, force_album=album_name,
                                        collection_name=collection_name)

    # Helper methods
    def _get_base_album_name(self, album_name: str) -> str:
        """Extract base album name without edition suffixes."""
        pattern = r'\s*[\(\[]?(deluxe|special|expanded|anniversary|remaster|edition|version|bonus|collector).*?[\)\]]?\s*$'
        base_name = re.sub(pattern, '', album_name, flags=re.IGNORECASE).strip()
        base_name = re.sub(r'\s*[-:]\s*$', '', base_name).strip()
        return base_name

    def _download_album_art(self, album_mbid: str) -> str:
        """Download album art from Cover Art Archive."""
        try:
            art_dir = Path("album_art")
            art_dir.mkdir(exist_ok=True)

            local_path = art_dir / f"{album_mbid}.jpg"

            if local_path.exists():
                return str(local_path)

            urls = [
                f"https://coverartarchive.org/release/{album_mbid}/front-500",
                f"https://coverartarchive.org/release/{album_mbid}/front",
                f"https://coverartarchive.org/release/{album_mbid}/front-250",
            ]

            for url in urls:
                try:
                    response = requests.get(url, timeout=10)
                    if response.status_code == 200:
                        with open(local_path, 'wb') as f:
                            f.write(response.content)
                        print(f"  Downloaded album art ({local_path.stat().st_size // 1024}KB)")
                        return str(local_path)
                except requests.RequestException:
                    continue

        except Exception as e:
            print(f"  Could not download album art: {e}")

        return None

    def _fetch_full_metadata(self, recording_id: str) -> dict:
        """Fetch basic metadata for a recording (fallback method)."""
        try:
            result = musicbrainzngs.get_recording_by_id(
                recording_id,
                includes=['artists', 'releases', 'tags']
            )

            recording = result['recording']
            metadata = {
                'mbid': recording.get('id'),
                'title': recording.get('title'),
                'duration': int(recording.get('length', 0)) // 1000 if recording.get('length') else 0,
            }

            # Get first release info
            if 'release-list' in recording and recording['release-list']:
                release = recording['release-list'][0]
                metadata['album'] = release.get('title')
                metadata['album_mbid'] = release.get('id')

            return metadata

        except Exception as e:
            logger.exception("MusicBrainz API error")
            return {}

    def _store_track(self, title: str, artist: str, metadata: dict,
                     album_art_local: str, collection_name: str,
                     fingerprint: str, acoustid_id: str):
        """Store a single track (compatibility method)."""
        conn = sqlite3.connect(self.cache_db)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO tracks 
            (fingerprint, acoustid_id, recording_id, title, artist, album, album_mbid, 
             duration, track_number, total_tracks, year, genres, 
             album_art_local, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            fingerprint,
            acoustid_id,
            metadata.get('mbid'),  # This is the recording_id
            title,
            artist,
            metadata.get('album'),
            metadata.get('album_mbid'),
            metadata.get('duration', 0),
            metadata.get('track_number'),
            metadata.get('total_tracks'),
            metadata.get('year'),
            json.dumps(metadata.get('genres', [])),
            album_art_local,
            json.dumps(metadata)
        ))

        conn.commit()
        conn.close()

    def print_statistics(self):
        """Print cache statistics."""
        conn = sqlite3.connect(self.cache_db)
        cursor = conn.cursor()

        stats = {}
        queries = {
            'total_tracks': "SELECT COUNT(*) FROM tracks",
            'total_albums': "SELECT COUNT(DISTINCT album) FROM tracks WHERE album IS NOT NULL",
            'total_artists': "SELECT COUNT(DISTINCT artist) FROM tracks",
            'tracks_with_art': "SELECT COUNT(*) FROM tracks WHERE album_art_local IS NOT NULL",
            'tracks_with_fingerprint': "SELECT COUNT(*) FROM tracks WHERE fingerprint IS NOT NULL",
            'tracks_with_number': "SELECT COUNT(*) FROM tracks WHERE track_number IS NOT NULL",
            'singles_count': "SELECT COUNT(*) FROM tracks WHERE release_type = 'Single'",
            'albums_consolidated': "SELECT COUNT(*) FROM album_consolidation"
        }

        for key, query in queries.items():
            cursor.execute(query)
            stats[key] = cursor.fetchone()[0]

        conn.close()

        print("\nCache Statistics:")
        print(f"  Total tracks: {stats['total_tracks']}")
        print(f"  Total albums: {stats['total_albums']}")
        print(f"  Total artists: {stats['total_artists']}")
        print(f"  Tracks with album art: {stats['tracks_with_art']}")
        print(f"  Tracks with fingerprints: {stats['tracks_with_fingerprint']}")
        print(f"  Tracks with track numbers: {stats['tracks_with_number']}")
        print(f"  Singles in database: {stats['singles_count']}")
        print(f"  Albums consolidated: {stats['albums_consolidated']}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python cache_vinyl.py <acoustid_api_key> [audio_files...]")
        print("\nExamples:")
        print("  python cache_vinyl.py YOUR_API_KEY music\\*.mp3")
        print("  python cache_vinyl.py YOUR_API_KEY \"C:\\Music\\Album Name\\\"")
        print("  python cache_vinyl.py YOUR_API_KEY --album \"C:\\Music\\Album\\\" \"Album Name\"")
        sys.exit(1)

    api_key = sys.argv[1]

    # Check for album mode
    if len(sys.argv) > 2 and sys.argv[2] == '--album':
        # Album directory mode
        if len(sys.argv) < 4:
            print("Album mode requires: --album <directory> [album_name]")
            sys.exit(1)

        album_dir = sys.argv[3]
        album_name = sys.argv[4] if len(sys.argv) > 4 else None

        cache = MusicCollectionCache(api_key)
        cache.cache_album_directory(album_dir, album_name)
    else:
        # For backwards compatibility with file-by-file mode
        print("Note: For better album detection, use --album mode")
        print("Processing files individually...")

        # ... rest of the original file processing code ...