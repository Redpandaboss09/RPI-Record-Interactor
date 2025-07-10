import argparse
import logging
import re
from typing import Optional
from tqdm import tqdm

import numpy as np
from pydub import AudioSegment
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.id3 import ID3

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from models import Config, TrackInfo
from audio.processing import AudioProcessor
from services.fingerprint import FingerprintGenerator
from services.music_database import MusicDatabase


def get_disc_number_from_folder(folder_name: str) -> Optional[int]:
    """ Extract disc number from folder name (e.g., 'Disc 1', 'Disc 2'). """
    patterns = [
        r'[Dd]isc\s*(\d+)',
        r'[Cc][Dd]\s*(\d+)',
        r'[Dd]isk\s*(\d+)',
        r'[Pp]art\s*(\d+)'
    ]

    for pattern in patterns:
        match = re.search(pattern, folder_name)
        if match:
            return int(match.group(1))

    return None


def find_audio_files(folder_path: Path) -> list[tuple[Path, Path, Optional[int]]]:
    """Find all FLAC and MP3 files in folder structure, with disc numbers."""
    audio_files = []

    for album_folder in folder_path.iterdir():
        if not album_folder.is_dir():
            continue

        # Check if album has disc subfolders
        disc_folders = []
        has_disc_folders = False

        for item in album_folder.iterdir():
            if item.is_dir() and get_disc_number_from_folder(item.name) is not None:
                disc_folders.append(item)
                has_disc_folders = True

        if has_disc_folders:
            # Process each disc folder
            for disc_folder in disc_folders:
                disc_number = get_disc_number_from_folder(disc_folder.name)
                for audio_file in disc_folder.glob("*.flac"):
                    audio_files.append((audio_file, album_folder, disc_number))
                for audio_file in disc_folder.glob("*.mp3"):
                    audio_files.append((audio_file, album_folder, disc_number))
        else:
            # No disc folders, process files directly (default to disc 1)
            for audio_file in album_folder.glob("*.flac"):
                audio_files.append((audio_file, album_folder, 1))
            for audio_file in album_folder.glob("*.mp3"):
                audio_files.append((audio_file, album_folder, 1))

    return audio_files


def process_music_folder(folder_path: Path, config: Config, reprocess: bool = False):
    """Process all FLAC and MP3 files in a folder structure."""
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info(f'Processing music folder {folder_path}')
    logger.info(f'Reprocess existing: {reprocess}')

    # Find all audio files
    audio_files = find_audio_files(folder_path)

    if not audio_files:
        logger.warning(f'No audio files found in folder {folder_path}')
        print(f'No audio files found in folder {folder_path}')
        return

    logger.info(f'Found {len(audio_files)} audio files')
    print(f'Found {len(audio_files)} audio files')

    # Initialize necessary components
    processor = AudioProcessor(config)
    generator = FingerprintGenerator(config)

    # Process files with progress bar
    successful = 0
    failed = 0
    skipped = 0

    with MusicDatabase(config) as db:
        with tqdm(audio_files, desc="Processing songs") as pbar:
            for file_path, album_folder, disc_number in pbar:
                pbar.set_description(f'Processing {file_path.name}')

                result = process_file(
                    file_path, album_folder, disc_number, db, processor, generator,
                    config, logger, reprocess
                )

                if result is None:
                    skipped += 1
                elif result:
                    successful += 1
                else:
                    failed += 1

                pbar.set_postfix({
                    "✓": successful,
                    "✗": failed,
                    "→": skipped
                })

        print("\nOptimizing database for fast queries...")
        db.optimize_database()

        # Show final stats
        stats = db.get_stats()
        print(f"\nDatabase Statistics:")
        print(f"  Total tracks: {stats['total_tracks']:,}")
        print(f"  Total fingerprints: {stats['total_fingerprints']:,}")
        print(f"  Unique hashes: {stats['unique_hashes']:,}")
        print(f"  Database size: {stats['db_size_mb']:.1f} MB")

    print(f'\nProcessing complete:')
    print(f'    Successful: {successful}')
    print(f'    Failed: {failed}')
    print(f'    Skipped (Already Exists): {skipped}')

    logger.info(f'Processing complete - Success: {successful}, Failed: {failed}, Skipped: {skipped}')


