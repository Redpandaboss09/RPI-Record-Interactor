""" Test recognition on a file. """
import sys
import time
import soundfile as sf
from models import Config
from services.fingerprint import FingerprintService
from config.database import DEJAVU_CONFIG


def test_recognition(filepath):
    print(f"Testing recognition on: {filepath}")

    # Load audio
    try:
        audio_data, sample_rate = sf.read(filepath, dtype='float32')
        if audio_data.ndim > 1:
            audio_data = audio_data.mean(axis=1)  # Convert to mono
    except Exception as e:
        print(f"Error loading audio: {e}")
        print("Install soundfile: pip install soundfile")
        return

    print(f"Loaded {len(audio_data) / sample_rate:.1f} seconds of audio")

    # Create service
    config = Config()
    service = FingerprintService(config, DEJAVU_CONFIG)
    service.start()

    # Submit chunks
    chunk_seconds = 5
    chunk_size = sample_rate * chunk_seconds

    print(f"\nSubmitting {chunk_seconds}-second chunks for recognition...")

    for i in range(0, len(audio_data), chunk_size):
        chunk = audio_data[i:i + chunk_size]
        if len(chunk) < chunk_size:
            print(f"Skipping final chunk (too short)")
            break

        print(f"\nChunk {i // chunk_size + 1}:")
        service.submit_audio(chunk)

        # Wait for recognition
        time.sleep(2)

        track = service.get_current_track()
        if track:
            print(f"✓ RECOGNIZED: {track.title} by {track.artist}")
            break
        else:
            print("  No recognition yet...")
    else:
        print("\nNo recognition after all chunks")

    service.stop()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_recognition_simple.py /path/to/audio.mp3")
    else:
        test_recognition(sys.argv[1])