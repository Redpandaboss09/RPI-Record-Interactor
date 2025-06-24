""" Simple test to fingerprint one file. """
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Config, TrackInfo
from services.fingerprint import FingerprintService
from config.database import DEJAVU_CONFIG


def test_fingerprint_single_file(filepath):
    if not os.path.exists(filepath):
        print(f"Error: File '{filepath}' not found")
        return

    print(f"Testing fingerprint on: {filepath}")

    # Create service
    config = Config()
    service = FingerprintService(config, DEJAVU_CONFIG)

    # Create track info
    filename = os.path.basename(filepath)
    track_info = TrackInfo(
        id="",
        title=filename.replace('.mp3', '').replace('.wav', ''),
        artist="Test Artist",
        album="Test Album"
    )

    print(f"\nFingerprinting as:")
    print(f"  Title: {track_info.title}")
    print(f"  Artist: {track_info.artist}")

    # Fingerprint it
    success = service.fingerprint_file(filepath, track_info)

    if success:
        print("\n✓ Fingerprinting successful!")
    else:
        print("\n✗ Fingerprinting failed!")

    service.stop()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_fingerprint_simple.py /path/to/audio.mp3")
    else:
        test_fingerprint_single_file(sys.argv[1])