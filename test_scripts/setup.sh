#!/usr/bin/env bash
# Set up virtual camera and audio routing for the AI video chat benchmark.
#
# This script must be run on the media source server (Linux desktop) before
# starting any tests.  It creates:
#
#   - A v4l2loopback virtual camera that OBS Studio outputs to.
#   - PulseAudio null sinks for audio routing so that:
#       * Question audio is played into the "android" sink, whose monitor
#         is picked up by Firefox as the microphone input.
#       * The "mix" sink captures audio output from the Genymotion emulator
#         (via Firefox) for recording with parecord.
#       * A loopback pipes the android sink monitor into the mix sink so
#         both sides of the conversation are recorded.
#
# Run once per boot (or after PulseAudio restarts).

set -euo pipefail

echo "=== Setting up v4l2loopback (virtual camera) ==="
sudo modprobe -r v4l2loopback 2>/dev/null || true
sudo modprobe v4l2loopback card_label="VirtualCamera" exclusive_caps=1
echo "  Virtual camera ready."

echo "=== Setting up PulseAudio sinks ==="
pactl load-module module-null-sink sink_name=android \
    sink_properties='device.description="AndroidOutput"'
pactl load-module module-null-sink sink_name=mix \
    sink_properties='device.description="MixOutput"'
pactl set-default-source android.monitor
pactl set-default-sink mix
pactl load-module module-loopback source=android.monitor sink=mix
echo "  PulseAudio routing ready."

echo ""
echo "Setup complete.  Next steps:"
echo "  1. Open OBS Studio and start the Virtual Camera."
echo "  2. Open Firefox and connect to the Genymotion emulator."
echo "  3. Run: bash run_test.sh --app <app_name> --serial <emulator_ip>:5555 [--iterations N] [--interval SECONDS]"
