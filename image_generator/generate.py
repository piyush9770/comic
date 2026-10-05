# ============================================================
# AGAINST THE GODS - PROLOGUE COMIC (50 SCENES)
# LOCAL VERSION: MeinaMix V11 (SD 1.5) | NVIDIA RTX 2050 4GB
#
# Folder structure:
#   generate.py                  <- ye file
#   models/meinamix_meinaV11.safetensors
#   outputs/                     <- images yahan banengi
#
# Purane prompts ki problems jo fix hui:
#  1. Lambi sentences -> danbooru tags (MeinaMix tags better samajhta hai)
#  2. CLIP ki 75 token limit -> script khud check/trim karti hai
#  3. Character tags har scene me same -> chehra consistent
#  4. Camera angles (close-up, low angle, from above...) add kiye
#  5. 1024x576 SD1.5 pe double body/face banata tha -> 768x432 use hota hai
# ============================================================

import os
import json
import torch

from diffusers import StableDiffusionPipeline, DPMSolverMultistepScheduler

# ---------------- CONFIG ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "models", "meinamix_meinaV11.safetensors")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs", "against_the_gods_prologue")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 16:9. 4GB VRAM + SD1.5 ke liye safe. Out of memory aaye to 640x360 karo.
WIDTH, HEIGHT = 768, 432

STEPS = 28
CFG = 7.0
CLIP_SKIP = None       # 2 karne se anime look thoda better, par kuch versions me error aata hai
                       # ("CLIPTextModel has no attribute text_model"). Pehle None rakho.
BASE_SEED = 5000
NUM_VARIANTS = 1       # 2-3 karoge to har scene ki multiple images banengi
RESUME = True          # True = jo image bani hui hai use skip

# ---------------- CHECKS ----------------
print("=" * 60)
print("AGAINST THE GODS - PROLOGUE (MeinaMix V11, local)")
print("=" * 60)

if not os.path.isfile(MODEL_PATH):
    raise FileNotFoundError(f"MeinaMix model nahi mila: {MODEL_PATH}")
if not torch.cuda.is_available():
    raise RuntimeError("CUDA available nahi hai.")

print("GPU:", torch.cuda.get_device_name(0))
print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.2f} GB")

# ---------------- LOAD MODEL ----------------
pipe = StableDiffusionPipeline.from_single_file(
    MODEL_PATH,
    torch_dtype=torch.float16,
    use_safetensors=True,
    safety_checker=None,
)

# DPM++ 2M Karras: SD1.5 anime models pe clean result deta hai
pipe.scheduler = DPMSolverMultistepScheduler.from_config(
    pipe.scheduler.config, use_karras_sigmas=True
)

# RTX 2050 4GB memory management
pipe.enable_model_cpu_offload()
for fn in ("enable_attention_slicing", "enable_vae_slicing", "enable_vae_tiling"):
    try:
        getattr(pipe, fn)()
    except Exception:
        pass

print("MeinaMix V11 loaded.")

# ============================================================
# TAG BANK + 50 SCENES
# ============================================================

QUALITY = "masterpiece, best quality, very aesthetic, absurdres, anime screencap, cinematic lighting"

# Yun Che (present, cliff par): ghayal, khoon se sana
YC = "1boy, yun che, black hair, long hair, black eyes, black robe, blood on clothes, wounds, injured"
# Yun Che (kishor/young man, flashback)
YC_TEEN = "1boy, teenager, black hair, black eyes, simple black robe"
YC_MAN = "1boy, young man, black hair, long hair, black eyes, black robe, crimson trim"
# Baby / bacha
BABY = "baby, newborn, black hair, wrapped in white cloth"
KID = "male child, black hair, black eyes, simple white robe"
# Master (guru)
MASTER = "old man, white hair, long white beard, green robe, kind eyes, wrinkles, elderly healer"
# Crowd / elders
CROWD = "multiple boys, 6+boys, crowd, fantasy robes, ornate robes, cultivators"
ELDERS = "old man, elders, clan leaders, ornate robes, long beard, stern faces"
# Objects / place
PEARL = "glowing green pearl, jade green orb, faint green light"
CLIFF = "cliff edge, dark abyss, mist, ancient jagged rocks"
ROCK = "leaning against giant boulder"
PENDANT = "silver pendant, locket on chest"