def extract_metadata(file_path: Path, album_folder: Path, disc_number: Optional[int]) -> Optional[TrackInfo]:
    """Extract metadata from a FLAC or MP3 file."""
    try:
        file_ext = file_path.suffix.lower()

        if file_ext == '.flac':
            # Load FLAC metadata
            audio = FLAC(str(file_path))

            # Extract tags
            title = audio.get("title", [file_path.stem])[0]
            artist = audio.get("artist", ["Unknown Artist"])[0]
            album = audio.get("album", [album_folder.name])[0]

            # Track numbers
            track_str = audio.get("tracknumber", [""])[0]
            total_str = audio.get("totaltracks", audio.get("tracktotal", [""]))[0]

            # Disc numbers (use metadata if available, otherwise use folder-based)
            disc_str = audio.get("discnumber", [""])[0]
            total_discs_str = audio.get("totaldiscs", audio.get("disctotal", [""]))[0]

            if disc_str and disc_str.isdigit():
                disc_number = int(disc_str)
            elif disc_number is None:
                disc_number = 1

            total_discs = int(total_discs_str) if total_discs_str and total_discs_str.isdigit() else None

            duration = int(audio.info.length)

        elif file_ext == '.mp3':
            # Load MP3 metadata
            audio = MP3(str(file_path))

            # Try to get ID3 tags
            if audio.tags:
                title = str(audio.tags.get("TIT2", file_path.stem))
                artist = str(audio.tags.get("TPE1", "Unknown Artist"))
                album = str(audio.tags.get("TALB", album_folder.name))

                # Track numbers
                track_info = audio.tags.get("TRCK", "")
                if track_info:
                    track_parts = str(track_info).split('/')
                    track_str = track_parts[0]
                    total_str = track_parts[1] if len(track_parts) > 1 else ""
                else:
                    track_str = ""
                    total_str = ""

                # Disc numbers
                disc_info = audio.tags.get("TPOS", "")
                total_discs = None
                if disc_info:
                    disc_parts = str(disc_info).split('/')
                    if disc_parts[0].isdigit():
                        disc_number = int(disc_parts[0])
                    if len(disc_parts) > 1 and disc_parts[1].isdigit():
                        total_discs = int(disc_parts[1])
                elif disc_number is None:
                    disc_number = 1
            else:
                # No ID3 tags
                title = file_path.stem
                artist = "Unknown Artist"
                album = album_folder.name
                track_str = ""
                total_str = ""
                total_discs = None
                if disc_number is None:
                    disc_number = 1

            duration = int(audio.info.length)
        else:
            logging.error(f'Unsupported file format: {file_ext}')
            return None

        track_number = int(track_str) if track_str.isdigit() else None
        total_tracks = int(total_str) if total_str and total_str.isdigit() else None

        # Look for cover art in album folder
        cover_path = album_folder / "cover.jpg"
        if not cover_path.exists():
            # Try other common cover filenames
            for cover_name in ["cover.png", "folder.jpg", "folder.png", "album.jpg", "album.png"]:
                cover_path = album_folder / cover_name
                if cover_path.exists():
                    break

        album_art_path = str(cover_path) if cover_path.exists() else None

        track_info = TrackInfo(
            title=title,
            artist=artist,
            album=album,
            duration=duration,
            audio_file_path=str(file_path),
            track_number=track_number,
            total_tracks=total_tracks,
            album_art_path=album_art_path,
            lyrics_file_path=None,
            disc_number=disc_number,
            total_discs=total_discs
        )

        return track_info

    except Exception as e:
        logging.error(f'Failed to extract metadata from {file_path}: {e}')
        return None


def process_file(file_path: Path, album_folder: Path, disc_number: Optional[int],
                 db: MusicDatabase, processor: AudioProcessor,
                 generator: FingerprintGenerator, config: Config,
                 logger: logging.Logger, reprocess: bool) -> Optional[bool]:
    """Process a single audio file."""
    try:
        # Extract metadata
        track_info = extract_metadata(file_path, album_folder, disc_number)
        if not track_info:
            logger.error(f'Failed to extract metadata from {file_path}')
            return False

        track_id = db.add_track(track_info)

        # Check if the track already exists
        if track_id == -1 and not reprocess:
            logger.debug(f'Skipping existing track: {track_info.title} by {track_info.artist}')
            return None

        # Load audio data
        logger.debug(f'Loading audio from {file_path}')
        audio_data = load_audio_file(file_path, config.target_sample_rate)
        if audio_data is None:
            logger.error(f'Failed to load audio from {file_path}')
            return False

        # Generate fingerprints
        logger.debug(f'Generating fingerprints for {track_info.title} by {track_info.artist}')
        fingerprints = generator.fingerprint_audio(audio_data, processor)

        if not fingerprints:
            logger.warning(f'No fingerprints generated for {file_path}')
            return False

        logger.debug(f'Generated {len(fingerprints)} fingerprints')

        # Store fingerprints using batch method
        db.add_fingerprints_batch(track_id, fingerprints)

        logger.info(f'Successfully loaded fingerprints for {track_info.title} by {track_info.artist} '
                    f'({len(fingerprints)} fingerprints)')

        return True
    except Exception as e:
        logging.error(f'Failed to process file {file_path}: {e}', exc_info=True)
        return False


def load_audio_file(file_path: Path, target_sample_rate: int) -> Optional[np.ndarray]:
    """Load and convert audio file to numpy array."""
    try:
        file_ext = file_path.suffix.lower()

        if file_ext == '.flac':
            audio = AudioSegment.from_file(file_path, format="flac")
        elif file_ext == '.mp3':
            audio = AudioSegment.from_file(file_path, format="mp3")
        else:
            logging.error(f'Unsupported audio format: {file_ext}')
            return None

        # Convert to mono
        if audio.channels > 1:
            audio = audio.set_channels(1)

        # Resample if needed
        if audio.frame_rate != target_sample_rate:
            audio = audio.set_frame_rate(target_sample_rate)

        samples = np.array(audio.get_array_of_samples())

        # Normalize to [-1, 1] range
        samples = samples.astype(np.float32) / 32768.0

        return samples
    except Exception as e:
        logging.error(f'Failed to load {file_path}: {e}')
        return None


def setup_logging():
    """ Create logs directory and configure logging. """
    # Creates the directory if it does not exist
    log_dir = Path('logs')
    log_dir.mkdir(exist_ok=True)

    # Configure logging
    log_file = log_dir / 'cache_songs.log'

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )

    logging.getLogger('pydub').setLevel(logging.WARNING)
    logging.getLogger('mutagen').setLevel(logging.WARNING)


def main():
    parser = argparse.ArgumentParser(description="Cache songs from your music library")
    parser.add_argument("folder", nargs="?", help="Folder containing your music library")
    parser.add_argument("--reprocess", action='store_true', help="Re-process the cached songs")

    args = parser.parse_args()

    config = Config()

    if args.folder:
        music_folder = Path(args.folder)
    else:
        music_folder = Path(config.music_library).expanduser()

    if not music_folder.exists():
        print(f'Error: {music_folder} does not exist')
        return

    process_music_folder(music_folder, config, args.reprocess)


if __name__ == '__main__':
    main()
