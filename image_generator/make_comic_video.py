import json
import math
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


# ============================================================
# FFmpeg Motion Comic Renderer
# ============================================================
#
# Replaces MoviePy.
#
# Input:
#   output_edge/chapter_with_real_durations.json
#   outputs/CLOUDS_END_CLIFF_01/*.png
#   output_edge/panel_audio/*.mp3
#   output_edge/voice_segments/*.mp3   (optional, for exact subtitles)
#
# Output:
#   FINAL_COMIC_CHAPTER_01.mp4
#   FINAL_COMIC_CHAPTER_01.srt
#
# The story/dialogue text is NOT changed.
#
# ============================================================


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

CHAPTER_JSON = (
    BASE_DIR
    / "output_edge"
    / "chapter_with_real_durations.json"
)

IMAGE_ROOT = BASE_DIR / "outputs"
IMAGE_DIR = next(
    (folder for folder in sorted(IMAGE_ROOT.iterdir())
     if folder.is_dir() and (folder / "001_PANEL_001.png").exists()),
    IMAGE_ROOT,
) if IMAGE_ROOT.exists() else IMAGE_ROOT


AUDIO_DIR = (
    BASE_DIR
    / "output_edge"
    / "panel_audio"
)

VOICE_SEGMENT_DIR = (
    BASE_DIR
    / "output_edge"
    / "voice_segments"
)

OUTPUT_VIDEO = (
    BASE_DIR
    / "FINAL_COMIC_CHAPTER_01.mp4"
)

OUTPUT_SRT = (
    BASE_DIR
    / "FINAL_COMIC_CHAPTER_01.srt"
)

WORK_DIR = (
    BASE_DIR
    / "_ffmpeg_work"
)

# FFmpeg executable.
# If ffmpeg is already in PATH, leave this as "ffmpeg".
FFMPEG = "ffmpeg"

# ffprobe executable.
FFPROBE = "ffprobe"


# ============================================================
# VIDEO SETTINGS
# ============================================================

WIDTH = 1280
HEIGHT = 720
FPS = 30
# ============================================================
# COMIC STYLE SETTINGS
# ============================================================

COMIC_PAGE_COLOR = "0xF3EBD8"
COMIC_MARGIN = 18
COMIC_BORDER = 6

PANEL_W = WIDTH - 2 * (COMIC_MARGIN + COMIC_BORDER)
PANEL_H = HEIGHT - 2 * (COMIC_MARGIN + COMIC_BORDER)

SUBTITLE_FONT = "Noto Sans Devanagari"


PAN_DISTANCE = 140
IMAGE_SCALE = 1.12
FLOAT_DISTANCE = 12

TWO_WAY_MIN_SECONDS = 12.0

# Encoding.
#
# "veryfast" is a good balance for this laptop.
# "ultrafast" = faster, larger file.
# "fast" = slower, better compression.
X264_PRESET = "veryfast"

VIDEO_BITRATE = "8M"
AUDIO_BITRATE = "192k"

# Number of panel FFmpeg jobs running simultaneously.
#
# With 8 GB RAM:
#   1 = safest
#   2 = good starting point
#   3 = more CPU usage / RAM
PANEL_WORKERS = 2

# Burn subtitles directly into video.
#
# True:
#   subtitles are permanently visible in MP4.
#
# False:
#   MP4 gets a normal subtitle stream and an SRT file is also created.
#
# Burning subtitles means FFmpeg must encode each panel with libass.
BURN_SUBTITLES = True

# Subtitle appearance.
SUBTITLE_FONT = "Noto Sans Devanagari"
SUBTITLE_FONT_SIZE = 31

# Put subtitles near the bottom.
SUBTITLE_MARGIN_V = 48

# Temporary panel files are deleted after final concat.
KEEP_TEMP_FILES = False


# ============================================================
# HELPERS
# ============================================================

