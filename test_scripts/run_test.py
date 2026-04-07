#!/usr/bin/env python3
"""Unified automated test runner for AI video chat benchmark applications.

This script replaces the per-app shell scripts (``auto_test_<app>.sh`` and
``auto_test_<app>_once.sh``) with a single, configurable Python runner.

It reads per-app UI automation commands from ``apps.json``, iterates over
every test video/audio pair in the configured directories, and for each
pair executes the full test lifecycle:

    force-stop app -> launch -> new conversation -> start call ->
    enable camera -> start captures -> play video + audio ->
    wait for response -> stop captures -> end call -> pull artifacts

Usage examples::

    # Run one full pass of all videos on Gemini
    python run_test.py --app gemini

    # Run three iterations with 5-minute intervals
    python run_test.py --app grok --iterations 3 --interval 300

    # Resume from a specific video
    python run_test.py --app doubao --start-from real_sample_9_1
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
APPS_JSON = SCRIPT_DIR / "apps.json"

STEP_ORDER = ["new_conversation", "start_call", "enable_camera"]

# Time intervals between ADB operations (seconds)
SLEEP_BETWEEN_COMMANDS = 3   # between consecutive taps/swipes in a step
SLEEP_AFTER_LAUNCH = 10      # wait for app UI to fully load
SLEEP_AFTER_STEP = 3         # after completing a major step
SLEEP_AFTER_END_CALL = 5     # after ending the call before pulling artifacts
RESPONSE_WAIT = 30           # how long to wait while audio/video plays


def load_app_config(app_name: str) -> dict:
    with APPS_JSON.open() as fh:
        data = json.load(fh)
    apps = data.get("apps", {})
    if app_name not in apps:
        available = ", ".join(sorted(apps))
        raise SystemExit(f"Unknown app '{app_name}'. Available: {available}")
    return apps[app_name]


def run_adb(cmd: str, serial: str | None = None) -> str:
    """Run a single ADB command and return its stdout."""
    if serial:
        cmd = cmd.replace("adb ", f"adb -s {serial} ", 1)
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=30
    )
    return result.stdout.strip()


def execute_step_commands(commands: list[dict], serial: str | None = None):
    """Execute a list of tap/swipe/noop commands with sleeps between them."""
    for cmd in commands:
        cmd_type = cmd.get("type", "noop")
        if cmd_type == "noop":
            continue
        elif cmd_type == "tap":
            run_adb(f"adb shell input tap {cmd['x']} {cmd['y']}", serial)
        elif cmd_type == "swipe":
            duration = cmd.get("duration_ms", "")
            dur_arg = f" {duration}" if duration else ""
            run_adb(
                f"adb shell input swipe {cmd['x1']} {cmd['y1']} "
                f"{cmd['x2']} {cmd['y2']}{dur_arg}",
                serial,
            )
        time.sleep(SLEEP_BETWEEN_COMMANDS)


def discover_test_cases(
    videos_dir: Path, audios_dir: Path
) -> list[tuple[str, Path, Path]]:
    """Find matched video/audio pairs.

    Returns a list of ``(basename, video_path, audio_path)`` sorted by name.
    """
    cases = []
    for vpath in sorted(videos_dir.glob("*.mp4")):
        apath = audios_dir / f"{vpath.stem}.wav"
        if apath.exists():
            cases.append((vpath.stem, vpath, apath))
        else:
            print(f"WARNING: no matching audio for {vpath.name}, skipping")
    return cases


def run_single_test(
    app_cfg: dict,
    test_id: str,
    video_path: Path,
    audio_path: Path,
    artifacts_dir: Path,
    serial: str | None,
):
    """Execute one complete test cycle for a single video/audio pair."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    prefix = f"{timestamp}_{test_id}"

    pcap_dir = artifacts_dir / "pcap"
    audio_dir = artifacts_dir / "audio"
    screenshot_dir = artifacts_dir / "screenshots"
    for d in (pcap_dir, audio_dir, screenshot_dir):
        d.mkdir(parents=True, exist_ok=True)

    dump_file = "/data/local/tmp/capture.pcap"
    canvas_w, canvas_h = app_cfg["canvas_size"]

    # --- Force-stop and relaunch ---
    adb_prefix = f"adb -s {serial}" if serial else "adb"
    reset_cmd = app_cfg["reset_command"]
    run_adb(f"adb {' '.join(reset_cmd)}", serial)
    time.sleep(SLEEP_BETWEEN_COMMANDS)

    launch_cmd = app_cfg["launch_command"]
    run_adb(f"adb {' '.join(launch_cmd)}", serial)
    time.sleep(SLEEP_AFTER_LAUNCH)

    # --- Execute UI steps ---
    steps = app_cfg.get("steps", {})
    for step_name in STEP_ORDER:
        step = steps.get(step_name, {})
        commands = step.get("commands", [])
        execute_step_commands(commands, serial)
        time.sleep(SLEEP_AFTER_STEP)

    # --- Start captures ---
    tcpdump_proc = subprocess.Popen(
        f"{adb_prefix} shell tcpdump -i wlan0 -w {dump_file}",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    parecord_proc = subprocess.Popen(
        f"parecord --device=mix.monitor {audio_dir / f'{prefix}.wav'}",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # --- Play video and audio ---
    obs_controller = SCRIPT_DIR / "obs_controller.py"
    subprocess.run(
        [sys.executable, str(obs_controller), str(video_path),
         str(canvas_w), str(canvas_h)],
        check=False,
    )
    paplay_proc = subprocess.Popen(
        f"paplay --device=android {audio_path}",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # --- Wait for response ---
    time.sleep(RESPONSE_WAIT)

    # --- Stop captures ---
    for proc in (tcpdump_proc, parecord_proc, paplay_proc):
        try:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    # --- End call ---
    end_commands = steps.get("end_call", {}).get("commands", [])
    execute_step_commands(end_commands, serial)
    time.sleep(SLEEP_AFTER_END_CALL)

    # --- Pull artifacts ---
    run_adb(f"adb pull {dump_file} {pcap_dir / f'{prefix}.pcap'}", serial)
    run_adb(f"adb shell rm {dump_file}", serial)

    screenshot_file = "/data/local/tmp/screenshot.png"
    run_adb(f"adb shell screencap -p {screenshot_file}", serial)
    run_adb(
        f"adb pull {screenshot_file} {screenshot_dir / f'{prefix}.png'}",
        serial,
    )
    run_adb(f"adb shell rm {screenshot_file}", serial)

    print(f"  Artifacts saved with prefix: {prefix}")


def main():
    parser = argparse.ArgumentParser(
        description="Automated test runner for AI video chat benchmark apps."
    )
    parser.add_argument(
        "--app",
        required=True,
        help="App to test (gemini, grok, doubao, yuanbao, qwen).",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Number of full passes through all videos (default: 1).",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Seconds to sleep between consecutive test cases (default: 300).",
    )
    parser.add_argument(
        "--start-from",
        default=None,
        help="Resume from this video basename (without extension).",
    )
    parser.add_argument(
        "--serial",
        default=None,
        help="ADB device serial (e.g., 172.31.12.245:5555). "
             "Omit to use the default device.",
    )
    parser.add_argument(
        "--videos-dir",
        default="test_videos",
        help="Directory containing test .mp4 files (default: test_videos).",
    )
    parser.add_argument(
        "--audios-dir",
        default="test_audios",
        help="Directory containing test .wav files (default: test_audios).",
    )
    parser.add_argument(
        "--artifacts-dir",
        default="artifacts",
        help="Root directory for output artifacts (default: artifacts).",
    )
    args = parser.parse_args()

    app_cfg = load_app_config(args.app)
    videos_dir = Path(args.videos_dir)
    audios_dir = Path(args.audios_dir)
    artifacts_dir = Path(args.artifacts_dir)

    if not videos_dir.is_dir():
        raise SystemExit(f"Videos directory not found: {videos_dir}")
    if not audios_dir.is_dir():
        raise SystemExit(f"Audios directory not found: {audios_dir}")

    cases = discover_test_cases(videos_dir, audios_dir)
    if not cases:
        raise SystemExit("No video/audio pairs found.")

    # Handle --start-from
    if args.start_from:
        start = args.start_from.replace(".mp4", "")
        found = False
        trimmed = []
        for c in cases:
            if not found and c[0] != start:
                continue
            found = True
            trimmed.append(c)
        if not found:
            raise SystemExit(f"Video '{start}' not found in {videos_dir}")
        cases = trimmed
        print(f"Starting from {start} ({len(cases)} videos remaining)")

    # Ensure adb root
    run_adb("adb root", args.serial)

    print(f"App: {args.app}")
    print(f"Videos: {len(cases)}")
    print(f"Iterations: {args.iterations}")
    print(f"Interval: {args.interval}s\n")

    total_run = 0
    for iteration in range(1, args.iterations + 1):
        print(f"=== Iteration {iteration}/{args.iterations} ===")
        for i, (test_id, vpath, apath) in enumerate(cases, 1):
            total_run += 1
            print(f"[{i}/{len(cases)}] Test #{total_run}: {test_id}")

            run_single_test(
                app_cfg=app_cfg,
                test_id=test_id,
                video_path=vpath,
                audio_path=apath,
                artifacts_dir=artifacts_dir,
                serial=args.serial,
            )

            # Sleep between tests (but not after the very last one)
            is_last = (iteration == args.iterations and i == len(cases))
            if not is_last and args.interval > 0:
                print(f"  Sleeping {args.interval}s before next test...")
                time.sleep(args.interval)

    print(f"\nAll done. {total_run} tests completed.")


if __name__ == "__main__":
    main()
