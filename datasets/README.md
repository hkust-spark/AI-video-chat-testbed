# Benchmark Datasets

This directory contains the benchmark dataset metadata and the media generation script for the AI video chat testbed.

## Overview

- **Standard dataset** (`dataset.csv`): 131 questions across 67 videos covering task types such as Text-Rich Understanding, Object Perception, Counting, Emotion Recognition, and more.
- **Memory dataset** (`mem_dataset.csv`): 553 questions across 56 memory clips derived from 3 source videos, testing whether AI apps can recall earlier context during a video call.

## Downloading Videos

Video files are hosted on the GitHub Releases page for this repository.  Download the two zip archives and extract them:

```bash
# Standard benchmark videos
unzip videos.zip -d datasets/videos/

# Memory benchmark videos (3 source files: mem_1.mp4, mem_2.mp4, mem_3.mp4)
unzip videos_mem.zip -d datasets/videos_mem/
```

## Directory Layout

After downloading videos and running `generate.py`, the directory looks like:

```
datasets/
├── dataset.csv          # standard benchmark metadata
├── mem_dataset.csv      # memory benchmark metadata
├── audio_info.csv       # generated audio duration metadata
├── generate.py          # media generation script
├── videos/              # standard benchmark videos (from GitHub release)
├── audios/              # generated standard question audio (WAV)
├── videos_mem/          # memory source videos (from release) + generated clips
└── audios_mem/          # generated memory question audio (WAV)
```

## CSV Schema

### `dataset.csv`

| Column               | Description                                          |
| -------------------- | ---------------------------------------------------- |
| `video_id`           | Basename of the video file (without `.mp4`)          |
| `video_duration`     | Source video duration in `HH:MM:SS`                  |
| `question_id`        | Sequential question ID within each video (1, 2, 3…)  |
| `question_timestamp` | When the question should be asked in `HH:MM:SS`     |
| `task_type`          | Category of the question                             |
| `question`           | The spoken question text                             |
| `answer`             | Reference answer                                     |

### `mem_dataset.csv`

Same columns as `dataset.csv`.  All rows have `task_type = Memory` and `answer` is intentionally blank.

- `video_id` follows the pattern `mem_X_Y` where `X` is the source video number and `Y` is the clip offset in seconds.
- Each clip has one question every 30 seconds starting from an anchor timestamp, with the final question being the relevant memory question.
- Anchor timestamps: `mem_1` starts at 00:00:30, `mem_2` at 00:00:10, `mem_3` at 00:00:15.

### `audio_info.csv`

| Column     | Description                                                  |
| ---------- | ------------------------------------------------------------ |
| `audio_id` | Standard: `{video_id}_{index}`.  Memory: `mem_X_final`.     |
| `question` | The synthesized question text.                               |
| `duration` | Audio duration in seconds.                                   |

This file is an output of `generate.py`, not an input.

## Generating Media

### Prerequisites

```bash
pip install pandas gTTS pydub
# ffmpeg and ffprobe must be installed and on PATH
```

`gTTS` requires network access to synthesize audio.

### Usage

```bash
# Generate everything for the standard dataset
python generate.py

# Generate only question audio for the standard dataset
python generate.py --outputs audio

# Generate everything for the memory dataset
python generate.py --dataset memory

# Generate only memory video clips (no audio)
python generate.py --dataset memory --outputs video

# Generate both datasets in one run
python generate.py --dataset all

# Process a specific video
python generate.py --video-id real_sample_9_1

# Process a specific memory clip
python generate.py --dataset memory --video-id mem_1_150
```

### What `generate.py` does

**Standard mode** (`--dataset standard`):

1. Reads `dataset.csv` and the `question` column.
2. Synthesizes English question audio with gTTS.
3. Builds the final audio track.  For videos with prefixes `er`, `ma`, `su`, or `sd`, it mixes reduced-volume background audio from the source video under the questions.  For all others, it creates question-only audio.
4. Optionally processes videos: scales to fit within a 1280x720 bounding box and strips audio streams.  Videos already at the target geometry are skipped.

**Memory mode** (`--dataset memory`):

1. Regenerates `mem_dataset.csv` on a strict 30-second grid.
2. Synthesizes question-only audio with gTTS.
3. Clips raw segments from the 3 source videos, scales, and strips audio.
4. Updates `audio_info.csv` with the final-question durations.

### Output geometry

- Exact 1280x720 for 16:9 content.
- For non-16:9 content, the aspect ratio is preserved and the video fits within a 1280x720 bounding box.
- Dimensions are always even (divisible by 2).
