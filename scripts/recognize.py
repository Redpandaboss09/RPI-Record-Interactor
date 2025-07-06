import argparse
import logging
import sys
from pathlib import Path

import numpy as np

sys.path.append(str(Path(__file__).parent.parent))

from models import Config, TrackInfo
from services.fingerprint import FingerprintGenerator
from services.music_database import MusicDatabase
from audio.capture import RealTimeAudioCapture
from audio.processing import AudioProcessor


def record_audio(duration: float, config: Config) -> np.ndarray:
    """ Record live audio for the specified duration. """
    with RealTimeAudioCapture(config, max_recording_seconds=duration) as capture:
        return capture.collect_audio(duration)


def recognize_audio(audio_data: np.ndarray, config: Config) -> list[tuple[TrackInfo, float]]:
    """ Generate fingerprints and find matches in the database. """
    processor = AudioProcessor(config)
    generator = FingerprintGenerator(config)

    fingerprints = generator.fingerprint_audio(audio_data, processor)

    with MusicDatabase(config) as db:
        return db.find_matches(fingerprints)


def display_results(matches: list[tuple[TrackInfo, float]], recording_duration: float):
    """ Display recognition results. """
    print(f'\n{'-'*50}')
    print(f'Recording duration: {recording_duration:.1f} seconds')
    print(f'\n{'-'*50}')

    if not matches:
        print('No matches found.')
        return

    print('Top matches:\n')

    for i, (track, confidence) in enumerate(matches[:5], 1):
        print(f'{i}. [{confidence:5.1%}] {track.title} - {track.artist}')
        if track.album:
            print(f'            Album: {track.album}')
        print()


def setup_logging(verbose: bool):
    """ Create logs directory and configure logging. """
    # Creates the directory if it does not exist
    project_root = Path(__file__).parent.parent
    log_dir = project_root / 'logs'
    log_dir.mkdir(exist_ok=True)

    # Configure logging
    log_file = log_dir / 'recognize.log'

    log_level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )

    if not verbose:
        logging.getLogger('audio').setLevel(logging.WARNING)
        logging.getLogger('services').setLevel(logging.WARNING)


def main():
    parser = argparse.ArgumentParser(description='Recognize songs using audio fingerprinting')
    parser.add_argument('-d', '--duration', type=float, default=10.0,
                        help='Duration of the recording in seconds (default: 10.0s)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output')
    parser.add_argument('--device', type=int, default=27,
                        help='Device index (default: 27)')

    args = parser.parse_args()

    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    config = Config()
    config.audio_device_index = args.device

    project_root = Path(__file__).parent.parent
    config.db_path = str(project_root / "database" / "collection")

    try:
        print(f'Preparing to record for {args.duration} seconds...')
        import time
        for i in range(3, 0, -1):
            print(f'Starting in {i}...')
            time.sleep(1)

        # Start recording
        print(f'\nListening...\n')

        audio_data = record_audio(args.duration, config)

        print(f'Recording complete!')

        print('Searching for matches...')
        matches = recognize_audio(audio_data, config)

        display_results(matches, args.duration)
    except KeyboardInterrupt:
        print('\nRecording cancelled by user')
        logger.info('User cancelled recording')
    except TimeoutError as e:
        print(f'\nRecording failed: {e}')
        logger.error(f'Recording timeout: {e}')
    except RuntimeError as e:
        print(f'\nAudio device failed: {e}')
        logger.error(f'Audio device error: {e}')
    except Exception as e:
        print(f'\nUnknown error: {e}')
        if args.verbose:
            logger.exception("Unexpected error!")
        else:
            logger.error(f'Unexpected error: {e}')
            print('\nRun with --verbose flag for detailed error info')


if __name__ == '__main__':
    main()