#!/usr/bin/env python3
""" Test recognition with an audio file. """

import sys
from models import Config
from services.fingerprint import FingerprintService
from config.database import DEJAVU_CONFIG
import soundfile as sf
import time


def test_file(filepath: str):
    """ Test recognition on a specific file. """
    config = Config()
    service = FingerprintService(config, DEJAVU_CONFIG)

    try:
        service.start()

        # Load audio file
        audio_data, sample_rate = sf.read(filepath, dtype='float32')

        if audio_data.ndim > 1:
            audio_data = audio_data.mean(axis=1)

        print(f"Testing recognition on: {filepath}")
        print(f"Sample rate: {sample_rate}")
        print(f"Duration: {len(audio_data) / sample_rate:.2f} seconds")

        # Submit for recognition
        chunk_size = sample_rate * 5  # 5 second chunks

        for i in range(0, len(audio_data), chunk_size):
            chunk = audio_data[i:i + chunk_size]

            print(f"\nSubmitting chunk {i // chunk_size + 1}...")
            service.submit_audio(chunk)

            # Wait for recognition
            time.sleep(2)

            if service.get_current_track():
                track = service.get_current_track()
                print(f"Recognized: {track.title} by {track.artist}")
                break
        else:
            print("No recognition")

    finally:
        service.stop()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_recognition.py audio_file.mp3")
        sys.exit(1)

    test_file(sys.argv[1])