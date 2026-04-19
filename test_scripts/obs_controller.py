#!/usr/bin/env python3
"""OBS WebSocket controller for the AI video chat benchmark.

Updates the file path of an existing OBS "Media Source" and centers the video
on the canvas.  Used by ``run_test.py`` to feed test videos through the OBS
virtual camera into the Genymotion Android emulator.

Usage::

    python obs_controller.py <video_file_path> [canvas_width canvas_height]

Requirements::

    pip install obsws-python
"""

from __future__ import annotations

import os
import sys

import obsws_python as obs

SOURCE_NAME = "Media Source"
HOST = os.environ.get("OBS_WEBSOCKET_HOST", "localhost")
PORT = int(os.environ.get("OBS_WEBSOCKET_PORT", "4455"))
# Default matches the password baked into the public media-source-server AMI.
# Override via OBS_WEBSOCKET_PASSWORD env var if you run your own OBS instance.
PASSWORD = os.environ.get("OBS_WEBSOCKET_PASSWORD", "iZXEvU9sdOQklOZW")

VIDEO_SIZE = (1280, 720)


def center_source_on_canvas(
    cl: obs.ReqClient,
    source_name: str,
    canvas_size: tuple[int, int],
):
    """Center a scene item on the canvas.  Video is assumed fixed at VIDEO_SIZE."""
    canvas_w, canvas_h = canvas_size
    video_w, video_h = VIDEO_SIZE

    pos_x = (canvas_w - video_w) / 2
    pos_y = (canvas_h - video_h) / 2

    scene_name = cl.get_current_program_scene().scene_name
    scene_items = cl.get_scene_item_list(name=scene_name).scene_items

    item_id = next(
        (item["sceneItemId"] for item in scene_items
         if item["sourceName"] == source_name),
        None,
    )
    if item_id is None:
        print(f"Could not find scene item for source '{source_name}'")
        return False

    cl.set_scene_item_transform(
        scene_name=scene_name,
        item_id=item_id,
        transform={
            "positionX": pos_x,
            "positionY": pos_y,
            "scaleX": 1.0,
            "scaleY": 1.0,
            "rotation": 0.0,
        },
    )
    print(f"Centered video at ({pos_x}, {pos_y})")
    return True


def configure_media_source(
    video_path: str,
    canvas_width: int = 1280,
    canvas_height: int = 720,
):
    """Update Media Source file and center it on the canvas."""
    cl = obs.ReqClient(host=HOST, port=PORT, password=PASSWORD)

    # Verify source exists
    existing = cl.get_input_list()
    if not any(i["inputName"] == SOURCE_NAME for i in existing.inputs):
        print(f"Source '{SOURCE_NAME}' does not exist")
        return False

    if not os.path.isabs(video_path) or not os.path.exists(video_path):
        print(f"Video file not found: {video_path}")
        return False

    # Update file path
    settings = cl.get_input_settings(name=SOURCE_NAME)
    new_settings = settings.input_settings.copy()
    new_settings["local_file"] = video_path
    cl.set_input_settings(name=SOURCE_NAME, settings=new_settings, overlay=True)
    print(f"Updated source '{SOURCE_NAME}' with: {video_path}")

    # Center on canvas
    canvas_size = (canvas_width, canvas_height)
    center_source_on_canvas(cl, SOURCE_NAME, canvas_size)

    # Mute and restart playback
    cl.set_input_mute(name=SOURCE_NAME, muted=True)
    cl.trigger_media_input_action(
        name=SOURCE_NAME,
        action="OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART",
    )
    return True


def main():
    if len(sys.argv) == 2:
        video_file = sys.argv[1]
        canvas_w, canvas_h = 1280, 720
    elif len(sys.argv) == 4:
        video_file = sys.argv[1]
        canvas_w, canvas_h = int(sys.argv[2]), int(sys.argv[3])
    else:
        print("Usage: python obs_controller.py <video_path> [canvas_w canvas_h]")
        sys.exit(1)

    configure_media_source(video_file, canvas_w, canvas_h)


if __name__ == "__main__":
    main()
