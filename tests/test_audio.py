import time
from models import Config, AudioState
from audio.capture import RealTimeAudioCapture
from audio.processing import calculate_rms, compute_fft, group_frequencies


def main():
    config = Config()
    audio_state = AudioState(volume_rms=0.0, frequency_bins=[])

    print("Starting audio capture test...")
    print("Press Ctrl+C to stop\n")

    with RealTimeAudioCapture(config) as audio:
        try:
            while True:
                # Get audio data
                audio_data = audio.get_audio_data()

                # Process it
                rms = calculate_rms(audio_data)
                fft_mags = compute_fft(audio_data)
                bands = group_frequencies(fft_mags, num_bands=32)

                # Update state
                audio_state.volume_rms = rms
                audio_state.frequency_bins = bands.tolist()

                # Display results
                print(f"\rRMS: {rms:6.4f} | ", end="")

                # Simple bar visualization
                for band in bands[:8]:  # Show first 8 bands
                    bar_length = int(band / 10)
                    print("█" * bar_length, end=" ")

                time.sleep(0.05)  # 20 FPS update

        except KeyboardInterrupt:
            print("\n\nStopping...")


if __name__ == "__main__":
    main()