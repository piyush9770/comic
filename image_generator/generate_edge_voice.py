import asyncio
import json
import re
from pathlib import Path

import edge_tts
from pydub import AudioSegment


# =========================================================
# CONFIG
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

INPUT_JSON = BASE_DIR / "chapter.json"

OUTPUT_DIR = BASE_DIR / "output_edge"
AUDIO_DIR = OUTPUT_DIR / "panel_audio"
SEGMENT_DIR = OUTPUT_DIR / "voice_segments"

UPDATED_JSON = OUTPUT_DIR / "chapter_with_real_durations.json"
DURATION_JSON = OUTPUT_DIR / "panel_durations.json"


# =========================================================
# EDGE TTS VOICE PROFILES
# =========================================================
#
# The JSON already tells us WHO is speaking through:
#     voice[].speaker
#
# The JSON does not contain Edge-TTS voice names, so the
# mapping is kept here without changing the story JSON.
#
# Hindi Edge voices:
#   hi-IN-MadhurNeural -> male
#   hi-IN-SwaraNeural  -> female
#
# Rudransh uses the same Hindi male voice with a small pitch/rate
# change so he does not sound exactly like the narrator.
# =========================================================

VOICE_PROFILES = {
    "NARRATOR": {
        "voice": "hi-IN-MadhurNeural",
        "rate": "+0%",
        "pitch": "+0Hz",
        "volume": "+0%",
    },

    "HOOK": {
        "voice": "hi-IN-MadhurNeural",
        "rate": "-3%",
        "pitch": "-2Hz",
        "volume": "+0%",
    },

    "रुद्रांश": {
        "voice": "hi-IN-MadhurNeural",
        "rate": "-5%",
        "pitch": "-5Hz",
        "volume": "+0%",
    },

    "छोटी बुआ": {
        "voice": "hi-IN-SwaraNeural",
        "rate": "+0%",
        "pitch": "+0Hz",
        "volume": "+0%",
    },
}


# Fallback if a new speaker is added to the JSON later.
DEFAULT_PROFILE = {
    "voice": "hi-IN-MadhurNeural",
    "rate": "+0%",
    "pitch": "+0Hz",
    "volume": "+0%",
}


# Small pause between separate voice entries inside one panel.
VOICE_GAP_MS = 180

# Maximum simultaneous Edge-TTS requests.
# 4-6 is a good starting point. Increase carefully if needed.
TTS_CONCURRENCY = 5

# Reuse already generated segment files on rerun.
USE_CACHE = True

# Save a new JSON with real audio durations.
# Existing duration values are replaced by measured durations.
ROUND_DURATION = 3


# =========================================================
# HELPERS
# =========================================================

def safe_name(value: str) -> str:
    return "".join(
        c if c.isalnum() or c in "_-" else "_"
        for c in value
    )


def ms_to_seconds(ms: int) -> float:
    return round(ms / 1000.0, ROUND_DURATION)


def clean_tts_text(text: str) -> str:
    """
    Remove Markdown formatting used only for visual emphasis.
    Story wording itself is not rewritten.
    """
    text = str(text).strip()

    # Remove bold markers: **text** -> text
    text = text.replace("**", "")

    # Normalize a few typographic quote characters.
    text = text.replace("“", '"')
    text = text.replace("”", '"')
    text = text.replace("‘", "'")
    text = text.replace("’", "'")

    # Avoid excessive blank lines.
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def get_profile(speaker: str) -> dict:
    return VOICE_PROFILES.get(
        speaker,
        DEFAULT_PROFILE
    )


def segment_is_valid(path: Path) -> bool:
    """
    Basic cache validation.
    Edge TTS should create a non-empty MP3.
    """
    if not path.exists():
        return False

    try:
        if path.stat().st_size < 1000:
            return False

        audio = AudioSegment.from_file(path)

        return len(audio) > 0

    except Exception:
        return False


async def synthesize(
    text: str,
    profile: dict,
    out_file: Path,
):
    communicate = edge_tts.Communicate(
        text=text,
        voice=profile["voice"],
        rate=profile["rate"],
        pitch=profile["pitch"],
        volume=profile["volume"],
    )

    await communicate.save(str(out_file))


# =========================================================
# LOAD JSON
# =========================================================

