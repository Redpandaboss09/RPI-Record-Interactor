from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import protocols as pr


@dataclass
class AudioState:
    volume_rms: float
    frequency_bins: list[float]


@dataclass(frozen=True)
class TrackInfo:
    id: str
    title: str
    artist: str
    album: str | None = None
    duration: float | None = None


@dataclass
class Config:
    buffer_size: int = 2048
    sample_rate: int = 44100
    audio_device_index: int | None = None


@dataclass
class AppContext:
    audio: "pr.AudioSource"
    metadata: "pr.MetadataSource"
    audio_state: AudioState
    config: Config
