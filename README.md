# AI Video Chat Testbed

An open-source testbed for benchmarking AI video chat applications.  It provides the benchmark datasets, a media generation pipeline, and automated test scripts used to evaluate five mainstream AI video chat apps.

## Tested Applications

| App     | Package Name                                |
| ------- | ------------------------------------------- |
| Gemini  | `com.google.android.googlequicksearchbox`   |
| Grok    | `ai.x.grok`                                |
| Doubao  | `com.larus.nova`                            |
| Yuanbao | `com.tencent.hunyuan.app.chat`              |
| Qwen    | `com.aliyun.tongyi`                         |

## Repository Structure

```
ai-video-chat-testbed/
├── README.md                # this file
├── datasets/
│   ├── dataset.csv          # standard benchmark metadata (131 questions)
│   ├── mem_dataset.csv      # memory benchmark metadata (553 questions)
│   ├── generate.py          # media generation script
│   └── README.md            # dataset documentation
└── test_scripts/
    ├── apps.json            # per-app UI automation configuration
    ├── run_test.sh          # convenience wrapper (activates venv)
    ├── run_test.py          # unified test runner
    ├── obs_controller.py    # OBS WebSocket controller
    ├── setup.sh             # virtual camera & audio routing setup
    └── README.md            # test scripts documentation
```

## Testbed Architecture

Each test environment consists of two components:

1. **Media source server** — A Linux desktop (Ubuntu 22.04 + Xfce) running:
   - OBS Studio with a virtual camera (via v4l2loopback)
   - Firefox connected to the Genymotion emulator's web interface
   - PulseAudio virtual sinks for audio routing
   - The test runner scripts

2. **Genymotion Android emulator** — An Android 14 emulator that:
   - Runs the AI video chat app under test
   - Receives camera and microphone input from the media source server through the browser
   - Is connected to the media source server via ADB

**Media flow:**

```
OBS virtual camera → Firefox (browser) → Genymotion camera
PulseAudio sink    → Firefox (browser) → Genymotion microphone
```

The audio routing (configured by `setup.sh`) prevents the AI from hearing its own voice during video calls.

### Media Source Server AMI

A pre-configured media source server is available as an AWS AMI:

| Field     | Value                    |
| --------- | ------------------------ |
| Region    | Hong Kong (ap-east-1)    |
| AMI ID    | `ami-03e6b00ac6ae50f84`  |
| AMI Name  | `media_source_server`    |

The AMI includes Ubuntu 22.04, Xfce desktop (via xrdp), OBS Studio, Firefox, v4l2loopback, and a Python virtual environment at `~/test/measure` with all required packages pre-installed.

## How to Test

### 1. Launch the media source server

Launch an EC2 instance from the AMI above (or set up your own Linux desktop with OBS Studio, Firefox, v4l2loopback, and PulseAudio).

### 2. Connect to the media source server

```bash
ssh -i <your-key.pem> ubuntu@<media_source_server_ip>
```

Or use xrdp to connect with a remote desktop client.

### 3. Connect to the Genymotion Android emulator

- Open Firefox on the media source server and navigate to the Genymotion emulator's IP address.
- ADB connection and root access are handled automatically by `run_test.py` when you pass `--serial <emulator_private_ip>:5555`.

### 4. Activate the Python environment and set up virtual devices

The media source server has a Python virtual environment at `~/test/measure`:

```bash
cd ~/test
source measure/bin/activate
bash setup.sh
```

### 5. Configure OBS Studio

- Open OBS Studio and start the Virtual Camera.
- Set the canvas size according to the app under test (see table below).
- Ensure a "Media Source" input exists and is centered on the canvas.

### 6. Upload test data

Upload the generated test videos and audios to the media source server:

```bash
# On the media source server
mkdir -p ~/test/test_videos ~/test/test_audios
# Copy files from datasets/videos/ to ~/test/test_videos/
# Copy files from datasets/audios/ to ~/test/test_audios/
```

### 7. Run tests

The `run_test.sh` wrapper automatically activates the Python venv, connects ADB, and gets root access:

```bash
cd ~/test
bash run_test.sh --app gemini --serial <emulator_private_ip>:5555 --iterations 2 --interval 300
```

Or activate the venv manually and call `run_test.py` directly:

```bash
cd ~/test
source measure/bin/activate
python run_test.py --app gemini --serial <emulator_private_ip>:5555 --iterations 2
```

See `test_scripts/README.md` for the full CLI reference.

## Canvas Size Reference

Different apps capture different portions of the virtual camera's field of view. To ensure each app sees the complete 1280x720 video, the OBS canvas must be enlarged:

| App     | Canvas Size |
| ------- | ----------- |
| Gemini  | 1828x1028   |
| Grok    | 1706x960    |
| Doubao  | 1334x752    |
| Yuanbao | 1706x960    |
| Qwen    | 1408x792    |
