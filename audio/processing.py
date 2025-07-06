from numpy.fft import rfft
from scipy.ndimage import maximum_filter
import numpy as np

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from models import Config


class AudioProcessor:
    """ The AudioProcessor class is used to both prepare raw audio for visualization and fingerprinting. """
    def __init__(self, config: Config):
        self.config = config
        self._window_cache = dict()

        self._window_cache[config.buffer_size] = np.hanning(config.buffer_size)

    def _get_window(self, size: int) -> np.ndarray:
        """ Returns the Hann window of the given size, creating it if it does not exist. """
        if size not in self._window_cache:
            self._window_cache[size] = np.hanning(size)
        return self._window_cache[size]

    def calculate_rms(self, audio_data: np.ndarray) -> float:
        """ RMS (Root Mean Squared) is used to calculate volume of audio input. """
        # In case we encounter silence
        if len(audio_data) == 0 or np.max(np.abs(audio_data)) < 1e-10:
            return 0.0

        return np.sqrt(np.mean(audio_data ** 2))

    def compute_fft_visualization(self, audio_data: np.ndarray) -> np.ndarray:
        """ Computes Raw Fourier Transform over the audio input used for visualization. """
        # In case we encounter silence or empty data
        if len(audio_data) == 0 or np.max(np.abs(audio_data)) < self.config.silence_threshold:
            return np.zeros(len(audio_data) // 2 + 1)

        window = self._get_window(len(audio_data))
        windowed_audio = audio_data * window

        fft_data = rfft(windowed_audio)

        magnitude = np.abs(fft_data)

        magnitude_db = 20 * np.log10(magnitude + 1e-10)

        magnitude_db = np.clip(magnitude_db, -80, 0)
        magnitude_normalized = (magnitude_db + 80) / 80 * 100

        return magnitude_normalized

    def group_frequencies(self, fft_magnitudes: np.ndarray, num_bands: int = 32) -> np.ndarray:
        """ Groups FFT bins into logarithmic bands for visualization. """
        # In case of empty input
        if len(fft_magnitudes) == 0:
            return np.zeros(num_bands)

        num_bins = len(fft_magnitudes)

        min_freq = 20
        max_freq = self.config.sample_rate / 2

        # Generate logarithmically spaced frequency boundaries
        freq_boundaries = np.logspace(
            np.log10(min_freq),
            np.log10(max_freq),
            num_bands + 1
        )

        # Convert frequencies to FFT bin indices
        bin_boundaries = freq_boundaries * num_bins * 2 / self.config.sample_rate
        bin_boundaries = np.clip(bin_boundaries.astype(int), 0, num_bins - 1)

        # Group the FFT bins
        bands = np.zeros(num_bands)
        for i in range(num_bands):
            start_bin = bin_boundaries[i]
            end_bin = bin_boundaries[i + 1]

            if start_bin < end_bin:
                bands[i] = np.mean(fft_magnitudes[start_bin:end_bin])
            else:
                bands[i] = fft_magnitudes[start_bin]

        bands_db = (bands / 100 * 80) - 80
        bands[bands_db < self.config.noise_floor_db] = 0

        return bands

    def compute_stft(self, audio_data: np.ndarray, window_size: int = None, hop_size: int = None) -> np.ndarray:
        """ Computes STFT of the audio input and returns the values in dB scale for peak analysis. """
        # In case we decide to use config values instead
        if window_size is None:
            window_size = self.config.stft_window_size
        if hop_size is None:
            hop_size = self.config.stft_hop_size

        frame_count = 1 + (len(audio_data) - window_size) // hop_size  # Amount of windows we analyze
        stft = np.zeros((frame_count, 1 + window_size // 2), dtype=np.complex128)  # Where results are stored

        window = self._get_window(window_size)  # Get Hann window to reduce edge artifacting

        for k in range(frame_count):
            audio_frame = audio_data[k * hop_size:k * hop_size + window_size]  # Get a chunk of audio
            windowed_frame = audio_frame * window  # Apply window
            stft[k, :] = rfft(windowed_frame)  # Store the chunk

        magnitude = np.abs(stft)  # Get magnitude

        return 20 * np.log10(magnitude + 1e-10)  # Return as decibels

    def extract_peaks(self, spectrogram: np.ndarray):
        # Find local maxima
        neighborhood = np.ones((2*self.config.neighborhood_size+1, 2*self.config.neighborhood_size+1))
        local_max = maximum_filter(spectrogram, footprint=neighborhood) == spectrogram

        # Apply threshold and extract wanted coordinates
        peaks = local_max & (spectrogram > self.config.peak_threshold_db)
        peak_coordinates = np.argwhere(peaks)

        return [(time, freq, spectrogram[time, freq]) for time, freq in peak_coordinates]

    def get_frequency_for_bin(self, bin_index: int, fft_size: int) -> float:
        """ Returns the frequency of the bin at given index. """
        return bin_index * self.config.sample_rate / fft_size
