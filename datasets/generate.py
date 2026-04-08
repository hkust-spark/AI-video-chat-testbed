"""Generate question audio tracks and processed videos for the AI video chat
benchmark datasets.

This script reads ``dataset.csv`` and ``dataset_mem.csv``, synthesises spoken
question audio using Google Text-to-Speech, and optionally processes the source
videos (scaling, stripping audio, and clipping memory segments).

Differences from the internal ``generate_audio.py``:

* Reads a single ``question`` column (no ``original_question`` / ``refined_question``).
* Flattened directory layout: ``videos/``, ``audios/``, ``videos_mem/``, ``audios_mem/``.
* No video tail-padding (``tpad``).  Videos keep their original duration.
* ``--dataset all`` processes both standard and memory in one invocation.

Usage examples::

    # Generate everything for the standard dataset
    python generate.py

    # Generate only question audio for the memory dataset
    python generate.py --dataset memory --outputs audio

    # Process both datasets end-to-end
    python generate.py --dataset all
"""

from __future__ import annotations

import argparse
import csv
import io
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from gtts import gTTS
from pydub import AudioSegment

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATASET_DIR = Path(__file__).resolve().parent
DATASET_CSV = DATASET_DIR / "dataset.csv"
MEMORY_DATASET_CSV = DATASET_DIR / "dataset_mem.csv"
AUDIO_INFO_CSV = DATASET_DIR / "audio_info.csv"

VIDEO_DIR = DATASET_DIR / "videos"
AUDIO_DIR = DATASET_DIR / "audios"
VIDEO_MEM_DIR = DATASET_DIR / "videos_mem"
AUDIO_MEM_DIR = DATASET_DIR / "audios_mem"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BACKGROUND_AUDIO_PREFIXES = {"er", "ma", "su", "sd"}
BACKGROUND_AUDIO_RATIO = 0.2
TARGET_MAX_WIDTH = 1280
TARGET_MAX_HEIGHT = 720

EXPECTED_DATASET_COLUMNS = [
    "video_id",
    "video_duration",
    "question_id",
    "question_timestamp",
    "task_type",
    "question",
    "answer",
]
EXPECTED_AUDIO_INFO_COLUMNS = ["audio_id", "question", "duration"]

MEMORY_IRRELEVANT_QUESTIONS = [
    "Could you tell me a joke?",
    "Could you tell me another joke?",
    "Could you tell me something about yourself?",
    "Could you recommend a comedy movie?",
    "Could you recommend a romantic movie?",
    "Could you recommend a horror movie?",
    "Could you recommend a science fiction movie?",
    "Could you recommend an anime movie?",
    "Could you recommend a good book?",
    "Could you recommend a pop song?",
    "Could you recommend a rock song?",
    "Could you recommend a jazz song?",
    "What is the capital of France?",
    "What is the capital of Japan?",
    "What is the capital of China?",
    "What is the capital of Korea?",
    "What is the capital of Canada?",
    "What is the capital of Australia?",
    "What is the capital of Germany?",
]

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VideoEntry:
    video_id: str
    video_path: Path
    audio_output_path: Path
    video_output_path: Path


@dataclass(frozen=True)
class QuestionItem:
    audio_id: str
    question_index: int
    timestamp_text: str
    timestamp_ms: int
    text: str


@dataclass(frozen=True)
class ScheduledQuestion:
    timestamp_text: str
    timestamp_ms: int
    text: str


@dataclass(frozen=True)
class MemorySourceConfig:
    base_id: str
    video_path: Path
    anchor_ms: int
    final_question: str


@dataclass(frozen=True)
class MemoryClipEntry:
    video_id: str
    base_id: str
    source_video_path: Path
    raw_clip_duration_ms: int
    audio_output_path: Path
    video_output_path: Path


