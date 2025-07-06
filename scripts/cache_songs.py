import argparse
import logging
from typing import Optional
from tqdm import tqdm

import numpy as np
from pydub import AudioSegment
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from models import Config, TrackInfo
from audio.processing import AudioProcessor
from services.fingerprint import FingerprintGenerator
from services.music_database import MusicDatabase


def process_music_folder(folder_path: Path, config: Config, reprocess: bool = False):
    """ Process all MP3 files in a folder structure. """
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info(f'Processing music folder {folder_path}')
    logger.info(f'Reprocess existing: {reprocess}')

    # Find all mp3 files
    mp3_files = []
    for album_folder in folder_path.iterdir():
        if album_folder.is_dir():
            for mp3_file in album_folder.glob("*.mp3"):
                mp3_files.append((mp3_file, album_folder.name))

    if not mp3_files:
        logger.warning(f'No MP3 files found in folder {folder_path}')
        print(f'No MP3 files found in folder {folder_path}')
        return

    logger.info(f'Found {len(mp3_files)} MP3 files')
    print(f'Found {len(mp3_files)} MP3 files')

    # Initialize necessary components
    processor = AudioProcessor(config)
    generator = FingerprintGenerator(config)

    # Process files with progress bar
    successful = 0
    failed = 0
    skipped = 0

    with MusicDatabase(config) as db:
        with tqdm(mp3_files, desc="Processing songs") as pbar:
            for file_path, album_name in pbar:
                pbar.set_description(f'Processing {file_path.name}')

                result = process_file(
                    file_path, album_name, db, processor, generator,
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

    print(f'\nProcessing complete:')
    print(f'    Successful: {successful}')
    print(f'    Failed: {failed}')
    print(f'    Skipped (Already Exists): {skipped}')

    logger.info(f'Processing complete - Success: {successful}, Failed: {failed}, Skipped: {skipped}')


def extract_mp3_metadata(file_path: Path, album_name: str) -> Optional[TrackInfo]:
    """ Extract metadata from MP3 file. """
    try:
        # Load the mp3 metadata
        audio = MP3(str(file_path))

        # Extract ID3 tags
        if audio.tags is None:
            # Fill in as much as possible using filename
            title = file_path.stem
            artist = "Unknown Artist"
            album = album_name
            track_number = None
            total_tracks = None
        else:
            tags = audio.tags

            # Get the basic metadata
            title = str(tags.get("TIT2", file_path.stem))
            artist = str(tags.get("TPE1", "Unknown Artist"))
            album = str(tags.get("TALB", album_name))

            # Get the track number
            track_info = tags.get("TRCK", None)
            if track_info:
                track_str = str(track_info)
                if "/" in track_str:
                    track_number, total_tracks = track_str.split("/", 1)
                    track_number = int(track_number) if track_number.isdigit() else None
                    total_tracks = int(total_tracks) if total_tracks.isdigit() else None
                else:
                    track_number = int(track_str) if track_str.isdigit() else None
                    total_tracks = None

        duration = int(audio.info.length)

        return TrackInfo(
            title=title,
            artist=artist,
            album=album,
            duration=duration,
            audio_file_path=str(file_path),
            track_number=track_number,
            total_tracks=total_tracks,
            album_art_path=None,
            lyrics_file_path=None
        )
    except Exception as e:
        logging.error(f'Failed to extract metadata from {file_path}: {e}')
        return None


def process_file(file_path: Path, album_name: str, db: MusicDatabase,
                 processor: AudioProcessor, generator: FingerprintGenerator,
                 config: Config, logger: logging.Logger, reprocess: bool) -> Optional[bool]:
    """ Process a single MP3 file. """
    try:
        # Extract metadata
        track_info = extract_mp3_metadata(file_path, album_name)
        if not track_info:
            logger.error(f'Failed to extract metadata from {file_path}')
            return False

        # Check if the track already exists
        if not reprocess and db.track_exists(track_info.title, track_info.artist, track_info.album):
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

        # Store in database
        track_id = db.add_track(track_info)
        db.add_fingerprints(track_id, fingerprints)

        logger.info(f'Successfully loaded fingerprints for {track_info.title} by {track_info.artist} '
                    f'({len(fingerprints)} fingerprints)')

        return True
    except Exception as e:
        logging.error(f'Failed to process file {file_path}: {e}', exc_info=True)
        return False


def load_audio_file(file_path: Path, target_sample_rate: int) -> Optional[np.ndarray]:
    """ Load and convert audio file to numpy array. """
    try:
        audio = AudioSegment.from_mp3(file_path)

        # Convert to mono
        if audio.channels > 1:
            audio = audio.set_channels(1)

        # May need to resample
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
