from numpy.fft import rfft
import numpy as np


def calculate_rms(audio_data: np.ndarray) -> float:
    """ RMS (Root Mean Squared) is used to calculate volume of audio input """
    # In case we encounter silence
    if len(audio_data) == 0 or np.max(np.abs(audio_data)) < 1e-10:
        return 0.0

    return np.sqrt(np.mean(audio_data**2))


def compute_fft(audio_data: np.ndarray, silence_threshold: float = 0.001) -> np.ndarray:
    """ Computes Raw Fourier Transform over the audio input """
    # In case we encounter silence or empty data
    if len(audio_data) == 0 or np.max(np.abs(audio_data)) < silence_threshold:
        return np.zeros(len(audio_data) // 2 + 1)

    window = np.hanning(len(audio_data))
    windowed_audio = audio_data * window

    fft_data = rfft(windowed_audio)

    magnitude = np.abs(fft_data)

    magnitude_db = 20 * np.log10(magnitude + 1e-10)

    magnitude_db = np.clip(magnitude_db, -80, 0)
    magnitude_normalized = (magnitude_db + 80) / 80 * 100

    return magnitude_normalized


def group_frequencies(fft_magnitudes: np.ndarray, num_bands: int = 32,
                      sample_rate: int = 44100, noise_floor_db: float = -60.0) -> np.ndarray:
    """
    Groups FFT bins into logarithmic bands for visualization

    Args:
        fft_magnitudes: Output from compute_fft()
        num_bands: How many frequency bands for visualization
        sample_rate: Used to calculate actual frequencies

    Returns:
        Array of length `num_bands` with averaged magnitude per band
    """
    # In case of empty input
    if len(fft_magnitudes) == 0:
        return np.zeros(num_bands)

    num_bins = len(fft_magnitudes)

    min_freq = 20
    max_freq = sample_rate / 2

    # Generate logarithmically spaced frequency boundaries
    freq_boundaries = np.logspace(
        np.log10(min_freq),
        np.log10(max_freq),
        num_bands + 1
    )

    # Convert frequencies to FFT bin indices
    bin_boundaries = freq_boundaries * num_bins * 2 / sample_rate
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
    bands[bands_db < noise_floor_db] = 0

    return bands
