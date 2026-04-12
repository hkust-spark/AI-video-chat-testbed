# Test Scripts

Automated test scripts for benchmarking AI video chat applications.  These scripts drive the full test lifecycle on a media source server connected to a Genymotion Android emulator.

## Contents

| File                | Description                                         |
| ------------------- | --------------------------------------------------- |
| `run_test.sh`       | Convenience wrapper — activates venv and runs tests |
| `run_test.py`       | Main test runner — replaces per-app shell scripts   |
| `apps.json`         | Per-app configuration (tap coordinates, packages)   |
| `obs_controller.py` | OBS WebSocket controller for virtual camera feed    |
| `setup.sh`          | Virtual camera and PulseAudio routing setup         |

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

1. Run the setup script (once per boot):

```bash
cd ~/test
bash setup.sh
```

2. Open OBS Studio:
   - Start the Virtual Camera.
   - Set the canvas size for the app under test (see `apps.json` for canvas sizes).
   - Ensure a source named "Media Source" exists.

3. Connect Firefox to the Genymotion emulator.

4. ADB connection and root access are handled automatically by `run_test.py` when you pass `--serial`.

## Usage

The easiest way is to use the `run_test.sh` wrapper, which activates the venv automatically:

```bash
cd ~/test

# Run one iteration on Gemini
bash run_test.sh --app gemini --serial <emulator_ip>:5555

# Run 3 iterations on Grok with 5-minute intervals
bash run_test.sh --app grok --serial <emulator_ip>:5555 --iterations 3 --interval 300

# Resume from a specific video
bash run_test.sh --app doubao --serial <emulator_ip>:5555 --start-from real_sample_9_1
```

Or activate the venv manually and call `run_test.py` directly:

```bash
source ~/test/measure/bin/activate
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
- `launch_command` — ADB command to start the app
- `reset_commands` — List of ADB commands to stop the app (some apps need multiple force-stops)
- `canvas_size` — OBS canvas dimensions
- `steps` — UI automation steps with tap/swipe coordinates:
  - `new_conversation` — open a fresh conversation
  - `prepare_call` — pre-call actions (e.g., Qwen swipes to reveal the call button)
  - `start_call` — initiate the video call
  - `enable_camera` — turn on the camera
  - `end_call` — hang up

### Canvas Size Reference

Different apps capture different portions of the virtual camera's field of view. To ensure each app sees the complete 1280x720 video, the OBS canvas must be enlarged:

| App         | Gemini    | Grok     | Doubao   | Yuanbao  | Qwen     |
| ----------- | --------- | -------- | -------- | -------- | -------- |
| Canvas Size | 1828x1028 | 1706x960 | 1334x752 | 1706x960 | 1408x792 |

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