# ============================================================
# 50 SCENES  (title, tags)
# Order = importance (subject -> action -> camera -> mood)
# ============================================================

SCENES = [
# ---------- ACT 1: Cloud's End Cliff (establishing) ----------
("01 mountain establishing",
 "no humans, scenery, wide shot, from far, gigantic mythical mountain, enormous cliff, bottomless abyss, floating mist, dark storm clouds, ancient fantasy world, ominous"),
("02 abyss depth",
 "no humans, scenery, from above, looking down, endless dark abyss, sheer cliff wall, thick fog, deep shadow, jagged rocks like tombstones, death, ominous, hopeless"),
("03 yun che at edge",
 f"{YC}, {ROCK}, {CLIFF}, standing, full body, wide shot, blood puddle, sunset, red sky, tragic"),
("04 blood pool",
 "close-up, feet focus, blood puddle, dripping blood, torn black robe, boots, stone ground, cliff edge, dim light"),
("05 heavy breathing",
 f"{YC}, upper body, heavy breathing, open mouth, sweat, trembling, exhausted, {ROCK}, chest heaving, dramatic lighting"),
("06 cold eyes",
 f"{YC}, face focus, extreme close-up, cold eyes, sharp eyes, wolf-like glare, contemptuous smirk, blood on face, black hair blowing"),

# ---------- ACT 2: The crowd ----------
("07 surrounded",
 f"{CROWD}, surrounding, from behind the crowd, small figure of 1boy, black robe, {ROCK}, cliff edge, blocked escape, wide shot, tense"),
("08 clan leaders",
 f"{ELDERS}, powerful aura, standing in group, from below, dramatic angle, fantasy sect, glaring, ancient masters"),
("09 crowd demands",
 f"{CROWD}, shouting, open mouth, pointing, angry, greedy faces, cliff edge, medium shot, dramatic"),
("10 cold laugh",
 f"{YC}, upper body, cold laugh, contemptuous smile, head tilt, hair over face, {CLIFF}, looking at viewer"),
("11 raises hand",
 f"{YC}, raised right hand, extended arm, open palm, bloody hand, from side, crowd blurred in background, dramatic"),
("12 sky poison pearl",
 f"close-up, hand focus, bloody hand holding {PEARL}, dark background, glowing, reflection, magical"),
("13 crowd freezes",
 f"{CROWD}, frozen, staring, wide eyes, green light on faces, silence, tense atmosphere, wide shot"),
("14 greed",
 "multiple boys, close-up faces, greedy, wide eyes, grin, green glow on faces, dark background, glowing green pearl reflected in eyes"),
("15 arrogant gaze",
 f"{YC}, upper body, looking at viewer, arrogant, disdain, glaring, hatred in eyes, holding {PEARL}, {CLIFF}"),

# ---------- ACT 3: Master's memory ----------
("16 speaks of master",
 f"{YC}, shouting, angry, clenched teeth, tears, furious, grief, upper body, dynamic angle"),
("17 blood tears",
 f"{YC}, face focus, close-up, crying, tears of blood, red tears, clenched teeth, hatred, sad eyes"),
("18 flashback spring",
 "no humans, scenery, flashback, spring, scattered clouds, spiritual mountains, clear stream, gentle breeze, soft sunlight, green hills, pastel colors, peaceful"),
("19 master finds baby",
 f"{MASTER}, kneeling by stream, finding {BABY}, surprised, gentle, spring, spiritual mountains, soft light, flashback"),
("20 master holds baby",
 f"{MASTER}, holding {BABY}, gentle smile, looking down, warm light, mountains, clouds, tender, flashback"),
("21 name yun che",
 f"{BABY}, close-up, sleeping, {PENDANT}, clear water reflection, clouds above, sunlight, serene, flashback"),
("22 learning medicine",
 f"{MASTER}, {KID}, herbs, wooden table, teaching medicine, simple hut, warm lamp light, learning, flashback"),
("23 healing patients",
 f"{MASTER}, healing, sick villager lying on bed, applying medicine, compassionate, hut interior, warm light, flashback"),
("24 pearl in master",
 f"{MASTER}, {PEARL}, floating above palm, green aura, pouring herbs into cauldron, purifying poison, steam, alchemy"),
("25 medicine refining",
 "no humans, close-up, alchemy cauldron, green liquid, glowing vials, herbs, mortar and pestle, steam, warm hut, magical, detailed"),
("26 passing knowledge",
 f"{MASTER}, {KID}, sitting together, scrolls, books, herbs, teaching, warm smile, lamp light, hut, flashback"),
("27 seven years ago - flee",
 f"{MASTER}, {YC_TEEN}, handing {PEARL}, urgent, panicked, pushing away, night, torches in distance, dramatic, flashback"),

# ---------- ACT 4: Grief to revenge ----------
("28 news of death",
 f"{YC_TEEN}, kneeling, shocked, pale, trembling, wide eyes, dark room, rain outside, dim light, despair"),
("29 three days crying",
 f"{YC_TEEN}, kneeling before grave marker, crying, tears, hunched, rain, moonlight, lonely, mountain, sad"),
("30 abandons medicine",
 f"{YC_TEEN}, throwing away herbs, scattered scrolls, dark eyes, resolute, hatred, dim room, green glow, turning point"),
("31 absorbing poison",
 f"{YC_TEEN}, meditation, sitting, closed eyes, floating {PEARL}, poison aura, dark energy swirling, cave, night, veins glowing green"),
("32 mastered poison",
 f"{YC_MAN}, standing, green poison mist swirling, holding {PEARL}, cold eyes, revenge, determined, dark background"),
("33 poison spreads",
 "no humans, scenery, from above, vast land, green poison mist spreading, dead trees, ruined village, dark sky, ominous, fantasy world"),
("34 the hunt",
 f"{YC_MAN}, running, from behind, pursued by many silhouettes on flying swords, mountains, dusk, chase, dynamic, tense"),

# ---------- ACT 5: Final confrontation ----------
("35 standoff",
 f"{CROWD}, standoff, facing 1boy, black robe, {ROCK}, cliff edge, wide shot, wind, blood, tense atmosphere, dusk"),
("36 hatred laugh",
 f"{YC}, upper body, low angle, laughing, evil smile, hatred, glaring, blood, wind blowing hair, {CLIFF}"),
("37 roar",
 f"{YC}, shouting, open mouth, furious, dynamic angle, from below, blood, wind, veins, defiant, upper body"),
("38 pearl to mouth",
 f"{YC}, close-up, hand near mouth, holding {PEARL}, mouth open, defiant, smirk, blood"),
("39 crowd shocked",
 f"{CROWD}, shocked, wide eyes, open mouth, pointing, horrified, faces close-up, dim light"),
("40 swallows pearl",
 f"{YC}, head tilted back, swallowing, closed eyes, throat, {PEARL}, green light on face, dramatic"),
("41 green glow",
 f"{YC}, standing, green glow, glowing aura, light particles, calm smirk, crowd shocked in background, supernatural"),
("42 they charge",
 f"{CROWD}, charging, rushing forward, motion blur, dynamic angle, attacking, energy, toward viewer, dusk, cliff edge"),
("43 weak laugh",
 f"{YC}, upper body, weak smile, laughing, blood from mouth, exhausted, defiant, wind, attackers blurred behind"),
("44 the jump",
 f"{YC}, from side, jumping backward, arms spread, midair, cliff edge, blood droplets, motion lines, dramatic, dynamic"),
("45 hands miss",
 "reaching hands, outstretched arms, grasping at air, from behind cliff edge, wide eyes, failing to catch, dusk sky, despair"),

# ---------- ACT 6: The fall ----------
("46 falling wide",
 f"{YC}, falling, from above, tiny figure, huge abyss, cliff walls, darkness, tiny people at cliff edge above, wide shot"),
("47 falling close",
 f"{YC}, falling, face focus, wind, hair blowing upward, dark, motion blur, eyes half closed, resigned"),
("48 holds pendant",
 f"{YC}, close-up, hand holding {PENDANT}, hand on chest, falling, wind, melancholic, tears, closed eyes"),
("49 masters smile",
 f"{YC}, falling, closed eyes, peaceful, {PENDANT}, faint image of old man smiling in clouds, memory, double exposure, ethereal"),
("50 final frame",
 f"{YC}, falling, from below, silhouette, eyes closed, holding {PENDANT}, endless darkness, tiny figure, light fading, hair blowing, final scene"),
]

