# ============================================================
# COMIC STYLE PATCH
# Apne script me ye saare functions/constants REPLACE karo:
#   get_movement, should_float, make_video_filter,
#   smart_wrap_hindi, write_panel_ass
# (baaki script same rahegi)
# ============================================================

# ---------- COMIC SETTINGS (CONFIG section me daal do) ----------
COMIC_PAGE_COLOR = "0xF3EBD8"   # cream paper colour
COMIC_MARGIN = 18               # page margin (px)
COMIC_BORDER = 6                # black panel border (px)
PANEL_W = WIDTH - 2 * (COMIC_MARGIN + COMIC_BORDER)    # 1232
PANEL_H = HEIGHT - 2 * (COMIC_MARGIN + COMIC_BORDER)   # 672

# Subtitle font: comic jaisa Hindi look chahiye to "Kalam" ya "Tillana"
# (Google Fonts se install karo). Warna Noto Sans Devanagari chalega.
SUBTITLE_FONT = "Noto Sans Devanagari"


def get_movement(index, duration):
    """Halka, smooth camera move (jhatka nahi)."""
    moves = (
        "PUSH_IN",
        "PUSH_IN_LEFT",
        "PULL_OUT",
        "PUSH_IN_RIGHT",
        "L-R",
        "PUSH_IN",
        "R-L",
        "PULL_OUT",
    )
    return moves[(index - 1) % len(moves)]


def should_float(index, panel):
    return False


# movement -> (zoom_start, zoom_end, x_start, x_end, y_start, y_end)
# x/y 0..1 = image ke andar camera ki position (0.5 = center)
_MOVES = {
    "PUSH_IN":       (1.00, 1.08, 0.50, 0.50, 0.50, 0.50),
    "PUSH_IN_LEFT":  (1.00, 1.08, 0.62, 0.38, 0.50, 0.45),
    "PUSH_IN_RIGHT": (1.00, 1.08, 0.38, 0.62, 0.50, 0.45),
    "PULL_OUT":      (1.08, 1.00, 0.50, 0.50, 0.45, 0.50),
    "L-R":           (1.08, 1.08, 0.25, 0.75, 0.50, 0.50),
    "R-L":           (1.08, 1.08, 0.75, 0.25, 0.50, 0.50),
}


def make_video_filter(duration, movement, floating=False, subtitle_path=None):
    """
    Comic look:
      1. image ko 3200px tak upscale  -> zoompan me jitter/jhatka nahi
      2. zoompan (ease in-out camera)
      3. halka contrast/saturation + sharpen + static paper grain
      4. kaala panel border
      5. cream paper page background
      6. comic caption boxes (ASS)
    """
    duration = max(0.1, float(duration))
    frames = max(2, int(round(duration * FPS)))

    z0, z1, x0, x1, y0, y1 = _MOVES.get(movement, _MOVES["PUSH_IN"])

    up_w = 3200
    up_h = int(round(up_w * PANEL_H / PANEL_W))
    up_h += up_h % 2

    e = f"(1-cos(PI*on/{frames}))/2"          # smooth ease in-out

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
        "noise=alls=5:allf=u",                  # static print grain
        # black comic panel border
        f"pad={PANEL_W + 2 * COMIC_BORDER}:{PANEL_H + 2 * COMIC_BORDER}"
        f":{COMIC_BORDER}:{COMIC_BORDER}:color=black",
        # cream paper page
        f"pad={WIDTH}:{HEIGHT}"
        f":{COMIC_MARGIN}:{COMIC_MARGIN}:color={COMIC_PAGE_COLOR}",
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


def smart_wrap_hindi(text, max_chars=34):
    text = clean_text(text)
    if len(text) <= max_chars:
        return text
    lines, current = [], ""
    for word in text.split():
        cand = word if not current else current + " " + word
        if len(cand) <= max_chars:
            current = cand
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return "\n".join(lines)   # ass_escape isko \N bana deta hai


_NARRATOR_NAMES = {"NARRATOR", "NARRATION", "सूत्रधार", "कथावाचक"}


def write_panel_ass(panel, ass_path):
    """Comic caption boxes: narration = peela box (upar-left),
    dialogue = safed speech box (neeche-center). Kaala outline ke saath."""
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
            # peela caption box, top-left
            box = "&H0080E6FF&"          # yellow (BGR)
            pos = r"\an7\pos(" + str(COMIC_MARGIN + COMIC_BORDER + 26) + "," + str(COMIC_MARGIN + COMIC_BORDER + 22) + ")"
            body = text
        else:
            # safed speech box, bottom-center
            box = "&H00FFFFFF&"
            pos = r"\an2"
            body = (
                r"{\fs21\c&H00007A&}" + speaker + r"\N"
                r"{\fs30\c&H101010&}" + text
            )

        anim = r"\fad(120,90)\fscx92\fscy92\t(0,140,\fscx100\fscy100)"
        start, end = format_ass_time(entry["start"]), format_ass_time(entry["end"])

        # Layer 0: kaala bada box (border), Layer 1: rang wala box
        for layer, bord, colour in ((0, 11, "&H00000000&"), (1, 6, box)):
            out.append(
                f"Dialogue: {layer},{start},{end},Default,,0,0,0,,"
                "{" + pos + anim + r"\bord" + str(bord) + r"\3c" + colour + "}"
                + body + "\n"
            )

    ass_path.write_text("".join(out), encoding="utf-8")