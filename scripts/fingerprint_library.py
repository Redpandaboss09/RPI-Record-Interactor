#!/usr/bin/env python3
"""
Script to fingerprint your music library.
Usage: python fingerprint_library.py /path/to/music
"""

import os
import sys
from pathlib import Path
import eyed3
from models import Config, TrackInfo
from services.fingerprint import FingerprintService
from config.database import DEJAVU_CONFIG


def get_audio_metadata(filepath: str) -> TrackInfo:
    """ Extract metadata from audio file. """
    try:
        audiofile = eyed3.load(filepath)
        if audiofile and audiofile.tag:
            return TrackInfo(
                id="",  # Will be set by Dejavu
                title=audiofile.tag.title or Path(filepath).stem,
                artist=audiofile.tag.artist or "Unknown Artist",
                album=audiofile.tag.album or "Unknown Album",
                duration=audiofile.info.time_secs if audiofile.info else None
            )
    except:
        pass

    # Fallback to filename parsing
    filename = Path(filepath).stem
    parts = filename.split(" - ")

    if len(parts) >= 2:
        return TrackInfo(
            id="",
            artist=parts[0].strip(),
            title=parts[1].strip(),
            album="Unknown Album"
        )
    else:
        return TrackInfo(
            id="",
            title=filename,
            artist="Unknown Artist",
            album="Unknown Album"
        )


def fingerprint_directory(directory: str, service: FingerprintService):
    """ Fingerprint all audio files in directory. """
    audio_extensions = {'.mp3', '.wav', '.flac', '.m4a', '.ogg'}

    for root, dirs, files in os.walk(directory):
        for file in files:
            if Path(file).suffix.lower() in audio_extensions:
                filepath = os.path.join(root, file)

                print(f"\nProcessing: {filepath}")

                # Get metadata
                track_info = get_audio_metadata(filepath)
                print(f"  Artist: {track_info.artist}")
                print(f"  Title: {track_info.title}")
                print(f"  Album: {track_info.album}")

                # Fingerprint
                success = service.fingerprint_file(filepath, track_info)

                if success:
                    print("Fingerprinted successfully")
                else:
                    print("Failed to fingerprint")


def main():
    if len(sys.argv) < 2:
        print("Usage: python fingerprint_library.py /path/to/music")
        sys.exit(1)

    music_directory = sys.argv[1]

    if not os.path.exists(music_directory):
        print(f"Error: Directory '{music_directory}' not found")
        sys.exit(1)

    # Initialize service
    config = Config()
    service = FingerprintService(config, DEJAVU_CONFIG)

    print(f"Fingerprinting music in: {music_directory}")
    print("-" * 50)

    try:
        fingerprint_directory(music_directory, service)
        print("\n✓ Fingerprinting complete!")
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\nError: {e}")
    finally:
        service.stop()


if __name__ == "__main__":
    main()