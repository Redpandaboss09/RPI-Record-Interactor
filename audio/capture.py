from collections import deque

import models as md
import numpy as np
import sounddevice as sd
import threading


class RealTimeAudioCapture:
    def __init__(self, config: md.Config):
        self.config = config
        self._sample_rate = config.sample_rate

        self.ring_buffer = deque(maxlen=config.buffer_size * 4)

        self.lock = threading.Lock()

        self.stream = None

    def callback(self, indata, frames, time, status):
        """ Callback function for audio capture, called from audio thread """
        if status:
            print(f"Audio callback status: {status}")

        # Converts to mono if in stereo
        if indata.shape[1] == 2:
            mono = np.mean(indata, axis=1)
        else:
            mono = indata[:, 0]

        with self.lock:
            self.ring_buffer.extend(mono)

    def __enter__(self):
        try:
            #self.__show_devices() # Uncomment for testing

            '''
            self.stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=1,
                callback=self.callback,
                blocksize=self.config.buffer_size,
                dtype=np.float32,
                #device=device # Uncomment to specify device
            )
            '''
            self.stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=2,  # Stereo Mix is stereo
                callback=self.callback,
                blocksize=self.config.buffer_size,
                dtype=np.float32,
                device=20  # Stereo Mix device
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
