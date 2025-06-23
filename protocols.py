from typing import Protocol

import numpy as np


class AudioSource(Protocol):
    def get_audio_data(self) -> np.ndarray:
        pass

    @property
    def sample_rate(self) -> int:
        pass


class MetadataSource(Protocol):
    def get_track_info(self, track_id: str) -> "TrackInfo | None":
        pass


class DisplayMode(Protocol):
    def update(self, dt: float) -> None:
        pass

    def render(self, painter: "QPainter", rect: "QRect") -> None:
        pass