MEMORY_SOURCE_CONFIGS = (
    MemorySourceConfig(
        base_id="mem_1",
        video_path=VIDEO_MEM_DIR / "mem_1.mp4",
        anchor_ms=30_000,
        final_question=(
            "Do you remember where I was at the beginning before the "
            "raptor encounter in Jurassic World?"
        ),
    ),
    MemorySourceConfig(
        base_id="mem_2",
        video_path=VIDEO_MEM_DIR / "mem_2.mp4",
        anchor_ms=10_000,
        final_question=(
            "Do you remember the broker's name that appeared at the beginning?"
        ),
    ),
    MemorySourceConfig(
        base_id="mem_3",
        video_path=VIDEO_MEM_DIR / "mem_3.mp4",
        anchor_ms=15_000,
        final_question=(
            "Do you remember what animals were in the paintings that "
            "appeared at the beginning?"
        ),
    ),
)
MEMORY_SOURCE_MAP = {cfg.base_id: cfg for cfg in MEMORY_SOURCE_CONFIGS}

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate question audio and processed videos for the benchmark."
    )
    parser.add_argument(
        "--dataset",
        choices=("standard", "memory", "all"),
        default="standard",
        help="Which dataset pipeline to run (default: standard).",
    )
    parser.add_argument(
        "--video-id",
        action="append",
        dest="video_ids",
        default=[],
        help="Process only the given video ID(s). Repeat to select several.",
    )
    parser.add_argument(
        "--outputs",
        choices=("all", "audio", "video"),
        default="all",
        help="What to generate: audio only, video only, or both (default: all).",
    )
    return parser.parse_args()

# ---------------------------------------------------------------------------
# Helpers – system & ffmpeg
# ---------------------------------------------------------------------------


def ensure_dependencies():
    missing = [b for b in ("ffmpeg", "ffprobe") if shutil.which(b) is None]
    if missing:
        raise RuntimeError(f"Missing required system binaries: {', '.join(missing)}")


def run_command(command, capture_output=False):
    kwargs: dict = {"check": True, "text": True}
    if capture_output:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    try:
        return subprocess.run(command, **kwargs)
    except subprocess.CalledProcessError as exc:
        cmd_text = " ".join(str(p) for p in command)
        stderr_text = exc.stderr.strip() if exc.stderr else ""
        raise RuntimeError(f"Command failed: {cmd_text}\n{stderr_text}") from exc

# ---------------------------------------------------------------------------
# Helpers – time conversion
# ---------------------------------------------------------------------------


def hms_to_milliseconds(ts: str) -> int:
    parts = ts.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp format: {ts}")
    h, m, s = (int(p) for p in parts)
    return ((h * 3600) + (m * 60) + s) * 1000


def seconds_to_hms(total_seconds: int) -> str:
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_duration_value(duration_ms: int) -> str:
    return f"{duration_ms / 1000:.3f}".rstrip("0").rstrip(".")

# ---------------------------------------------------------------------------
# Helpers – video probing
# ---------------------------------------------------------------------------


def probe_video_duration_ms(video_path: Path) -> int:
    result = run_command(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True,
    )
    return int(math.ceil(float(result.stdout.strip()) * 1000))


def probe_video_geometry(video_path: Path) -> tuple[int, int]:
    result = run_command(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0:s=x",
            str(video_path),
        ],
        capture_output=True,
    )
    w, h = result.stdout.strip().split("x")
    return int(w), int(h)


def has_audio_stream(video_path: Path) -> bool:
    result = run_command(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=index",
            "-of", "csv=p=0",
            str(video_path),
        ],
        capture_output=True,
    )
    return bool(result.stdout.strip())

# ---------------------------------------------------------------------------
# Helpers – geometry
# ---------------------------------------------------------------------------


def is_close_to_sixteen_by_nine(w: int, h: int) -> bool:
    return abs((w * 9) - (h * 16)) <= 2


def compute_target_geometry(w: int, h: int) -> tuple[int, int]:
    if is_close_to_sixteen_by_nine(w, h):
        return TARGET_MAX_WIDTH, TARGET_MAX_HEIGHT
    scale = min(TARGET_MAX_WIDTH / w, TARGET_MAX_HEIGHT / h)
    tw = max(2, int(math.floor((w * scale) / 2) * 2))
    th = max(2, int(math.floor((h * scale) / 2) * 2))
    return tw, th

