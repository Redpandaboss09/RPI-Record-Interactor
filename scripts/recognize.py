import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np

sys.path.append(str(Path(__file__).parent.parent))

from models import Config, TrackInfo
from services.fingerprint import FingerprintGenerator
from services.music_database import MusicDatabase
from audio.capture import RealTimeAudioCapture
from audio.processing import AudioProcessor


def record_audio(duration: float, config: Config) -> np.ndarray:
    """Record live audio for the specified duration."""
    with RealTimeAudioCapture(config, max_recording_seconds=duration) as capture:
        return capture.collect_audio(duration)


def recognize_audio_optimized(audio_data: np.ndarray, config: Config) -> list[tuple[TrackInfo, float]]:
    """Optimized audio recognition with early termination."""
    processor = AudioProcessor(config)
    generator = FingerprintGenerator(config)

    # Start timing
    start_time = time.time()

    # Generate fingerprints
    print("Generating fingerprints...")
    fp_start = time.time()
    fingerprints = generator.fingerprint_audio(audio_data, processor)
    fp_time = time.time() - fp_start
    print(f"Generated {len(fingerprints)} fingerprints in {fp_time:.3f}s")

    # Early termination if too few fingerprints
    if len(fingerprints) < 20:
        print("Too few fingerprints generated")
        return []

    print("Searching database...")
    search_start = time.time()

    with MusicDatabase(config) as db:
        matches = db.find_matches(fingerprints)

    search_time = time.time() - search_start
    total_time = time.time() - start_time

    print(f"Search completed in {search_time:.3f}s")
    print(f"Total recognition time: {total_time:.3f}s")

    return matches


def recognize_audio_progressive(audio_data: np.ndarray, config: Config,
                                confidence_threshold: float = 0.95) -> list[tuple[TrackInfo, float]]:
    """Progressive recognition - process audio in chunks for faster results."""
    processor = AudioProcessor(config)
    generator = FingerprintGenerator(config)

    # Process in increasing chunk sizes
    chunk_sizes = [3, 5, 10]  # seconds
    sample_rate = config.target_sample_rate

    for chunk_seconds in chunk_sizes:
        chunk_samples = int(chunk_seconds * sample_rate)
        if chunk_samples > len(audio_data):
            chunk_samples = len(audio_data)

        print(f"\nTrying with {chunk_seconds}s of audio...")
        chunk = audio_data[:chunk_samples]

        # Generate fingerprints
        fingerprints = generator.fingerprint_audio(chunk, processor)

        if len(fingerprints) < 10:
            continue

        # Try to find matches
        with MusicDatabase(config) as db:
            matches = db.find_matches(fingerprints)

        if matches and matches[0][1] >= confidence_threshold:
            print(f"High confidence match found with {chunk_seconds}s!")
            return matches

        if chunk_samples >= len(audio_data):
            break

    # If no high confidence match, process full audio
    print("\nProcessing full audio...")
    return recognize_audio_optimized(audio_data, config)


def display_results(matches: list[tuple[TrackInfo, float]], recording_duration: float):
    """Display recognition results."""
    print(f'\n{"=" * 60}')
    print(f'Recording duration: {recording_duration:.1f} seconds')
    print(f'{"=" * 60}\n')

    if not matches:
        print('No matches found.')
        return

    print('Top matches:\n')

    for i, (track, confidence) in enumerate(matches[:5], 1):
        print(f'{i}. [{confidence:5.1%}] {track.title} - {track.artist}')
        if track.album:
            print(f'     └─ Album: {track.album}')
        print()


def setup_logging(verbose: bool):
    """Create logs directory and configure logging."""
    project_root = Path(__file__).parent.parent
    log_dir = project_root / 'logs'
    log_dir.mkdir(exist_ok=True)

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
    parser = argparse.ArgumentParser(description='Music recognition using audio fingerprinting')
    parser.add_argument('-d', '--duration', type=float, default=10.0,
                        help='Duration of the recording in seconds (default: 10.0s)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output')
    parser.add_argument('--device', type=int, default=27,
                        help='Device index (default: 27)')
    parser.add_argument('--progressive', action='store_true',
                        help='Use progressive recognition (faster for clear audio)')
    parser.add_argument('--confidence', type=float, default=0.95,
                        help='Confidence threshold for progressive mode (default: 0.95)')

    args = parser.parse_args()

    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    config = Config()
    config.audio_device_index = args.device

    project_root = Path(__file__).parent.parent
    config.db_path = str(project_root / "database" / "collection")

    try:
        print(f'Preparing to record for {args.duration} seconds...')

        # Countdown
        import time as time_module
        for i in range(3, 0, -1):
            print(f'   Starting in {i}...')
            time_module.sleep(1)

        # Start recording
        print(f'\nRECORDING - Please play audio now!\n')

        record_start = time.time()
        audio_data = record_audio(args.duration, config)
        record_time = time.time() - record_start

        print(f'\nRecording complete! ({record_time:.1f}s)')
        print(f'Analyzing audio...\n')

        # Recognize
        if args.progressive:
            matches = recognize_audio_progressive(
                audio_data, config,
                confidence_threshold=args.confidence
            )
        else:
            matches = recognize_audio_optimized(audio_data, config)

        # Display results
        display_results(matches, args.duration)

    except KeyboardInterrupt:
        print('\n\nRecording cancelled by user')
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