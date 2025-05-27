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
  -n, --num-workers INTEGER       Number of parallel worker processes. Defaults to number of CPU cores.  [default: 1]
  -h, --help                      Show this message and exit.
```