# ---------------------------------------------------------------------------
# Helpers – CSV I/O
# ---------------------------------------------------------------------------


def write_csv_rows(path: Path, fieldnames: list[str], rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_standard_dataset() -> pd.DataFrame:
    df = pd.read_csv(DATASET_CSV, keep_default_na=False)
    missing = set(EXPECTED_DATASET_COLUMNS) - set(df.columns)
    if missing:
        raise RuntimeError(
            f"dataset.csv is missing columns: {', '.join(sorted(missing))}"
        )
    return df

# ---------------------------------------------------------------------------
# Helpers – audio synthesis
# ---------------------------------------------------------------------------


def synthesize_question_audio(text: str, cache: dict) -> AudioSegment:
    if text in cache:
        return cache[text]
    tts = gTTS(text=text, lang="en", slow=False)
    buf = io.BytesIO()
    tts.write_to_fp(buf)
    buf.seek(0)
    seg = AudioSegment.from_file(buf, format="mp3")
    cache[text] = seg
    return seg


def ensure_audio_length(audio: AudioSegment, target_ms: int) -> AudioSegment:
    if len(audio) >= target_ms:
        return audio
    return audio + AudioSegment.silent(duration=target_ms - len(audio))


def scale_background_audio(
    background: AudioSegment, reference: AudioSegment
) -> AudioSegment:
    if background.dBFS == float("-inf") or reference.dBFS == float("-inf"):
        return background
    target_dbfs = reference.dBFS + (20 * math.log10(BACKGROUND_AUDIO_RATIO))
    return background.apply_gain(target_dbfs - background.dBFS)


def export_audio_track(audio: AudioSegment, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    audio.export(path, format="wav")

# ---------------------------------------------------------------------------
# Standard dataset – question map
# ---------------------------------------------------------------------------


def build_standard_question_map(
    df: pd.DataFrame,
) -> dict[str, list[QuestionItem]]:
    qmap: dict[str, list[QuestionItem]] = {}
    for video_id, group in df.groupby("video_id", sort=False):
        ordered = group.sort_values("question_timestamp", kind="stable").reset_index(
            drop=True
        )
        items = []
        for idx, row in ordered.iterrows():
            items.append(
                QuestionItem(
                    audio_id=f"{video_id}_{idx}",
                    question_index=idx,
                    timestamp_text=row.question_timestamp,
                    timestamp_ms=hms_to_milliseconds(row.question_timestamp),
                    text=str(row.question).strip(),
                )
            )
        qmap[video_id] = items
    return qmap

# ---------------------------------------------------------------------------
# Standard dataset – audio info rows
# ---------------------------------------------------------------------------


def build_standard_audio_info_rows(
    df: pd.DataFrame, tts_cache: dict
) -> list[dict]:
    rows: list[dict] = []
    for video_id, group in df.groupby("video_id", sort=False):
        ordered = group.sort_values("question_timestamp", kind="stable").reset_index(
            drop=True
        )
        for idx, row in ordered.iterrows():
            text = str(row.question).strip()
            seg = synthesize_question_audio(text, tts_cache)
            rows.append(
                {
                    "audio_id": f"{video_id}_{idx}",
                    "question": text,
                    "duration": format_duration_value(len(seg)),
                }
            )
    return rows

# ---------------------------------------------------------------------------
# Standard dataset – duration map
# ---------------------------------------------------------------------------


def build_dataset_duration_map(df: pd.DataFrame) -> dict[str, int]:
    dmap: dict[str, int] = {}
    for row in df.itertuples(index=False):
        ms = hms_to_milliseconds(str(row.video_duration))
        prev = dmap.get(row.video_id)
        if prev is not None and prev != ms:
            raise RuntimeError(
                f"Inconsistent video_duration for {row.video_id}"
            )
        dmap[row.video_id] = ms
    return dmap

# ---------------------------------------------------------------------------
# Standard dataset – video discovery
# ---------------------------------------------------------------------------


def discover_standard_videos() -> dict[str, VideoEntry]:
    catalog: dict[str, VideoEntry] = {}
    for video_path in sorted(VIDEO_DIR.glob("*.mp4")):
        vid = video_path.stem
        if vid.startswith("mem_"):
            continue
        catalog[vid] = VideoEntry(
            video_id=vid,
            video_path=video_path,
            audio_output_path=AUDIO_DIR / f"{vid}.wav",
            video_output_path=VIDEO_DIR / f"{vid}.mp4",
        )
    return catalog

# ---------------------------------------------------------------------------
# Standard dataset – build final audio
# ---------------------------------------------------------------------------


def build_standard_final_audio(
    entry: VideoEntry,
    questions: list[QuestionItem],
    base_duration_ms: int,
    tts_cache: dict,
) -> tuple[AudioSegment, int, bool, int]:
    """Return (audio, final_duration_ms, used_background, question_count)."""
    include_bg = entry.video_id.split("_")[0] in BACKGROUND_AUDIO_PREFIXES
    final_dur = base_duration_ms
    count = 0

    if include_bg and has_audio_stream(entry.video_path):
        bg = AudioSegment.from_file(entry.video_path)
        bg = ensure_audio_length(bg, base_duration_ms)
        if questions:
            ref = synthesize_question_audio(questions[0].text, tts_cache)
            bg = scale_background_audio(bg, ref)
        audio = bg
    else:
        audio = AudioSegment.silent(duration=base_duration_ms)
        include_bg = False

    for q in questions:
        q_audio = synthesize_question_audio(q.text, tts_cache)
        dur = len(q_audio)
        final_dur = max(final_dur, q.timestamp_ms + dur)
        audio = ensure_audio_length(audio, q.timestamp_ms + dur)
        audio = audio.overlay(q_audio, position=q.timestamp_ms)
        count += 1

    audio = ensure_audio_length(audio, final_dur)
    return audio, final_dur, include_bg, count

# ---------------------------------------------------------------------------
# Standard dataset – render video (no tpad)
# ---------------------------------------------------------------------------


def render_standard_video(entry: VideoEntry):
    """Scale and strip audio.  No tail-padding."""
    entry.video_output_path.parent.mkdir(parents=True, exist_ok=True)
    src_w, src_h = probe_video_geometry(entry.video_path)
    tgt_w, tgt_h = compute_target_geometry(src_w, src_h)

    needs_scale = (src_w, src_h) != (tgt_w, tgt_h)
    needs_strip = has_audio_stream(entry.video_path)

    if not needs_scale and not needs_strip:
        return

    if needs_scale:
        run_command([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(entry.video_path),
            "-vf", f"scale={tgt_w}:{tgt_h}",
            "-an",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p",
            str(entry.video_output_path),
        ])
    else:
        tmp = entry.video_output_path.with_suffix(".tmp.mp4")
        run_command([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(entry.video_path),
            "-map", "0:v:0", "-c:v", "copy", "-an",
            str(tmp),
        ])
        tmp.replace(entry.video_output_path)

# ---------------------------------------------------------------------------
# Standard dataset – main processing loop
# ---------------------------------------------------------------------------


def process_standard_videos(
    video_ids: list[str],
    catalog: dict[str, VideoEntry],
    question_map: dict[str, list[QuestionItem]],
    dataset_dur_map: dict[str, int],
    outputs_mode: str,
):
    tts_cache: dict = {}
    summary = {
        "videos_processed": 0,
        "audio_files_written": 0,
        "videos_rendered": 0,
        "background_audio_videos": 0,
        "question_count": 0,
    }

    for i, vid in enumerate(video_ids, 1):
        entry = catalog[vid]
        questions = question_map[vid]
        source_dur = probe_video_duration_ms(entry.video_path)
        dataset_dur = dataset_dur_map[vid]
        base_dur = max(source_dur, dataset_dur)

        print(f"[{i}/{len(video_ids)}] Processing {vid}")

        if outputs_mode in ("all", "audio"):
            audio, _, used_bg, qcount = build_standard_final_audio(
                entry, questions, base_dur, tts_cache
            )
            export_audio_track(audio, entry.audio_output_path)
            summary["audio_files_written"] += 1
            summary["question_count"] += qcount
            if used_bg:
                summary["background_audio_videos"] += 1
            print(f"  Wrote audio: {entry.audio_output_path}")

        if outputs_mode in ("all", "video"):
            render_standard_video(entry)
            summary["videos_rendered"] += 1
            print(f"  Processed video: {entry.video_output_path}")

        summary["videos_processed"] += 1

    return summary, tts_cache

# ---------------------------------------------------------------------------
# Memory dataset – build rows & question map
# ---------------------------------------------------------------------------


def build_memory_dataset_rows():
    rows: list[dict] = []
    question_map: dict[str, list[ScheduledQuestion]] = {}
    raw_dur_map: dict[str, int] = {}
    valid_ids: list[str] = []

    for cfg in MEMORY_SOURCE_CONFIGS:
        src_dur = probe_video_duration_ms(cfg.video_path)
        if src_dur < cfg.anchor_ms:
            raise RuntimeError(
                f"Memory source shorter than anchor: {cfg.video_path}"
            )
        max_num = ((src_dur - cfg.anchor_ms) // 30_000) * 30

        for num in range(0, max_num + 1, 30):
            vid = f"{cfg.base_id}_{num}"
            raw_clip_ms = cfg.anchor_ms + (num * 1000)
            irrel_count = num // 30
            questions: list[ScheduledQuestion] = []

            for pi, text in enumerate(
                MEMORY_IRRELEVANT_QUESTIONS[:irrel_count]
            ):
                ts_ms = cfg.anchor_ms + (pi * 30_000)
                questions.append(
                    ScheduledQuestion(
                        timestamp_text=seconds_to_hms(ts_ms // 1000),
                        timestamp_ms=ts_ms,
                        text=text,
                    )
                )

            final_ts_ms = cfg.anchor_ms + (num * 1000)
            questions.append(
                ScheduledQuestion(
                    timestamp_text=seconds_to_hms(final_ts_ms // 1000),
                    timestamp_ms=final_ts_ms,
                    text=cfg.final_question,
                )
            )

            for qi, q in enumerate(questions, 1):
                rows.append(
                    {
                        "video_id": vid,
                        "video_duration": seconds_to_hms(raw_clip_ms // 1000),
                        "question_id": str(qi),
                        "question_timestamp": q.timestamp_text,
                        "task_type": "Memory",
                        "question": q.text,
                        "answer": "",
                    }
                )

            question_map[vid] = questions
            raw_dur_map[vid] = raw_clip_ms
            valid_ids.append(vid)

    return rows, question_map, raw_dur_map, valid_ids

# ---------------------------------------------------------------------------
# Memory dataset – clip catalog
# ---------------------------------------------------------------------------


def build_memory_clip_catalog(
    raw_dur_map: dict[str, int],
) -> dict[str, MemoryClipEntry]:
    catalog: dict[str, MemoryClipEntry] = {}
    for vid, raw_ms in raw_dur_map.items():
        base_id = "_".join(vid.split("_")[:2])
        cfg = MEMORY_SOURCE_MAP[base_id]
        catalog[vid] = MemoryClipEntry(
            video_id=vid,
            base_id=base_id,
            source_video_path=cfg.video_path,
            raw_clip_duration_ms=raw_ms,
            audio_output_path=AUDIO_MEM_DIR / f"{vid}.wav",
            video_output_path=VIDEO_MEM_DIR / f"{vid}.mp4",
        )
    return catalog

# ---------------------------------------------------------------------------
# Memory dataset – audio
# ---------------------------------------------------------------------------


def build_question_only_audio(
    questions: list[ScheduledQuestion],
    base_duration_ms: int,
    tts_cache: dict,
) -> tuple[AudioSegment, int]:
    audio = AudioSegment.silent(duration=base_duration_ms)
    final_dur = base_duration_ms
    for q in questions:
        q_audio = synthesize_question_audio(q.text, tts_cache)
        dur = len(q_audio)
        final_dur = max(final_dur, q.timestamp_ms + dur)
        audio = ensure_audio_length(audio, q.timestamp_ms + dur)
        audio = audio.overlay(q_audio, position=q.timestamp_ms)
    audio = ensure_audio_length(audio, final_dur)
    return audio, final_dur

# ---------------------------------------------------------------------------
# Memory dataset – render clip (no tpad)
# ---------------------------------------------------------------------------


def render_memory_video(clip: MemoryClipEntry):
    """Clip from source, scale, strip audio.  No tail-padding."""
    clip.video_output_path.parent.mkdir(parents=True, exist_ok=True)
    src_w, src_h = probe_video_geometry(clip.source_video_path)
    tgt_w, tgt_h = compute_target_geometry(src_w, src_h)

    needs_scale = (src_w, src_h) != (tgt_w, tgt_h)
    clip_sec = f"{clip.raw_clip_duration_ms / 1000:.3f}"

    if needs_scale:
        run_command([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-t", clip_sec,
            "-i", str(clip.source_video_path),
            "-vf", f"scale={tgt_w}:{tgt_h}",
            "-an",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p",
            str(clip.video_output_path),
        ])
    else:
        run_command([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-t", clip_sec,
            "-i", str(clip.source_video_path),
            "-map", "0:v:0", "-c:v", "copy", "-an",
            str(clip.video_output_path),
        ])

# ---------------------------------------------------------------------------
# Memory dataset – main processing loop
# ---------------------------------------------------------------------------


def process_memory_videos(
    video_ids: list[str],
    catalog: dict[str, MemoryClipEntry],
    question_map: dict[str, list[ScheduledQuestion]],
    outputs_mode: str,
):
    tts_cache: dict = {}
    summary = {
        "videos_processed": 0,
        "audio_files_written": 0,
        "videos_rendered": 0,
        "question_count": 0,
    }

    for i, vid in enumerate(video_ids, 1):
        clip = catalog[vid]
        questions = question_map[vid]

        print(f"[{i}/{len(video_ids)}] Processing {vid}")

        if outputs_mode in ("all", "audio"):
            audio, _ = build_question_only_audio(
                questions, clip.raw_clip_duration_ms, tts_cache
            )
            export_audio_track(audio, clip.audio_output_path)
            summary["audio_files_written"] += 1
            summary["question_count"] += len(questions)
            print(f"  Wrote audio: {clip.audio_output_path}")

        if outputs_mode in ("all", "video"):
            render_memory_video(clip)
            summary["videos_rendered"] += 1
            print(f"  Wrote video: {clip.video_output_path}")

        summary["videos_processed"] += 1

    return summary, tts_cache

# ---------------------------------------------------------------------------
# Memory dataset – cleanup
# ---------------------------------------------------------------------------


def cleanup_memory_derivatives(valid_ids: set[str]):
    """Remove stale memory clips from ``videos_mem/``."""
    removed: list[str] = []
    for p in sorted(VIDEO_MEM_DIR.glob("mem_*.mp4")):
        if p.stem.count("_") > 1 and p.stem not in valid_ids:
            p.unlink()
            removed.append(p.name)
    return removed

# ---------------------------------------------------------------------------
# audio_info.csv helpers
# ---------------------------------------------------------------------------


def build_memory_audio_info_rows(tts_cache: dict) -> list[dict]:
    rows: list[dict] = []
    for cfg in MEMORY_SOURCE_CONFIGS:
        seg = synthesize_question_audio(cfg.final_question, tts_cache)
        rows.append(
            {
                "audio_id": f"{cfg.base_id}_final",
                "question": cfg.final_question,
                "duration": format_duration_value(len(seg)),
            }
        )
    return rows


def write_audio_info(df: pd.DataFrame, tts_cache: dict):
    std_rows = build_standard_audio_info_rows(df, tts_cache)
    mem_rows = build_memory_audio_info_rows(tts_cache)
    write_csv_rows(AUDIO_INFO_CSV, EXPECTED_AUDIO_INFO_COLUMNS, std_rows + mem_rows)
    return len(std_rows), len(mem_rows)

# ---------------------------------------------------------------------------
# Pipeline – standard
# ---------------------------------------------------------------------------


def run_standard_pipeline(args):
    df = read_standard_dataset()
    qmap = build_standard_question_map(df)
    dur_map = build_dataset_duration_map(df)
    catalog = discover_standard_videos()

    dataset_vids = set(qmap)
    catalog_vids = set(catalog)
    missing = sorted(dataset_vids - catalog_vids)
    if missing:
        raise RuntimeError(
            f"Videos in dataset.csv but missing from videos/: {', '.join(missing)}"
        )

    if args.video_ids:
        unknown = sorted(set(args.video_ids) - dataset_vids)
        if unknown:
            raise RuntimeError(f"Unknown video IDs: {', '.join(unknown)}")
        video_ids = sorted(set(args.video_ids))
    else:
        video_ids = sorted(dataset_vids)

    summary, tts_cache = process_standard_videos(
        video_ids, catalog, qmap, dur_map, args.outputs
    )

    if args.outputs in ("all", "audio"):
        std_count, mem_count = write_audio_info(df, tts_cache)
    else:
        std_count = mem_count = None

    print("\nStandard pipeline complete.")
    print(f"  Outputs mode: {args.outputs}")
    print(f"  Videos processed: {summary['videos_processed']}")
    print(f"  Audio files written: {summary['audio_files_written']}")
    print(f"  Videos rendered: {summary['videos_rendered']}")
    print(f"  Background-audio mixes: {summary['background_audio_videos']}")
    print(f"  Questions synthesized: {summary['question_count']}")
    if std_count is not None:
        print(f"  audio_info standard rows: {std_count}")
        print(f"  audio_info memory rows: {mem_count}")

# ---------------------------------------------------------------------------
# Pipeline – memory
# ---------------------------------------------------------------------------


def run_memory_pipeline(args):
    for cfg in MEMORY_SOURCE_CONFIGS:
        if not cfg.video_path.exists():
            raise RuntimeError(f"Missing memory source: {cfg.video_path}")

    mem_rows, qmap, raw_dur_map, valid_ids = build_memory_dataset_rows()

    if args.outputs in ("all", "audio"):
        write_csv_rows(MEMORY_DATASET_CSV, EXPECTED_DATASET_COLUMNS, mem_rows)

    valid_set = set(valid_ids)
    removed = cleanup_memory_derivatives(valid_set)
    if removed:
        print(f"Removed stale memory clips: {', '.join(removed)}")

    if args.video_ids:
        unknown = sorted(set(args.video_ids) - valid_set)
        if unknown:
            raise RuntimeError(f"Unknown memory video IDs: {', '.join(unknown)}")
        video_ids = sorted(set(args.video_ids))
    else:
        video_ids = valid_ids

    catalog = build_memory_clip_catalog(raw_dur_map)
    summary, tts_cache = process_memory_videos(
        video_ids, catalog, qmap, args.outputs
    )

    if args.outputs in ("all", "audio"):
        std_df = read_standard_dataset()
        std_count, mem_count = write_audio_info(std_df, tts_cache)
    else:
        std_count = mem_count = None

    print("\nMemory pipeline complete.")
    print(f"  Outputs mode: {args.outputs}")
    print(f"  Videos processed: {summary['videos_processed']}")
    print(f"  Audio files written: {summary['audio_files_written']}")
    print(f"  Videos rendered: {summary['videos_rendered']}")
    print(f"  Questions synthesized: {summary['question_count']}")
    print(f"  Memory dataset rows: {len(mem_rows)}")
    print(f"  Memory clip IDs: {len(valid_ids)}")
    if std_count is not None:
        print(f"  audio_info standard rows: {std_count}")
        print(f"  audio_info memory rows: {mem_count}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    args = parse_args()
    ensure_dependencies()

    if args.dataset in ("standard", "all"):
        run_standard_pipeline(args)
    if args.dataset in ("memory", "all"):
        run_memory_pipeline(args)


if __name__ == "__main__":
    main()