def run_command(cmd, label=None):
    """Run a command and show useful errors."""

    if label:
        print(f"\n[{label}]")

    print(" ".join(str(x) for x in cmd))

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        print()
        print(result.stderr)
        raise RuntimeError(
            f"FFmpeg command failed with exit code "
            f"{result.returncode}"
        )

    return result


def ffprobe_duration(path):
    """Get media duration in seconds."""

    cmd = [
        FFPROBE,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed for:\n{path}\n\n"
            f"{result.stderr}"
        )

    value = result.stdout.strip()

    if not value:
        raise RuntimeError(
            f"Could not read duration:\n{path}"
        )

    return float(value)


def clean_text(value):
    """
    Keep the actual story/dialogue text.
    Only remove markdown bold markers because they are
    formatting, not spoken words.
    """

    if value is None:
        return ""

    text = str(value)

    text = text.replace("**", "")

    return text.strip()


def format_srt_time(seconds):
    """Convert seconds to SRT timestamp."""

    seconds = max(0.0, float(seconds))

    total_ms = int(round(seconds * 1000))

    hours = total_ms // 3_600_000
    total_ms %= 3_600_000

    minutes = total_ms // 60_000
    total_ms %= 60_000

    secs = total_ms // 1000
    ms = total_ms % 1000

    return (
        f"{hours:02d}:"
        f"{minutes:02d}:"
        f"{secs:02d},"
        f"{ms:03d}"
    )


def format_ass_time(seconds):
    """Convert seconds to ASS timestamp."""

    seconds = max(0.0, float(seconds))

    total_cs = int(round(seconds * 100))

    hours = total_cs // 360000
    total_cs %= 360000

    minutes = total_cs // 6000
    total_cs %= 6000

    secs = total_cs // 100

    cs = total_cs % 100

    return (
        f"{hours}:"
        f"{minutes:02d}:"
        f"{secs:02d}."
        f"{cs:02d}"
    )


def ass_escape(text):
    """Escape text for ASS subtitles."""

    text = clean_text(text)

    text = text.replace("\\", r"\\")

    text = text.replace("{", r"\{")
    text = text.replace("}", r"\}")

    text = text.replace("\n", r"\N")

    return text


# ============================================================
# IMAGE FINDER
# ============================================================

def find_image(index, panel_id):
    """Find panel image."""

    exact = (
        IMAGE_DIR
        / f"{index:03d}_{panel_id}.png"
    )

    if exact.exists():
        return exact

    matches = sorted(
        IMAGE_DIR.glob(
            f"{index:03d}_*.png"
        )
    )

    if matches:
        return matches[0]

    raise FileNotFoundError(
        "Image not found.\n"
        f"Expected:\n{exact}\n\n"
        f"Directory:\n{IMAGE_DIR}"
    )


# ============================================================
# LOAD JSON
# ============================================================

def load_data():
    """Load the actual top-level JSON structure."""

    if not CHAPTER_JSON.exists():
        raise FileNotFoundError(
            f"Chapter JSON not found:\n{CHAPTER_JSON}"
        )

    with CHAPTER_JSON.open(
        "r",
        encoding="utf-8",
    ) as f:
        data = json.load(f)

    if "scenes" not in data:
        raise KeyError(
            "JSON does not contain top-level 'scenes'.\n"
            "Expected structure:\n"
            "{\n"
            '  "project": "...",\n'
            '  "scenes": [...]\n'
            "}"
        )

    panels = []

    for scene in data["scenes"]:

        scene_id = scene.get(
            "scene_id",
            scene.get("id", ""),
        )

        for panel in scene.get("panels", []):

            item = dict(panel)

            item["_scene_id"] = scene_id

            panels.append(item)

    if not panels:
        raise RuntimeError(
            "No panels found in JSON."
        )

    return data, panels


# ============================================================
# PANEL AUDIO
# ============================================================

def get_panel_audio(panel_id):
    path = (
        AUDIO_DIR
        / f"{panel_id}.mp3"
    )

    if not path.exists():
        raise FileNotFoundError(
            f"Panel audio not found:\n{path}"
        )

    return path


