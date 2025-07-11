# The Shazam-Like Recognition Process

*Disclaimer:*

The following process is taken from the original Shazam paper by Avery Li-Chun Wang, ["An Industrial-Strength Audio 
Search Algorithm"](https://www.ee.columbia.edu/~dpwe/papers/Wang03-shazam.pdf). As to best explain the process / train
of thought going into the design of my program, I feel it is fitting to explain the process in my own words, as well as
going into project-specific design. I do not come from a background in audio processing, so I may leave out some 
details but will link relevant info! 

## Audio Processing
First, we need to gather audio in a format that we can work with. For the purpose of this project, we read music in
real-time from a audio input device at a sample rate of 44100 Hz (chosen for overall compatibility). The audio sample is
fed into a buffer of our desired buffer size (by default, we gather a buffer size of 8192 samples) or by the length of
our desired $\text{sample rate} \cdot \text{desired length}$. From this buffer, we create a numpy array of the audio 
samples, which is when we get into the first step of the primary process.

### Step 1: Short-Time Fourier Transform (STFT)
Sound is naturally just time-based waveform, but we need a way to analyze content like pitch. To do so, we use a Fourier
Transform to convert the time-based waveform into a frequency-based representation. More specifically, we use an 
algorithm called the **Short-Time Fourier Transform (STFT)** to break the audio sample into smaller chunks, or "frames".