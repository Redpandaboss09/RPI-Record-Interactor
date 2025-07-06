import sys
from PyQt5.QtWidgets import QApplication
from app import KioskApp
from models import AppContext, Config, AudioState
from audio.capture import RealTimeAudioCapture


def main():
    app = QApplication(sys.argv)

    # Create config
    config = Config()

    # Initialize fingerprint service with new system
    metadata_service = None
    try:
        from services.fingerprint import FingerprintService

        # Use local music collection database
        metadata_service = FingerprintService(
            config=config,
            cache_db_path="music_collection.db"
        )
        print("Fingerprint recognition service initialized")
        print(f"  Loaded {metadata_service.get_stats()['total_tracks']} tracks")

    except ImportError as e:
        print(f"Could not import fingerprinting service: {e}")
    except Exception as e:
        print(f"Could not initialize fingerprinting: {e}")

    # Use context manager for audio
    with RealTimeAudioCapture(config) as audio_source:
        context = AppContext(
            config=config,
            audio=audio_source,
            metadata=metadata_service,
            audio_state=AudioState()
        )

        # Create and show kiosk
        kiosk = KioskApp(context, dev_mode=True)
        kiosk.show()

        # Run app
        try:
            sys.exit(app.exec_())
        finally:
            # Cleanup
            if metadata_service:
                metadata_service.stop()


if __name__ == "__main__":
    main()