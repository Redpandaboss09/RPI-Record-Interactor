import numpy as np

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from models import Config
from audio.processing import AudioProcessor


class FingerprintGenerator:
    def __init__(self, config: Config):
        self.config = config

    def _generate_constellation_pairs(self, peaks: list[tuple]) -> list[tuple]:
        """ Generate the constellation pairs from the audio peak map. """
        peaks = sorted(peaks, key=lambda p: p[0])  # sort by the time

        pairs = []
        for i in range(len(peaks)):  # Set the peak as the anchor
            for j in range(1, min(self.config.fan_value + 1, len(peaks) - i)):  # Try to pair up to fan_value or rest
                time_diff = peaks[i + j][0] - peaks[i][0]  # Get time difference between anchor and target

                if time_diff > self.config.max_time_delta:
                    break  # Too far, break out

                if time_diff >= self.config.min_time_delta:
                    pairs.append((peaks[i], peaks[i + j]))

        return pairs

    def _generate_hashes(self, constellation_pairs: list[tuple]) -> list[tuple]:
        """ Generate the hashes of the constellation pairs, used to store the fingerprints. """
        hashes = []

        for anchor, target in constellation_pairs:
            anchor_time = int(anchor[0])
            anchor_freq = int(anchor[1])
            target_freq = int(target[1])
            time_delta = int(target[0]) - int(anchor[0])

            hash_value = ((anchor_freq & 0x3FF) << 22) | \
                         ((target_freq & 0x3FF) << 12) | \
                         (time_delta & 0xFFF)

            hashes.append((hash_value, anchor_time))

        return hashes

    def fingerprint_audio(self, audio_data: np.ndarray, processor: AudioProcessor) -> list[tuple]:
        """
            Represents the full pipeline:
                1. Generate spectrogram
                2. Extract peaks
                3. Generate constellation pairs
                4. Generate hashes

            This will return the hashes for storage.
        """

        spectrogram = processor.compute_stft(audio_data)
        peaks = processor.extract_peaks(spectrogram)
        constellation_pairs = self._generate_constellation_pairs(peaks)

        return self._generate_hashes(constellation_pairs)
