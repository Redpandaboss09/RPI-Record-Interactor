from protocols import MetadataSource


class FingerprintService(MetadataSource):
    def __init__(self):
        pass

    def get_track_info(self, track_id: str) -> "TrackInfo | None":
        pass
