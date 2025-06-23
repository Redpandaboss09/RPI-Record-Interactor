import sys
from PyQt5.QtWidgets import QApplication
from app import KioskApp
from models import AppContext, Config, AudioState
from audio.capture import RealTimeAudioCapture


def main():
    app = QApplication(sys.argv)

    # Create config
    config = Config()

    # Use context manager for audio
    with RealTimeAudioCapture(config) as audio_source:
        # Create context
        context = AppContext(
            config=config,
            audio=audio_source,
            metadata=None,
            audio_state=AudioState()
        )

        # Create and show kiosk
        kiosk = KioskApp(context, dev_mode=True)
        kiosk.show()

        # Run app
        sys.exit(app.exec_())

    # Audio automatically cleaned up when exiting 'with' block


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        input("Press Enter to exit...")