import numpy as np
from collections import deque
import threading
from typing import Optional


class RecognitionBuffer:
    """ Thread-safe circular buffer for accumulating audio for recognition. """

    def __init__(self, target_seconds: float = 5.0, sample_rate: int = 44100):
        self.target_seconds = target_seconds
        self.sample_rate = sample_rate
        self.target_samples = int(target_seconds * sample_rate)

        self.buffer = deque(maxlen=self.target_samples)
        self.lock = threading.Lock()

        self.samples_added = 0

    def add_audio(self, audio_data: np.ndarray) -> None:
        """ Add audio samples to the buffer. """
        with self.lock:
            self.buffer.extend(audio_data.flatten())
            self.samples_added += len(audio_data)

    def get_recognition_chunk(self) -> Optional[np.ndarray]:
        """ Get a full chunk of audio for recognition if available. """
        with self.lock:
            if self.samples_added >= self.target_samples and len(self.buffer) >= self.target_samples:
                self.samples_added = 0

                return np.array(self.buffer, dtype=np.float32)

        return None

    def clear(self) -> None:
        """ Clear the buffer. """
        with self.lock:
            self.buffer.clear()
            self.samples_added = 0