# ============================================================
# NEGATIVE
# ============================================================

NEGATIVE = (
    "worst quality, low quality, lowres, blurry, jpeg artifacts, bad anatomy, bad hands, "
    "extra fingers, missing fingers, extra arms, extra legs, fused fingers, deformed face, "
    "duplicate, multiple views, cropped, out of frame, text, watermark, signature, "
    "3d, realistic, chibi, modern clothes"
)

# ============================================================
# TOKEN LIMIT CHECK (CLIP = 77 tokens)
# ============================================================

tok = pipe.tokenizer


def n_tokens(text):
    return len(tok(text).input_ids) - 2


def fit(text, limit=75):
    """Prompt limit se bada ho to aakhri (kam zaroori) tags hata do."""
    tags = [t.strip() for t in text.split(",") if t.strip()]
    dropped = []
    while n_tokens(", ".join(tags)) > limit and len(tags) > 1:
        dropped.append(tags.pop())
    return ", ".join(tags), dropped


# ============================================================
# GENERATE
# ============================================================

TOTAL = len(SCENES)
neg_final, _ = fit(NEGATIVE)
log = []

print(f"\nScenes: {TOTAL} | Size: {WIDTH}x{HEIGHT} | Steps: {STEPS} | CFG: {CFG}\n")

for i, (title, tags) in enumerate(SCENES, 1):
    prompt, dropped = fit(f"{QUALITY}, {tags}")
    log.append({"scene": i, "title": title, "prompt": prompt, "dropped_tags": dropped})
    if dropped:
        print(f"Warning Scene {i:02d}: token limit ki wajah se tags hate -> {dropped}")

    for v in range(NUM_VARIANTS):
        suffix = "" if NUM_VARIANTS == 1 else f"_v{v + 1}"
        path = os.path.join(OUTPUT_DIR, f"scene_{i:02d}{suffix}.png")

        if RESUME and os.path.isfile(path):
            print(f"SKIP scene {i:02d}{suffix} (already exists)")
            continue

        torch.cuda.empty_cache()
        seed = BASE_SEED + i * 10 + v
        gen = torch.Generator(device="cuda").manual_seed(seed)
        print(f"Generating scene {i:02d}/{TOTAL}{suffix} | {title} | seed {seed}")

        try:
            with torch.inference_mode():
                image = pipe(
                    prompt=prompt,
                    negative_prompt=neg_final,
                    width=WIDTH,
                    height=HEIGHT,
                    num_inference_steps=STEPS,
                    guidance_scale=CFG,
                    clip_skip=CLIP_SKIP,
                    generator=gen,
                ).images[0]
            image.save(path)
            print("Saved:", path)
            del image
        except torch.cuda.OutOfMemoryError:
            print("CUDA OUT OF MEMORY -> WIDTH/HEIGHT ko 640x360 karke dobara chalao")
            torch.cuda.empty_cache()
            break
        except RuntimeError as e:
            print("Scene failed:", e)
        finally:
            torch.cuda.empty_cache()

with open(os.path.join(OUTPUT_DIR, "prompts_log.json"), "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False, indent=2)

# ---------------- FINAL CHECK ----------------
done = sum(
    os.path.isfile(os.path.join(OUTPUT_DIR, f"scene_{i:02d}{'' if NUM_VARIANTS == 1 else '_v1'}.png"))
    for i in range(1, TOTAL + 1)
)
print("\n" + "=" * 60)
print(f"DONE | Generated: {done}/{TOTAL}")
print("Output folder:", os.path.abspath(OUTPUT_DIR))
print("=" * 60)