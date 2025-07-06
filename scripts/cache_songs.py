import argparse
import logging
from typing import Optional
from tqdm import tqdm

import numpy as np
from pydub import AudioSegment
from mutagen.flac import FLAC

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from models import Config, TrackInfo
from audio.processing import AudioProcessor
from services.fingerprint import FingerprintGenerator
from services.music_database import MusicDatabase


def process_music_folder(folder_path: Path, config: Config, reprocess: bool = False):
    """ Process all FLAC files in a folder structure. """
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info(f'Processing music folder {folder_path}')
    logger.info(f'Reprocess existing: {reprocess}')

    # Find all FLAC files
    flac_files = []
    for album_folder in folder_path.iterdir():
        if album_folder.is_dir():
            for flac_file in album_folder.glob("*.flac"):
                flac_files.append((flac_file, album_folder))

    if not flac_files:
        logger.warning(f'No flac files found in folder {folder_path}')
        print(f'No flac files found in folder {folder_path}')
        return

    logger.info(f'Found {len(flac_files)} flac files')
    print(f'Found {len(flac_files)} flac files')

    # Initialize necessary components
    processor = AudioProcessor(config)
    generator = FingerprintGenerator(config)

    # Process files with progress bar
    successful = 0
    failed = 0
    skipped = 0

    with MusicDatabase(config) as db:
        with tqdm(flac_files, desc="Processing songs") as pbar:
            for file_path, album_folder in pbar:
                pbar.set_description(f'Processing {file_path.name}')

                result = process_file(
                    file_path, album_folder, db, processor, generator,
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


def extract_metadata(file_path: Path, album_folder: Path) -> Optional[TrackInfo]:
    """ Extract metadata from a FLAC file. """
    try:
        # Load the FLAC metadata
        audio = FLAC(str(file_path))

        # Extract tags
        title = audio.get("title", [file_path.stem])[0]
        artist = audio.get("artist", ["Unknown Artist"])[0]
        album = audio.get("album", [album_folder.name])[0]

        # Track numbers
        track_str = audio.get("tracknumber", [""])[0]
        total_str = audio.get("totaltracks", audio.get("tracktotal", [""]))[0]

        track_number = int(track_str) if track_str.isdigit() else None
        total_tracks = int(total_str) if total_str else None

        duration = int(audio.info.length)

        cover_path = album_folder / "cover.jpg"
        album_art_path = str(cover_path) if cover_path.exists() else None

        return TrackInfo(
            title=title,
            artist=artist,
            album=album,
            duration=duration,
            audio_file_path=str(file_path),
            track_number=track_number,
            total_tracks=total_tracks,
            album_art_path=album_art_path,
            lyrics_file_path=None
        )
    except Exception as e:
        logging.error(f'Failed to extract metadata from {file_path}: {e}')
        return None


def process_file(file_path: Path, album_folder: Path, db: MusicDatabase,
                 processor: AudioProcessor, generator: FingerprintGenerator,
                 config: Config, logger: logging.Logger, reprocess: bool) -> Optional[bool]:
    """ Process a single flac file. """
    try:
        # Extract metadata
        track_info = extract_metadata(file_path, album_folder)
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
        audio = AudioSegment.from_file(file_path, format="flac")

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
