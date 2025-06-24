import sys
from PyQt5.QtWidgets import QApplication
from app import KioskApp
from models import AppContext, Config, AudioState
from audio.capture import RealTimeAudioCapture


def main():
    app = QApplication(sys.argv)

    # Create config
    config = Config()

    # Try to initialize fingerprint service
    metadata_service = None
    try:
        from services.fingerprint import FingerprintService
        from config.database import DEJAVU_CONFIG

        metadata_service = FingerprintService(config, DEJAVU_CONFIG)
        print("Fingerprinting service initialized")
    except ImportError:
        print("Dejavu not installed - fingerprinting disabled")
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