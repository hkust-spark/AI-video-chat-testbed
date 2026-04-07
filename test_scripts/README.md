# Test Scripts

Automated test scripts for benchmarking AI video chat applications.  These scripts drive the full test lifecycle on a media source server connected to a Genymotion Android emulator.

## Contents

| File                | Description                                        |
| ------------------- | -------------------------------------------------- |
| `run_test.py`       | Main test runner — replaces per-app shell scripts  |
| `apps.json`         | Per-app configuration (tap coordinates, packages)  |
| `obs_controller.py` | OBS WebSocket controller for virtual camera feed   |
| `setup.sh`          | Virtual camera and PulseAudio routing setup        |

## Prerequisites

**On the media source server:**

- Python 3.8+
- ADB (Android Debug Bridge)
- OBS Studio with WebSocket server enabled (port 4455)
- `obsws-python` Python package: `pip install obsws-python`
- PulseAudio (for audio routing)
- v4l2loopback kernel module (for virtual camera)
- Firefox (to connect to the Genymotion emulator)

## Setup

1. Activate the Python environment and run the setup script:

```bash
cd ~/test
source measure/bin/activate
bash setup.sh
```

2. Open OBS Studio:
   - Start the Virtual Camera.
   - Set the canvas size for the app under test (see `apps.json` for canvas sizes).
   - Ensure a source named "Media Source" exists.

3. Connect Firefox to the Genymotion emulator.

4. Connect ADB to the emulator:

```bash
adb connect <emulator_ip>:5555
adb root
```

## Usage

```bash
# Run one iteration on Gemini
python run_test.py --app gemini

# Run 3 iterations on Grok with 5-minute intervals
python run_test.py --app grok --iterations 3 --interval 300

# Resume from a specific video
python run_test.py --app doubao --start-from real_sample_9_1

# Specify ADB serial and custom directories
python run_test.py --app yuanbao \
    --serial 172.31.12.245:5555 \
    --videos-dir ~/test/test_videos \
    --audios-dir ~/test/test_audios \
    --artifacts-dir ~/test/artifacts
```

### CLI Reference

| Argument          | Default       | Description                                   |
| ----------------- | ------------- | --------------------------------------------- |
| `--app`           | (required)    | App to test: gemini, grok, doubao, yuanbao, qwen |
| `--iterations`    | 1             | Number of full passes through all videos      |
| `--interval`      | 300           | Seconds between consecutive test cases        |
| `--start-from`    | (none)        | Resume from a specific video basename         |
| `--serial`        | (default)     | ADB device serial                             |
| `--videos-dir`    | test_videos   | Directory with `.mp4` test videos             |
| `--audios-dir`    | test_audios   | Directory with `.wav` question audio          |
| `--artifacts-dir` | artifacts     | Root directory for captured artifacts         |

## App Configuration

`apps.json` defines per-app settings:

- `package_name` — Android package name
- `launch_command` / `reset_command` — ADB commands to start/stop the app
- `canvas_size` / `video_size` — OBS canvas and video dimensions
- `steps` — UI automation steps (new_conversation, start_call, enable_camera, end_call) with tap/swipe coordinates

## Artifacts

Each test case produces the following artifacts under `--artifacts-dir`:

```
artifacts/
├── pcap/          # Network packet captures from the emulator (tcpdump)
├── audio/         # Audio recordings from the media source server (parecord)
└── screenshots/   # Screenshots from the emulator after each call
```

Files are named `YYYYMMDDHHMMSS_<video_id>.<ext>`.

## Timing

The test runner uses the following time intervals between operations:

- **3 seconds** between consecutive ADB tap/swipe commands
- **10 seconds** after launching the app (wait for UI)
- **3 seconds** after each major step (new conversation, start call, enable camera)
- **30 seconds** response wait (while video and audio play)
- **5 seconds** after ending the call (before pulling artifacts)
- **Configurable** `--interval` seconds between test cases (default: 300)
