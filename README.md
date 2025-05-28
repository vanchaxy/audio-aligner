# Audio-Aligner

Audio-Aligner is a CLI tool designed to accurately synchronize audio tracks from multiple video sources.

## Usage

```bash
Usage: audio-aligner-cli [OPTIONS] REFERENCE_VIDEO SECONDARY_VIDEO

Options:
  -ra, --ref-audio-track INTEGER  Audio track number (0-indexed) from the reference video.  [default: 0]
  -sa, --sec-audio-track INTEGER  Audio track number (0-indexed) from the secondary video.  [default: 0]
  -m, --method [rms|onset]        Algorithm for feature extraction and comparison.  [default: onset]
  -md, --max-duration INTEGER     Maximum duration (seconds) from the start of each video to process. 0 for full length. [default: 0]
  -cd, --chunk-duration FLOAT     Duration (seconds) of audio chunks for parallel processing.  [default: 300]
  -sr, --sample-rate INTEGER      Target sampling rate (Hz) for audio processing.  [default: 48000]
  -n, --num-workers INTEGER       Number of parallel worker processes.  [default: 1]
  -h, --help                      Show this message and exit.
```

## Memory Requirements

Memory usage depends on audio length, sample rate, and processing settings.

*   **Audio Data:** Loading raw audio (48kHz, 32-bit float) requires approximately **11 MB of RAM per minute per track**. For two tracks, this is 22 MB/minute.
    *   Example: 2-hour videos (`--max-duration 7200`) will load `120 min * 22 MB/min ≈ 2.6 GB` for the audio data in the main process.

*   **Chunk Processing (Per Worker):** Each worker processing a chunk incurs additional memory.
    *   For the default `onset` method this can be around **700 MB per minute of `--chunk-duration` per worker.**
    *   The `rms` method is significantly less memory-intensive per worker.

*   **Overall Example:** With default parameters (`method=onset`, `sr=48000`, `--max-duration` for 2 hours, `--chunk-duration=300s` (5 min), `num-workers=1`), total peak RAM usage can be around **6 GB**. This setup takes approximately 5 minutes to process on an i7-13700HX CPU.

**Estimated RAM Usage Formula (MB):**

The following formula approximates RAM usage in MB, based on observed values with default `onset` settings:

`Total RAM (MB) = ( (MAX_DURATION_S * SAMPLE_RATE_HZ * 8) + (CHUNK_DURATION_S * NUM_WORKERS * WORKER_FACTOR_BYTES_PER_S) ) / (1024 * 1024)`

Where:
*   `MAX_DURATION_S`: Value of `--process-duration` (if 0, use full video length in seconds).
*   `SAMPLE_RATE_HZ`: Value of `--sample-rate`.
*   `8`: Represents bytes for stereo audio (2 tracks * 4 bytes/sample for float32).
*   `CHUNK_DURATION_S`: Value of `--chunk-duration`.
*   `NUM_WORKERS`: Value of `--num-workers`.
*   `WORKER_FACTOR_BYTES_PER_S`: 12288000 (1000 (millisecond accuracy) * 1024 (STFT parameter) * 8+4(per element memory for spectrogram))

**Example Calculation (2-hour videos, default parameters):**
Using `MAX_DURATION_S = 120 * 60 = 7200s`, `SAMPLE_RATE_HZ = 48000`, `CHUNK_DURATION_S = 300s`, `NUM_WORKERS = 1`, `WORKER_FACTOR_BYTES_PER_S = 12232358.4` (approx 700MB/min):

`RAM_MB = ( (7200 * 48000 * 8) + (300 * 1 * 12288000) ) / (1024*1024) ≈ 6152 MB ≈ 6.0 GB`

**Managing Memory Usage:**

*   Decrease `--chunk-duration` (especially effective for `onset` method).
*   Decrease `--num-workers`.
*   Use `rms` method instead of `onset`.
*   Decrease `--process-duration`.
*   Decrease `--sample-rate`.

**Processing Time:**

*   Processing time scales with `--max-duration`.
*   Increase `--num-workers` to reduce time (at the cost of RAM).
*   `onset` method is generally slower than `rms`.

## How It Works

The tool follows these steps to determine the audio delay:

1.  **Audio Extraction:**
    *   Extracts audio from the specified tracks of both the reference and secondary video files.
    *   Alternatively, can directly process provided audio files.
    *   If `--max-duration` is set (e.g., to 1800 for 30 minutes), only the initial segment of this duration is 
    extracted from each audio source. Otherwise, the full audio is used.

2.  **Preprocessing:**
    *   Converts both audio streams to WAV format internally.
    *   Resamples audio from both sources to a consistent sample rate (default: 48000 Hz, controlled by `--sample-rate`)
    to ensure accurate comparison.
    *   Converts audio to mono by averaging channels if the original is stereo or multi-channel.

3.  **Chunking:**
    *   Divides the audio streams into smaller, manageable chunks.
    *   The duration of these chunks is controlled by `--chunk-duration` (default: 300 seconds / 5 minutes).

4.  **Feature Aggregation (per chunk):**
    *   For each corresponding pair of chunks (one from reference, one from secondary), a feature time series is
    generated at a high temporal resolution (aiming for ~1 millisecond).
    *   Two methods are available (`--method`):
        *   **`onset` (default):** Calculates an onset strength envelope. This represents the "suddenness" or intensity
        of new sound events occurring at each millisecond.
        *   **`rms`:** Calculates a Root Mean Square (RMS) energy envelope. This represents the loudness of the audio
        over a very short window (~12 milliseconds) at each millisecond.

5.  **Cross-Correlation (per chunk):**
    *   For each pair of feature time series, the algorithm finds the time offset (delay) that results in the highest
    cross-correlation score.
    *   This determines the most likely delay for that specific chunk.

6.  **Results & Aggregation:**
    *   The tool outputs the estimated delay found for each individual chunk pair.
    *   It then calculates and displays aggregate statistics from all chunk delays, such as:
        *   **Median:** Often the most robust estimate of the overall delay.
        *   **Mean (Average):** The average delay.
        *   **Min/Max:** The minimum and maximum delays found across chunks.
