import time
from collections import deque

import models as md
import numpy as np
import sounddevice as sd
import threading


class RealTimeAudioCapture:
    def __init__(self, config: md.Config, max_recording_seconds: float = 0.0):
        self.config = config
        self._sample_rate = config.sample_rate

        if max_recording_seconds > 0:
            required_samples = int(config.sample_rate * max_recording_seconds)
            buffer_capacity = max(config.buffer_size * 4, required_samples)
        else:
            buffer_capacity = config.buffer_size * 4

        self.ring_buffer = deque(maxlen=buffer_capacity)

        self.lock = threading.Lock()

        self.stream = None

    def callback(self, indata, frames, time, status):
        """ Callback function for audio capture, called from audio thread """
        if status:
            print(f"Audio callback status: {status}")

        # Converts to mono if in stereo
        if indata.shape[1] == 2:
            mono = np.mean(indata, axis=1)
        elif indata.shape[1] == 1:
            mono = indata[:, 0]
        else:
            mono = indata.flatten()

        with self.lock:
            self.ring_buffer.extend(mono)

    def __enter__(self):
        try:
            # self.__show_devices()  # Uncomment for testing

            self.stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=2,
                callback=self.callback,
                blocksize=self.config.buffer_size,
                dtype=np.float32,
                device=self.config.audio_device_index
            )

            self.stream.start()
            return self

        except sd.PortAudioError as e:
            raise RuntimeError(f"Failed to open audio device: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Audio initialization failed: {e}") from e

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.stream:
            self.stream.stop()
            self.stream.close()

        with self.lock:
            self.ring_buffer.clear()

    def get_audio_data(self) -> np.ndarray:
        """ Returns the latest audio buffer """
        with self.lock:
            # Gets the latest samples
            buffer_list = list(self.ring_buffer)

        # Return last samples of size = buffer_size
        if len(buffer_list) >= self.config.buffer_size:
            return np.array(buffer_list[-self.config.buffer_size:], dtype=np.float32)
        else:
            # If we don't have enough data yet, we return silence
            return np.zeros(self.config.buffer_size, dtype=np.float32)

    def collect_audio(self, duration_seconds: float) -> np.ndarray:
        """ Collects audio for a specific duration. """
        samples_needed = int(self._sample_rate * duration_seconds)

        # Clear the buffer first to ensure we get fresh audio
        with self.lock:
            self.ring_buffer.clear()

        # Wait for buffer to fill
        start_time = time.time()
        timeout = duration_seconds + 2.0  # Add some buffer time

        while True:
            with self.lock:
                current_samples = len(self.ring_buffer)

            if current_samples >= samples_needed:
                break

            if time.time() - start_time > timeout:
                raise TimeoutError(f"Failed to collect {duration_seconds} seconds of audio. "
                                   f"Only got {current_samples / self._sample_rate:.2f} seconds")

            time.sleep(0.01)

        # Get the collected audio
        with self.lock:
            buffer_list = list(self.ring_buffer)

        # Return the requested duration (take from the end to get the most recent)
        audio_data = np.array(buffer_list[-samples_needed:], dtype=np.float32)
        return audio_data

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @staticmethod
    def __show_devices():
        """ Prints available audio devices out (Used mainly for debugging) """
        devices = sd.query_devices()
        print("Available audio devices:")
        for i, device in enumerate(devices):
            print(f"{i}: {device['name']} - {device['max_input_channels']} in, {device['max_output_channels']} out")
