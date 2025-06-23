from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import protocols as pr


@dataclass
class AudioState:
    volume_rms: float = 0.0
    frequency_bins: list[float] = field(default_factory=list)


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
    noise_floor_db: float = -60.0
    silence_threshold: float = 0.001


@dataclass
class AppContext:
    audio: "pr.AudioSource"
    metadata: "pr.MetadataSource"
    audio_state: AudioState
    config: Config
