import numpy as np
import sounddevice as sd
import models as md


class RealTimeAudioCapture:
    def __init__(self, config: md.Config):
        self.config = config
        self._sample_rate = config.sample_rate
        self._audio_data = None
        self.stream = None

    def __enter__(self):
        pass

    def __exit__(self):
        pass

    def get_audio_data(self) -> np.ndarray:
        return self._audio_data

    @property
    def sample_rate(self) -> int:
        return self._sample_rate
