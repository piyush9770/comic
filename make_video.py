import os
import glob
import shutil
import subprocess

# ================= CONFIG =================
BASE_DIR = r"D:\Desktop\comic\image_generator"
IMAGE_DIR = os.path.join(BASE_DIR, "outputs", "against_the_gods_prologue")
WORK_DIR = os.path.join(BASE_DIR, "comic_motion")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "against_the_gods_smooth_comic.mp4")

FFMPEG = "ffmpeg"
WIDTH, HEIGHT = 1024, 576
FPS = 30
SCENE_DURATION = 3.0
TRANSITION = 0.35
WORK_WIDTH, WORK_HEIGHT = 2560, 1440    

# Purane clips hatakar naye sire se banane ke liye True rakhiye
REBUILD_CLIPS = True

MOVEMENTS = ["zoom_in", "zoom_out", "pan_lr", "pan_rl", "pan_tb", "pan_bt", "diag"]

# ================= PREPARE =================
os.makedirs(WORK_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

images = sorted(glob.glob(os.path.join(IMAGE_DIR, "scene_*.png")))
if not images:
    print("No images found:", IMAGE_DIR)
    raise SystemExit(1)

try:
    subprocess.run([FFMPEG, "-version"], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, check=True)
except Exception:
    print("FFmpeg not found!")
    raise SystemExit(1)

print(f"Images: {len(images)} | {WIDTH}x{HEIGHT} | {FPS} FPS")

if REBUILD_CLIPS:
    for old in glob.glob(os.path.join(WORK_DIR, "scene_*.mp4")):
        os.remove(old)


# ================= CAMERA FILTER =================
def camera_filter(movement):
    frames = int(SCENE_DURATION * FPS)
    last = frames - 1

    # NOTE: zoompan mein frame number ka variable chhota "on" hai
    t = f"(on/{last})"
    ease = f"(3*{t}*{t}-2*{t}*{t}*{t})"   # smoothstep

    if movement == "zoom_in":
        zoom = f"(1.0+0.12*{ease})"
        x, y = "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
    elif movement == "zoom_out":
        zoom = f"(1.12-0.12*{ease})"
        x, y = "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
    elif movement == "pan_lr":
        zoom = "1.10"
        x, y = f"(iw-iw/zoom)*{ease}", "(ih-ih/zoom)/2"
    elif movement == "pan_rl":
        zoom = "1.10"
        x, y = f"(iw-iw/zoom)*(1-{ease})", "(ih-ih/zoom)/2"
    elif movement == "pan_tb":
        zoom = "1.10"
        x, y = "(iw-iw/zoom)/2", f"(ih-ih/zoom)*{ease}"
    elif movement == "pan_bt":
        zoom = "1.10"
        x, y = "(iw-iw/zoom)/2", f"(ih-ih/zoom)*(1-{ease})"
    else:  # diag
        zoom = "1.10"
        x, y = f"(iw-iw/zoom)*{ease}", f"(ih-ih/zoom)*(1-{ease})"

    return (
        f"scale={WORK_WIDTH}:{WORK_HEIGHT}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={WORK_WIDTH}:{WORK_HEIGHT},"
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS},"
        f"format=yuv420p"
    )


# ================= CREATE CLIPS =================
clips = []
print("\nCreating camera-motion clips...\n")

for i, image in enumerate(images):
    scene = i + 1
    movement = MOVEMENTS[i % len(MOVEMENTS)]
    output = os.path.join(WORK_DIR, f"scene_{scene:03d}.mp4")
    clips.append(output)

    print(f"[{scene:02d}/{len(images)}] {movement}")

    if os.path.exists(output) and os.path.getsize(output) > 10000:
        print("    existing")
        continue

    command = [
        FFMPEG, "-y",
        "-i", image,
        "-vf", camera_filter(movement),
        "-frames:v", str(int(SCENE_DURATION * FPS)),
        "-r", str(FPS),
        "-an",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        output,
    ]

    result = subprocess.run(command, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        print("\nFFmpeg error:\n", result.stderr[-1500:])
        raise SystemExit(1)


# ================= CROSSFADE =================
print("\nCreating smooth transitions...\n")

if len(clips) == 1:
    shutil.copyfile(clips[0], OUTPUT_FILE)
    print("Video created:", OUTPUT_FILE)
    raise SystemExit(0)

input_args = []
for c in clips:
    input_args += ["-i", c]

parts = []
current = "[0:v]"
offset = SCENE_DURATION - TRANSITION

for i in range(1, len(clips)):
    label = f"[v{i}]"
    parts.append(
        f"{current}[{i}:v]xfade=transition=fade:"
        f"duration={TRANSITION}:offset={offset:.3f}{label}"
    )
    current = label
    offset += SCENE_DURATION - TRANSITION

command = [
    FFMPEG, "-y", *input_args,
    "-filter_complex", ";".join(parts),
    "-map", current,
    "-c:v", "libx264",
    "-preset", "medium",
    "-crf", "18",
    "-pix_fmt", "yuv420p",
    "-r", str(FPS),
    "-movflags", "+faststart",
    OUTPUT_FILE,
]

result = subprocess.run(command, stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE, text=True)
if result.returncode != 0:
    print("\nFinal transition error:\n", result.stderr[-1500:])
    raise SystemExit(1)

print("\nSMOOTH COMIC VIDEO READY")
print(OUTPUT_FILE)

























































