def load_chapter():
    if not INPUT_JSON.exists():
        raise FileNotFoundError(
            f"\nJSON not found:\n{INPUT_JSON}\n\n"
            f"Put chapter.json in the same folder as this script."
        )

    with INPUT_JSON.open(
        "r",
        encoding="utf-8",
    ) as f:
        data = json.load(f)

    # IMPORTANT:
    # This JSON has:
    #
    # {
    #   "project": "...",
    #   "chapter": "...",
    #   "scenes": [...]
    # }
    #
    # NOT:
    #
    # {
    #   "chapter": {
    #       "scenes": [...]
    #   }
    # }

    if "scenes" not in data:
        raise ValueError(
            "Invalid JSON: top-level 'scenes' array not found."
        )

    if not isinstance(data["scenes"], list):
        raise ValueError(
            "Invalid JSON: 'scenes' must be an array."
        )

    return data


def flatten_panels(chapter: dict):
    panels = []

    for scene in chapter["scenes"]:
        if "panels" not in scene:
            raise ValueError(
                f"{scene.get('scene_id', 'UNKNOWN')}: "
                f"'panels' array not found."
            )

        for panel in scene["panels"]:
            panels.append(panel)

    return panels


# =========================================================
# GENERATE ONE VOICE SEGMENT
# =========================================================

async def generate_segment(
    panel_id: str,
    index: int,
    item: dict,
    semaphore: asyncio.Semaphore,
):
    speaker = str(
        item.get("speaker", "NARRATOR")
    )

    original_text = str(
        item.get("text", "")
    ).strip()

    if not original_text:
        return None

    tts_text = clean_tts_text(original_text)

    profile = get_profile(speaker)

    segment_path = (
        SEGMENT_DIR
        / f"{panel_id}_{index:02d}.mp3"
    )

    async with semaphore:

        if USE_CACHE and segment_is_valid(segment_path):
            print(
                f"   ♻️ CACHE "
                f"{panel_id}_{index:02d} "
                f"| {speaker}"
            )

        else:
            print(
                f"   🎙️ TTS "
                f"{panel_id}_{index:02d} "
                f"| {speaker}"
            )

            # Retry a few times because Edge TTS is network based.
            last_error = None

            for attempt in range(1, 4):
                try:
                    await synthesize(
                        tts_text,
                        profile,
                        segment_path,
                    )
                    break

                except Exception as exc:
                    last_error = exc

                    if attempt < 3:
                        print(
                            f"      retry {attempt}/2..."
                        )
                        await asyncio.sleep(
                            1.0 * attempt
                        )
                    else:
                        raise RuntimeError(
                            f"TTS failed for "
                            f"{panel_id} voice item {index}: "
                            f"{last_error}"
                        )

        if not segment_is_valid(segment_path):
            raise RuntimeError(
                f"Invalid generated audio:\n"
                f"{segment_path}"
            )

    return {
        "index": index,
        "speaker": speaker,
        "text": original_text,
        "tts_text": tts_text,
        "path": segment_path,
        "profile": profile,
    }


# =========================================================
# CREATE PANEL AUDIO
# =========================================================

async def create_panel_audio(
    panel: dict,
    semaphore: asyncio.Semaphore,
):
    panel_id = panel["panel_id"]

    voice_items = panel.get(
        "voice",
        [],
    )

    if not voice_items:
        raise ValueError(
            f"{panel_id}: voice array is empty."
        )

    print()
    print("=" * 60)
    print(f"PANEL: {panel_id}")
    print("=" * 60)

    # Generate all voice entries for this panel.
    tasks = []

    for index, item in enumerate(
        voice_items,
        start=1,
    ):
        tasks.append(
            generate_segment(
                panel_id,
                index,
                item,
                semaphore,
            )
        )

    results = await asyncio.gather(*tasks)

    # Keep exact JSON voice order.
    results = sorted(
        [r for r in results if r is not None],
        key=lambda x: x["index"],
    )

    panel_audio = AudioSegment.empty()

    for position, result in enumerate(results):
        audio = AudioSegment.from_file(
            result["path"]
        )

        if len(audio) <= 0:
            raise RuntimeError(
                f"{panel_id}: empty audio in "
                f"{result['path']}"
            )

        panel_audio += audio

        # Add pause only between actual generated voice entries.
        if position < len(results) - 1:
            panel_audio += AudioSegment.silent(
                duration=VOICE_GAP_MS
            )

    if len(panel_audio) <= 0:
        raise RuntimeError(
            f"{panel_id}: final panel audio is empty."
        )

    panel_audio_path = (
        AUDIO_DIR
        / f"{panel_id}.mp3"
    )

    panel_audio.export(
        panel_audio_path,
        format="mp3",
        bitrate="192k",
    )

    duration_ms = len(panel_audio)
    duration_sec = ms_to_seconds(
        duration_ms
    )

    # Replace the old/generated duration with REAL audio duration.
    panel["duration"] = duration_sec

    print(
        f"   ✅ duration = "
        f"{duration_sec:.3f}s"
    )

    return {
        "panel_id": panel_id,
        "duration": duration_sec,
        "duration_ms": duration_ms,
        "audio": str(
            panel_audio_path
        ).replace("\\", "/"),
    }


