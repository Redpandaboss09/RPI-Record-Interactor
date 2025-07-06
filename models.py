from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import protocols as pr


@dataclass
class AudioState:
    volume_rms: float = 0.0
    frequency_bins: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class TrackInfo:
    title: str
    artist: str
    duration: int
    audio_file_path: str
    album: Optional[str] = None
    album_art_path: Optional[str] = None
    lyrics_file_path: Optional[str] = None
    track_number: Optional[int] = None
    total_tracks: Optional[int] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> 'TrackInfo':
        return cls(**data)


@dataclass
class Config:
    # File paths
    db_path: str = "database/collection"
    log_dir: str = "logs"
    music_library: str = "music_data/mp3"

    # Audio settings
    buffer_size: int = 2048
    sample_rate: int = 44100
    audio_device_index: int | None = None
    noise_floor_db: float = -60.0
    silence_threshold: float = 0.001

    # Spectrogram settings
    stft_window_size: int = 2048
    stft_hop_size: int = 512
    neighborhood_size: int = 10
    peak_threshold_db: float = -40.0

    # Constellation parameters
    fan_value: int = 10
    min_time_delta: int = 0  # In frames
    max_time_delta: int = 200  # In frames, ~3 seconds

    # Recognition parameters
    min_match_confidence: float = 0.05
    min_absolute_matches: int = 5

    # Procession options
    skip_existing: bool = False
    target_sample_rate: int = 44100


@dataclass
class AppContext:
    audio: "pr.AudioSource"
    metadata: "pr.MetadataSource"
    audio_state: AudioState
    config: Config