# ============================================================
# VOICE SEGMENTS
# ============================================================

def find_voice_segment(panel_id, voice_index):
    """
    Expected:
        PANEL_001_00.mp3
        PANEL_001_01.mp3
        ...

    Returns None when no segment exists.
    """

    exact = (
        VOICE_SEGMENT_DIR
        / f"{panel_id}_{voice_index:02d}.mp3"
    )

    if exact.exists():
        return exact

    # Fallback for slightly different numbering.
    candidates = [
        VOICE_SEGMENT_DIR
        / f"{panel_id}_{voice_index}.mp3",

        VOICE_SEGMENT_DIR
        / f"{panel_id}_{voice_index + 1:02d}.mp3",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return None


def get_panel_voice_items(panel):
    """
    Read voice[] entries from JSON.

    Each entry normally contains:
        speaker
        text

    We do not rewrite the text.
    """

    voice = panel.get("voice", [])

    if isinstance(voice, dict):
        voice = [voice]

    if not isinstance(voice, list):
        return []

    result = []

    for i, item in enumerate(voice):

        if not isinstance(item, dict):
            continue

        text = clean_text(
            item.get("text", "")
        )

        if not text:
            continue

        result.append(
            {
                "index": i,
                "speaker": str(
                    item.get(
                        "speaker",
                        "NARRATOR",
                    )
                ),
                "text": text,
            }
        )

    return result


# ============================================================
# PANEL SUBTITLE TIMINGS
# ============================================================

def build_panel_subtitle_entries(panel):
    """Create natural subtitle timings from the actual voice segments.

    Voice-segment duration remains the source of truth.  A tiny gap is
    inserted only for readability and all timings are clamped to the
    panel audio duration so a subtitle can never hang over into the next
    panel.
    """
    panel_id = panel["panel_id"]
    voice_items = get_panel_voice_items(panel)
    if not voice_items:
        return []

    panel_duration = ffprobe_duration(get_panel_audio(panel_id))
    gap = 0.08
    durations = []
    exact = True

    for item in voice_items:
        segment = find_voice_segment(panel_id, item["index"])
        if segment is None:
            exact = False
            break
        durations.append(max(0.001, ffprobe_duration(segment)))

    if exact and durations:
        raw_total = sum(durations) + gap * max(0, len(durations) - 1)
        # If tiny gaps make the sequence longer than the panel, scale only
        # the gaps down; never distort the real speech durations.
        effective_gap = gap
        if raw_total > panel_duration and len(durations) > 1:
            available_gap = max(0.0, panel_duration - sum(durations))
            effective_gap = available_gap / (len(durations) - 1)

        entries = []
        current = 0.0
        for item, duration in zip(voice_items, durations):
            start = current
            end = min(panel_duration, start + duration)
            if end > start + 0.02:
                entries.append({
                    "speaker": item["speaker"],
                    "text": item["text"],
                    "start": start,
                    "end": end,
                })
            current = end + effective_gap
        return entries

    # Fallback: proportional timing by text length.
    usable = max(0.1, panel_duration - gap * max(0, len(voice_items) - 1))
    weights = [max(1, len(item["text"])) for item in voice_items]
    total_weight = sum(weights)
    entries = []
    current = 0.0
    for i, item in enumerate(voice_items):
        duration = usable * weights[i] / total_weight
        start = current
        end = min(panel_duration, start + duration)
        if end > start + 0.02:
            entries.append({
                "speaker": item["speaker"],
                "text": item["text"],
                "start": start,
                "end": end,
            })
        current = end + gap
    return entries


def build_global_srt(panels):
    """
    Create one complete SRT for the entire chapter.
    """

    all_entries = []

    chapter_time = 0.0

    for index, panel in enumerate(
        panels,
        start=1,
    ):

        panel_entries = (
            build_panel_subtitle_entries(
                panel
            )
        )

        for entry in panel_entries:

            all_entries.append(
                {
                    "speaker": entry["speaker"],
                    "text": entry["text"],
                    "start": (
                        chapter_time
                        + entry["start"]
                    ),
                    "end": (
                        chapter_time
                        + entry["end"]
                    ),
                    "panel": index,
                }
            )

        panel_audio = get_panel_audio(
            panel["panel_id"]
        )

        chapter_time += ffprobe_duration(
            panel_audio
        )

    with OUTPUT_SRT.open(
        "w",
        encoding="utf-8-sig",
        newline="\n",
    ) as f:

        for number, entry in enumerate(
            all_entries,
            start=1,
        ):

            f.write(
                f"{number}\n"
            )

            f.write(
                f"{format_srt_time(entry['start'])}"
                " --> "
                f"{format_srt_time(entry['end'])}\n"
            )

            # Speaker name is shown in subtitles.
            # Remove this prefix if you want dialogue only.
            f.write(
                f"{entry['speaker']}: "
                f"{entry['text']}\n\n"
            )

    print(
        f"\nSRT created:\n{OUTPUT_SRT}"
    )


# ============================================================
# ASS FOR EACH PANEL
# ============================================================

def smart_wrap_hindi(text, max_chars=34):
    """Wrap Hindi text without changing wording."""
    text = clean_text(text)
    if len(text) <= max_chars:
        return text

    lines = []
    current = ""

    for word in text.split():
        candidate = word if not current else current + " " + word
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    return r"\N".join(lines)

_NARRATOR_NAMES = {"NARRATOR", "NARRATION", "सूत्रधार", "कथावाचक"}


def write_panel_ass(panel, ass_path):
    """Comic caption boxes for narration and dialogue."""
    entries = build_panel_subtitle_entries(panel)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {WIDTH}
PlayResY: {HEIGHT}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{SUBTITLE_FONT},30,&H00101010,&H00101010,&H00FFFFFF,&H00000000,1,0,0,0,100,100,0,0,3,6,0,2,110,110,{COMIC_MARGIN + COMIC_BORDER + 22},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    out = [header]

    for entry in entries:
        speaker_raw = clean_text(entry["speaker"])
        speaker = ass_escape(speaker_raw)
        text = ass_escape(smart_wrap_hindi(entry["text"], 34))
        is_narr = speaker_raw.strip().upper() in _NARRATOR_NAMES

        if is_narr:
            box = "&H0080E6FF&"
            pos = (
                r"\an7\pos("
                + str(COMIC_MARGIN + COMIC_BORDER + 26)
                + ","
                + str(COMIC_MARGIN + COMIC_BORDER + 22)
                + ")"
            )
            body = text
        else:
            box = "&H00FFFFFF&"
            pos = r"\an2"
            body = (
                r"{\fs21\c&H00007A&}" + speaker + r"\N"
                r"{\fs30\c&H101010&}" + text
            )

        anim = r"\fad(120,90)\fscx92\fscy92\t(0,140,\fscx100\fscy100)"
        start = format_ass_time(entry["start"])
        end = format_ass_time(entry["end"])

        for layer, bord, colour in (
            (0, 11, "&H00000000&"),
            (1, 6, box),
        ):
            out.append(
                f"Dialogue: {layer},{start},{end},Default,,0,0,0,,"
                "{"
                + pos + anim + r"\bord" + str(bord) + r"\3c" + colour
                + "}" + body + "\n"
            )

    ass_path.write_text("".join(out), encoding="utf-8")

def get_movement(index, duration):
    """Halka, smooth camera move (jhatka nahi)."""
    moves = (
        "PUSH_IN", "PUSH_IN_LEFT", "PULL_OUT", "PUSH_IN_RIGHT",
        "L-R", "PUSH_IN", "R-L", "PULL_OUT",
    )
    return moves[(index - 1) % len(moves)]


def should_float(index, panel):
    return False


_MOVES = {
    "PUSH_IN":       (1.00, 1.08, 0.50, 0.50, 0.50, 0.50),
    "PUSH_IN_LEFT":  (1.00, 1.08, 0.62, 0.38, 0.50, 0.45),
    "PUSH_IN_RIGHT": (1.00, 1.08, 0.38, 0.62, 0.50, 0.45),
    "PULL_OUT":      (1.08, 1.00, 0.50, 0.50, 0.45, 0.50),
    "L-R":           (1.08, 1.08, 0.25, 0.75, 0.50, 0.50),
    "R-L":           (1.08, 1.08, 0.75, 0.25, 0.50, 0.50),
}

def make_video_filter(duration, movement, floating=False, subtitle_path=None):
    """Create comic-style motion, border, paper background and subtitles."""
    duration = max(0.1, float(duration))
    frames = max(2, int(round(duration * FPS)))

    z0, z1, x0, x1, y0, y1 = _MOVES.get(
        movement, _MOVES["PUSH_IN"]
    )

    up_w = 3200
    up_h = int(round(up_w * PANEL_H / PANEL_W))
    up_h += up_h % 2

    e = f"(1-cos(PI*on/{frames}))/2"

    filters = [
        f"scale={up_w}:{up_h}:force_original_aspect_ratio=increase:flags=lanczos",
        f"crop={up_w}:{up_h}",
        (
            f"zoompan=z='{z0}+({z1}-{z0})*{e}'"
            f":x='(iw-iw/zoom)*({x0}+({x1}-{x0})*{e})'"
            f":y='(ih-ih/zoom)*({y0}+({y1}-{y0})*{e})'"
            f":d=1:s={PANEL_W}x{PANEL_H}:fps={FPS}"
        ),
        "eq=contrast=1.10:saturation=1.15:gamma=0.97",
        "unsharp=5:5:0.7:5:5:0.0",
        "noise=alls=5:allf=u",
        f"pad={PANEL_W + 2 * COMIC_BORDER}:{PANEL_H + 2 * COMIC_BORDER}:{COMIC_BORDER}:{COMIC_BORDER}:color=black",
        f"pad={WIDTH}:{HEIGHT}:{COMIC_MARGIN}:{COMIC_MARGIN}:color={COMIC_PAGE_COLOR}",
        "format=yuv420p",
    ]

    if subtitle_path is not None:
        escaped = str(subtitle_path.resolve())
        escaped = (
            escaped.replace("\\", "/")
            .replace(":", r"\:")
            .replace("'", r"\'")
        )
        filters.append(f"subtitles='{escaped}'")

    return ",".join(filters)

def render_panel(
    index,
    panel,
):
    panel_id = panel["panel_id"]

    image_path = find_image(
        index,
        panel_id,
    )

    audio_path = get_panel_audio(
        panel_id
    )

    duration = ffprobe_duration(
        audio_path
    )

    movement = get_movement(
        index,
        duration,
    )

    floating = should_float(
        index,
        panel,
    )

    panel_dir = (
        WORK_DIR
        / f"{index:03d}_{panel_id}"
    )

    panel_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    ass_path = (
        panel_dir
        / f"{panel_id}.ass"
    )

    output_path = (
        panel_dir
        / f"{index:03d}_{panel_id}.mp4"
    )

    # Create subtitle file if burn-in is enabled.
    if BURN_SUBTITLES:

        write_panel_ass(
            panel,
            ass_path,
        )

        subtitle_path = ass_path

    else:

        subtitle_path = None

    video_filter = make_video_filter(
        duration=duration,
        movement=movement,
        floating=floating,
        subtitle_path=subtitle_path,
    )

    # --------------------------------------------------------
    # FFmpeg
    # --------------------------------------------------------

    cmd = [
        FFMPEG,

        "-y",

        # Loop image for the exact audio duration.
        "-loop",
        "1",
        "-framerate",
        str(FPS),

        "-i",
        str(image_path),

        # Audio.
        "-i",
        str(audio_path),

        "-t",
        f"{duration:.6f}",

        "-vf",
        video_filter,

        "-map",
        "0:v:0",

        "-map",
        "1:a:0",

        "-c:v",
        "libx264",

        "-preset",
        X264_PRESET,

        "-crf",
        "20",

        "-pix_fmt",
        "yuv420p",

        "-r",
        str(FPS),

        "-c:a",
        "aac",

        "-b:a",
        AUDIO_BITRATE,

        "-ar",
        "48000",

        "-ac",
        "2",

        "-shortest",

        # Important for stream-copy concat later.
        "-movflags",
        "+faststart",

        str(output_path),
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:

        print(
            f"\nFAILED PANEL {index}: "
            f"{panel_id}\n"
        )

        print(result.stderr)

        raise RuntimeError(
            f"Panel render failed: "
            f"{panel_id}"
        )

    print(
        f"OK  {index:03d} | "
        f"{panel_id} | "
        f"{duration:.2f}s | "
        f"{movement}"
        + (
            " | FLOAT"
            if floating
            else ""
        )
    )

    return output_path


# ============================================================
# CONCAT FILE
# ============================================================

def create_concat_file(
    rendered_files,
):
    concat_file = (
        WORK_DIR
        / "concat.txt"
    )

    with concat_file.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as f:

        for path in rendered_files:

            # FFmpeg concat demuxer syntax.
            #
            # Use forward slashes on Windows.
            safe_path = (
                path.resolve()
                .as_posix()
                .replace("'", "'\\''")
            )

            f.write(
                f"file '{safe_path}'\n"
            )

    return concat_file


# ============================================================
# CONCAT FINAL VIDEO
# ============================================================

def concat_final_video(
    concat_file,
):
    """
    Final join is stream-copy.

    No second H264 encode.
    This is the important speed advantage.
    """

    cmd = [
        FFMPEG,

        "-y",

        "-f",
        "concat",

        "-safe",
        "0",

        "-i",
        str(concat_file),

        "-c",
        "copy",

        "-movflags",
        "+faststart",

        str(OUTPUT_VIDEO),
    ]

    run_command(
        cmd,
        "FINAL CONCAT",
    )


# ============================================================
# CLEANUP
# ============================================================

def cleanup():
    if KEEP_TEMP_FILES:
        return

    if WORK_DIR.exists():

        shutil.rmtree(
            WORK_DIR,
            ignore_errors=True,
        )


# ============================================================
# CHECK TOOLS
# ============================================================

def check_tools():
    print("\nChecking FFmpeg...")

    for executable in (
        FFMPEG,
        FFPROBE,
    ):

        path = shutil.which(
            executable
        )

        if path is None:

            raise RuntimeError(
                f"'{executable}' was not found "
                "in PATH.\n\n"
                "Test with:\n"
                "ffmpeg -version"
            )

        print(
            f"{executable}: {path}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 75)
    print("FFMPEG MOTION COMIC RENDERER")
    print("=" * 75)

    print()
    print("MoviePy: DISABLED")
    print("Renderer: FFmpeg")
    print(
        f"Resolution: {WIDTH}x{HEIGHT}"
    )
    print(
        f"FPS: {FPS}"
    )
    print(
        f"Preset: {X264_PRESET}"
    )
    print(
        f"Panel workers: {PANEL_WORKERS}"
    )
    print(
        f"Burn subtitles: {BURN_SUBTITLES}"
    )

    print("=" * 75)

    check_tools()

    # --------------------------------------------------------
    # Load chapter
    # --------------------------------------------------------

    data, panels = load_data()

    print()
    print(
        f"Project: "
        f"{data.get('project', 'Unknown')}"
    )

    print(
        f"Chapter: "
        f"{data.get('chapter', 'Unknown')}"
    )

    print(
        f"Panels found: "
        f"{len(panels)}"
    )

    # --------------------------------------------------------
    # Work directory
    # --------------------------------------------------------

    WORK_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Validate all input files first.
    # --------------------------------------------------------

    print()
    print("=" * 75)
    print("CHECKING INPUT FILES")
    print("=" * 75)

    for index, panel in enumerate(
        panels,
        start=1,
    ):

        panel_id = panel["panel_id"]

        image = find_image(
            index,
            panel_id,
        )

        audio = get_panel_audio(
            panel_id
        )

        print(
            f"{index:03d} | "
            f"{panel_id} | "
            f"image OK | "
            f"audio OK"
        )

    # --------------------------------------------------------
    # Build SRT first.
    # --------------------------------------------------------

    print()
    print("=" * 75)
    print("BUILDING SUBTITLE FILE")
    print("=" * 75)

    build_global_srt(
        panels
    )

    # --------------------------------------------------------
    # Render panels.
    # --------------------------------------------------------

    print()
    print("=" * 75)
    print("RENDERING PANELS WITH FFMPEG")
    print("=" * 75)
    print()

    rendered = {}

    # If only one worker, normal loop.
    if PANEL_WORKERS <= 1:

        for index, panel in enumerate(
            panels,
            start=1,
        ):

            output = render_panel(
                index,
                panel,
            )

            rendered[index] = output

    else:

        with ThreadPoolExecutor(
            max_workers=PANEL_WORKERS
        ) as executor:

            future_map = {
                executor.submit(
                    render_panel,
                    index,
                    panel,
                ): index
                for index, panel in enumerate(
                    panels,
                    start=1,
                )
            }

            for future in as_completed(
                future_map
            ):

                index = future_map[
                    future
                ]

                output = future.result()

                rendered[index] = output

    # --------------------------------------------------------
    # Restore exact panel order.
    # --------------------------------------------------------

    rendered_files = [
        rendered[index]
        for index in range(
            1,
            len(panels) + 1,
        )
    ]

    # --------------------------------------------------------
    # Concat.
    # --------------------------------------------------------

    concat_file = create_concat_file(
        rendered_files
    )

    print()
    print("=" * 75)
    print("JOINING FINAL VIDEO")
    print("=" * 75)

    concat_final_video(
        concat_file
    )

    # --------------------------------------------------------
    # Cleanup.
    # --------------------------------------------------------

    cleanup()

    print()
    print("=" * 75)
    print("VIDEO COMPLETE")
    print("=" * 75)

    print()
    print(
        f"Video:\n{OUTPUT_VIDEO}"
    )

    print()
    print(
        f"Subtitles:\n{OUTPUT_SRT}"
    )

    print()
    print(
        "Subtitles are generated from the JSON voice[] "
        "text and voice-segment timings."
    )

    print(
        "Story/dialogue wording was not rewritten."
    )

    print("=" * 75)


# ============================================================
# RUN
# ============================================================

# ============================================================
# 5-SECOND CAMERA TEST
# ============================================================
def run_camera_test():
    """Render one panel for motion testing before the full 139-panel render."""
    import subprocess
    import tempfile

    image = find_image(1, "PANEL_001")
    if image is None:
        raise FileNotFoundError("PANEL_001 image नहीं मिली।")

    out = BASE_DIR / "CAMERA_TEST_5SEC.mp4"

    vf = make_video_filter(
        duration=8.0,
        movement="L-R",
        floating=False,
        subtitle_path=None,
    )

    cmd = [
        FFMPEG,
        "-y",
        "-loop", "1",
        "-i", str(image),
        "-t", "5",
        "-vf", vf,
        "-an",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out),
    ]

    print("\n=== CAMERA TEST ===")
    print("Image:", image)
    print("Output:", out)
    print("Testing 5 seconds of slow cinematic L-R drift...\n")

    subprocess.run(cmd, check=True)

    print("\nTEST COMPLETE:")
    print(out)



if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "\n\nStopped by user."
        )

        sys.exit(130)

    except Exception as e:

        print()
        print("=" * 75)
        print("ERROR")
        print("=" * 75)
        print()
        print(str(e))
        print()

        sys.exit(1)
 