# =========================================================
# MAIN
# =========================================================

async def main():

    print()
    print("=" * 70)
    print("TRI-ANANT — HINDI EDGE TTS GENERATOR")
    print("=" * 70)
    print()

    print(f"Script folder : {BASE_DIR}")
    print(f"Input JSON    : {INPUT_JSON}")
    print(f"Output folder : {OUTPUT_DIR}")
    print()

    # -----------------------------------------------------
    # FOLDERS
    # -----------------------------------------------------

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    AUDIO_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    SEGMENT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # -----------------------------------------------------
    # LOAD
    # -----------------------------------------------------

    chapter = load_chapter()
    panels = flatten_panels(chapter)

    print(
        f"Project       : {chapter.get('project', 'UNKNOWN')}"
    )

    print(
        f"Chapter       : {chapter.get('chapter', 'UNKNOWN')}"
    )

    print(
        f"Scenes        : {len(chapter['scenes'])}"
    )

    print(
        f"Panels        : {len(panels)}"
    )

    print()

    # -----------------------------------------------------
    # SHOW VOICE ROUTING
    # -----------------------------------------------------

    print("VOICE ROUTING")
    print("-" * 70)

    for speaker, profile in VOICE_PROFILES.items():
        print(
            f"{speaker:15} -> "
            f"{profile['voice']} | "
            f"rate={profile['rate']} | "
            f"pitch={profile['pitch']}"
        )

    print("-" * 70)
    print(
        f"TTS concurrency : {TTS_CONCURRENCY}"
    )

    print(
        f"Voice gap      : {VOICE_GAP_MS} ms"
    )

    print()

    # -----------------------------------------------------
    # VALIDATE ALL PANELS BEFORE TTS
    # -----------------------------------------------------

    panel_ids = set()

    for panel in panels:

        panel_id = panel.get(
            "panel_id"
        )

        if not panel_id:
            raise ValueError(
                "A panel has no 'panel_id'."
            )

        if panel_id in panel_ids:
            raise ValueError(
                f"Duplicate panel_id: {panel_id}"
            )

        panel_ids.add(panel_id)

        if not panel.get("voice"):
            raise ValueError(
                f"{panel_id}: voice array is empty."
            )

    # -----------------------------------------------------
    # GENERATE
    # -----------------------------------------------------

    semaphore = asyncio.Semaphore(
        TTS_CONCURRENCY
    )

    duration_records = []

    for panel_number, panel in enumerate(
        panels,
        start=1,
    ):

        print()
        print(
            f"[{panel_number}/{len(panels)}]"
        )

        record = await create_panel_audio(
            panel,
            semaphore,
        )

        duration_records.append(
            record
        )

    # -----------------------------------------------------
    # SAVE UPDATED CHAPTER JSON
    # -----------------------------------------------------

    with UPDATED_JSON.open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            chapter,
            f,
            ensure_ascii=False,
            indent=2,
        )

    # -----------------------------------------------------
    # SAVE DURATION JSON
    # -----------------------------------------------------

    with DURATION_JSON.open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            {
                "project": chapter.get(
                    "project",
                    "UNKNOWN",
                ),

                "chapter": chapter.get(
                    "chapter",
                    "UNKNOWN",
                ),

                "voice": {
                    "engine": "Edge TTS",

                    "profiles": VOICE_PROFILES,

                    "default_profile": DEFAULT_PROFILE,

                    "voice_gap_ms": VOICE_GAP_MS,

                    "tts_concurrency": TTS_CONCURRENCY,
                },

                "panels": duration_records,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    # -----------------------------------------------------
    # SUMMARY
    # -----------------------------------------------------

    total = sum(
        record["duration"]
        for record in duration_records
    )

    print()
    print("=" * 70)
    print("VOICE GENERATION COMPLETE")
    print("=" * 70)

    print(
        f"Scenes        : "
        f"{len(chapter['scenes'])}"
    )

    print(
        f"Panels        : "
        f"{len(duration_records)}"
    )

    print(
        f"Voice time    : "
        f"{total:.3f}s "
        f"({total / 60:.2f} min)"
    )

    print(
        f"Audio folder  : "
        f"{AUDIO_DIR}"
    )

    print(
        f"Updated JSON  : "
        f"{UPDATED_JSON}"
    )

    print(
        f"Durations     : "
        f"{DURATION_JSON}"
    )

    print("=" * 70)


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    asyncio.run(main())
 