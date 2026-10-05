# ============================================================
# NOVEL CHAPTER JSON -> IMAGE GENERATOR  (IP-Adapter version)
# MeinaMix V11 / SD 1.5 / NVIDIA RTX 2050 4GB
#
# INPUT : chapter_v2.json   (each panel has "refs": ["rudransh"] etc.)
# REFS  : refs/<name>.png  (characters + locations, names are in
#         chapter_v2.json -> reference_images)
# OUTPUT: outputs/<chapter_id>/001_PANEL_001.png ... + prompts_log.json
#
# One PANEL = one image. panel["refs"][0] = character reference,
# panel["loc_ref"] = location reference. Missing = text-only.
# ============================================================

import re
import json
import argparse
from pathlib import Path

import torch
from PIL import Image
from diffusers import StableDiffusionPipeline, DPMSolverMultistepScheduler


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

MODEL_PATH = BASE_DIR / "models" / "meinamix_meinaV11.safetensors"
DEFAULT_JSON = BASE_DIR / "chapter_v2.json"
OUTPUT_ROOT = BASE_DIR / "outputs"
REF_DIR = BASE_DIR / "refs"

WIDTH, HEIGHT = 768, 432

STEPS = 45
CFG = 7.0
CLIP_SKIP = None

BASE_SEED = 5000
NUM_VARIANTS = 1
RESUME = True

# ---4- IP-Adapter ----
USE_IP_ADAPTER = True
USE_LOCATION_REFS = True     # True = 2 adapters (character + location). False = character only (kam VRAM)
IP_ADAPTER_REPO = "h9/IP-Adapter"
IP_ADAPTER_SUBFOLDER = "models"
IP_CHAR_WEIGHT = "ip-adapter-plus_sd15.bin"   # slot 0: character
IP_LOC_WEIGHT = "ip-adapter_sd15.bin"         # slot 1: location
IP_SCALE = 0.6        # character: 0.4 weak, 0.6 balanced, 0.8 strong (pose may get copied)
LOC_SCALE = 0.4       # location: 0.3 weak, 0.4 balanced, 0.6 strong

IP_SLOTS = 0          # runtime: 0 = off, 1 = character only, 2 = character + location
_REF_CACHE = {}
_MISSING_REFS = set()
DUMMY_IMAGE = Image.new("RGB", (224, 224), (128, 128, 128))

NEGATIVE = (
    "worst quality, low quality, lowres, blurry, jpeg artifacts, "
    "bad anatomy, bad hands, extra fingers, missing fingers, extra arms, "
    "extra legs, deformed face, duplicate, multiple views, "
    "cropped, text, watermark, signature, 3d, chibi, "
    "modern clothes, photorealistic"
)

QUALITY = "masterpiece, best quality, anime screencap, dramatic lighting"


# ============================================================
# HELPERS
# ============================================================

def clean_text(value):
    if value is None:
        return ""
    return str(value).strip()


def safe_name(value):
    value = clean_text(value)
    value = re.sub(r'[<>:"/\\|?*]', "_", value)
    value = re.sub(r"\s+", "_", value)
    return value[:100] or "chapter"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("JSON root object/dict hona chahiye.")

    if isinstance(data.get("chapter"), str) and "scenes" in data:
        chapter_title = clean_text(data.get("chapter"))
        chapter = {
            "chapter_id": safe_name(chapter_title) or "CHAPTER",
            "chapter_title": chapter_title,
            "format": data.get("format", "16:9"),
            "language": data.get("language", "Hindi"),
            "style": data.get("style", ""),
            "continuity_rules": data.get("continuity_rules", []),
            "memory": data.get("memory", {}),
            "scenes": data.get("scenes", []),
        }
        if not isinstance(chapter["scenes"], list):
            raise ValueError("Root 'scenes' list hona chahiye.")
        return chapter

    if "chapter" not in data:
        raise ValueError("JSON format invalid: root me 'chapter' nahi mila.")

    chapter = data["chapter"]
    if not isinstance(chapter, dict):
        raise ValueError("'chapter' string hai aur root 'scenes' nahi mile.")
    if "scenes" not in chapter or not isinstance(chapter["scenes"], list):
        raise ValueError("'chapter.scenes' list nahi mila.")
    return chapter


def flatten_panels(chapter):
    panels = []
    for scene_index, scene in enumerate(chapter.get("scenes", []), 1):
        scene_id = scene.get("scene_id", f"SCENE_{scene_index:02d}")
        scene_title = scene.get("scene_title", scene.get("title", ""))
        scene_type = scene.get("scene_type", "PRESENT")

        for panel_index, panel in enumerate(scene.get("panels", []), 1):
            if not isinstance(panel, dict):
                continue
            panel_copy = dict(panel)
            panel_copy["_scene_id"] = scene_id
            panel_copy["_scene_title"] = scene_title
            panel_copy["_scene_type"] = panel.get("scene_type", scene_type)
            panel_copy["_scene_index"] = scene_index
            panel_copy["_panel_index_in_scene"] = panel_index
            panels.append(panel_copy)
    return panels


# ============================================================
# MEMORY -> VISUAL TAGS (kept for text names in prompts)
# ============================================================

def build_memory_visuals(memory):
    visual_map = {}
    for key, field in (("characters", "appearance"),
                       ("locations", "description"),
                       ("objects", "description")):
        for _, data in memory.get(key, {}).items():
            if not isinstance(data, dict):
                continue
            name = clean_text(data.get("name"))
            desc = clean_text(data.get(field))
            if name and desc:
                visual_map[name] = desc
    return visual_map


def visualize_canonical_names(prompt, visual_map):
    result = clean_text(prompt)
    for name in sorted(visual_map.keys(), key=len, reverse=True):
        if name and visual_map[name]:
            result = result.replace(name, visual_map[name])
    return result


def panel_voice_text(panel):
    voice = panel.get("voice", [])
    if not isinstance(voice, list):
        return ""
    parts = []
    for item in voice:
        if isinstance(item, dict):
            text = clean_text(item.get("text"))
            if text:
                parts.append(text)
    return " ".join(parts)


# ============================================================
# PROMPT BUILDING
# ============================================================

def comma_tags(text):
    return re.sub(r"\s+", " ", clean_text(text))


def token_count(tokenizer, text):
    return len(tokenizer(text).input_ids) - 2


def fit_prompt(tokenizer, text, limit=75):
    text = comma_tags(text)
    if token_count(tokenizer, text) <= limit:
        return text, []

    parts = [x.strip() for x in text.split(",") if x.strip()]
    dropped = []
    while len(parts) > 1 and token_count(tokenizer, ", ".join(parts)) > limit:
        dropped.append(parts.pop())
    return ", ".join(parts), dropped


def build_prompt(pipe, panel, visual_map):
    raw = clean_text(panel.get("image_prompt"))
    if not raw:
        raise ValueError(f"{panel.get('panel_id', 'UNKNOWN')} me image_prompt missing hai.")

    visual_prompt = visualize_canonical_names(raw, visual_map)
    scene_type = clean_text(panel.get("_scene_type", "PRESENT"))

    style = QUALITY
    if scene_type == "FLASHBACK":
        style += ", soft memory atmosphere, flashback"

    prompt = f"{style}, {visual_prompt}"
    return fit_prompt(pipe.tokenizer, prompt)


def build_negative(pipe):
    final_negative, dropped = fit_prompt(pipe.tokenizer, NEGATIVE)
    if dropped:
        print("Warning: negative prompt trimmed:", dropped)
    return final_negative


# ============================================================
# REFERENCE IMAGES
# ============================================================

def load_ref(name):
    """Return a PIL reference image for refs/<name>.(png|jpg|jpeg|webp) or None."""
    name = clean_text(name)
    if not name:
        return None
    if name in _REF_CACHE:
        return _REF_CACHE[name]

    img = None
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        p = REF_DIR / f"{name}{ext}"
        if p.is_file():
            img = Image.open(p).convert("RGB")
            break

    if img is None and name not in _MISSING_REFS:
        _MISSING_REFS.add(name)
        print(f"   WARNING: refs/{name}.png nahi mila -> text-only prompt use hoga")

    _REF_CACHE[name] = img
    return img


# ============================================================
# MODEL
# ============================================================

def load_pipeline():
    global IP_SLOTS

    if not MODEL_PATH.is_file():
        raise FileNotFoundError(
            f"MeinaMix model nahi mila:\n{MODEL_PATH}\n\n"
            "Model ko models/meinamix_meinaV11.safetensors me rakho."
        )
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA available nahi hai. NVIDIA driver + CUDA PyTorch check karo.")

    print("=" * 70)
    print("NOVEL CHAPTER -> IMAGE GENERATOR (IP-Adapter)")
    print("=" * 70)
    print("GPU:", torch.cuda.get_device_name(0))
    print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.2f} GB")
    print("Model:", MODEL_PATH)

    pipe = StableDiffusionPipeline.from_single_file(
        str(MODEL_PATH),
        torch_dtype=torch.float16,
        use_safetensors=True,
        safety_checker=None,
    )

    pipe.scheduler = DPMSolverMultistepScheduler.from_config(
        pipe.scheduler.config,
        use_karras_sigmas=True,
    )

    # IP-Adapter must be loaded BEFORE enable_model_cpu_offload()
    if USE_IP_ADAPTER:
        IP_SLOTS = 0

        if USE_LOCATION_REFS:
            try:
                print("Loading IP-Adapters (character + location) ... pehli baar download hoga")
                pipe.load_ip_adapter(
                    IP_ADAPTER_REPO,
                    subfolder=[IP_ADAPTER_SUBFOLDER, IP_ADAPTER_SUBFOLDER],
                    weight_name=[IP_CHAR_WEIGHT, IP_LOC_WEIGHT],
                )
                pipe.set_ip_adapter_scale([IP_SCALE, LOC_SCALE])
                IP_SLOTS = 2
                print("IP-Adapter ready: character + location.")
            except Exception as exc:
                print(f"2-adapter load nahi hua ({type(exc).__name__}: {exc})")
                print("Sirf character adapter try kar raha hoon...")
                try:
                    pipe.unload_ip_adapter()
                except Exception:
                    pass

        if IP_SLOTS == 0:
            try:
                print("Loading IP-Adapter (character only):", IP_CHAR_WEIGHT)
                pipe.load_ip_adapter(
                    IP_ADAPTER_REPO,
                    subfolder=IP_ADAPTER_SUBFOLDER,
                    weight_name=IP_CHAR_WEIGHT,
                )
                pipe.set_ip_adapter_scale(IP_SCALE)
                IP_SLOTS = 1
                print("IP-Adapter ready: character only.")
            except Exception as exc:
                IP_SLOTS = 0
                print(f"IP-Adapter load nahi hua ({type(exc).__name__}: {exc})")
                print("Reference images ke bina text-only mode me chalega.")
                print("Tip: pip install -U diffusers transformers accelerate")

    pipe.enable_model_cpu_offload()

    for fn in ("enable_attention_slicing", "enable_vae_slicing", "enable_vae_tiling"):
        try:
            getattr(pipe, fn)()
        except Exception:
            pass

    print("MeinaMix loaded.")
    return pipe


# ============================================================
# GENERATION
# ============================================================

def generate(chapter_json):
    chapter = load_json(chapter_json)

    chapter_id = clean_text(chapter.get("chapter_id", "CHAPTER"))
    chapter_title = clean_text(chapter.get("chapter_title", ""))

    output_dir = OUTPUT_ROOT / safe_name(chapter_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    visual_map = build_memory_visuals(chapter.get("memory", {}))
    panels = flatten_panels(chapter)
    if not panels:
        raise ValueError("Chapter me koi panel nahi mila.")

    pipe = load_pipeline()
    neg_final = build_negative(pipe)

    print()
    print("Chapter:", chapter_title)
    print("Panels:", len(panels))
    print("Size:", f"{WIDTH}x{HEIGHT}", "| Steps:", STEPS, "| CFG:", CFG)
    print("IP-Adapter slots:", IP_SLOTS, "(0=off, 1=character, 2=character+location)")
    print("Scales: character", IP_SCALE, "| location", LOC_SCALE)
    print("Refs folder:", REF_DIR)
    print("Output:", output_dir)
    print()

    log = []

    for order, panel in enumerate(panels, 1):
        panel_id = clean_text(panel.get("panel_id")) or f"PANEL_{order:03d}"
        title = clean_text(panel.get("_scene_title"))
        scene_id = clean_text(panel.get("_scene_id"))
        scene_type = clean_text(panel.get("_scene_type", "PRESENT"))

        prompt, dropped = build_prompt(pipe, panel, visual_map)

        refs = panel.get("refs", [])
        if not isinstance(refs, list):
            refs = []
        ref_name = clean_text(refs[0]) if refs else ""
        loc_name = clean_text(panel.get("loc_ref"))

        log.append({
            "order": order,
            "panel_id": panel_id,
            "scene_id": scene_id,
            "scene_title": title,
            "scene_type": scene_type,
            "ref": ref_name,
            "loc_ref": loc_name,
            "prompt": prompt,
            "dropped_prompt_tags": dropped,
            "voice_text": panel_voice_text(panel),
        })

        for variant in range(NUM_VARIANTS):
            suffix = "" if NUM_VARIANTS == 1 else f"_v{variant + 1}"
            path = output_dir / f"{order:03d}_{safe_name(panel_id)}{suffix}.png"

            if RESUME and path.is_file():
                print(f"[{order:03d}/{len(panels)}] SKIP {panel_id} -> already exists")
                continue

            seed = BASE_SEED + order * 100 + variant
            print(f"[{order:03d}/{len(panels)}] {panel_id} | {scene_type} | char: {ref_name or '-'} | loc: {loc_name or '-'} | seed {seed}")
            print("   scene:", title)
            if dropped:
                print("   trimmed:", ", ".join(dropped))

            call_kwargs = {}
            if IP_SLOTS >= 1:
                char_img = load_ref(ref_name) if ref_name else None
                char_scale = float(panel.get("ref_scale", IP_SCALE)) if char_img is not None else 0.0
                if char_img is None:
                    char_img = DUMMY_IMAGE

                if IP_SLOTS == 2:
                    loc_img = load_ref(loc_name) if loc_name else None
                    loc_scale = float(panel.get("loc_scale", LOC_SCALE)) if loc_img is not None else 0.0
                    if loc_img is None:
                        loc_img = DUMMY_IMAGE
                    pipe.set_ip_adapter_scale([char_scale, loc_scale])
                    call_kwargs["ip_adapter_image"] = [char_img, loc_img]
                else:
                    pipe.set_ip_adapter_scale(char_scale)
                    call_kwargs["ip_adapter_image"] = char_img

            generator = torch.Generator(device="cuda").manual_seed(seed)

            try:
                torch.cuda.empty_cache()
                with torch.inference_mode():
                    result = pipe(
                        prompt=prompt,
                        negative_prompt=neg_final,
                        width=WIDTH,
                        height=HEIGHT,
                        num_inference_steps=STEPS,
                        guidance_scale=CFG,
                        clip_skip=CLIP_SKIP,
                        generator=generator,
                        **call_kwargs,
                    )

                image = result.images[0]
                image.save(path)
                print("   saved:", path)
                del image
                del result

            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache()
                print(
                    "\nCUDA OUT OF MEMORY.\n"
                    "Try WIDTH, HEIGHT = 640, 360, STEPS = 20-24,\n"
                    "ya USE_LOCATION_REFS = False (kam VRAM).\n"
                )
                raise

            except Exception as exc:
                print(f"   FAILED: {type(exc).__name__}: {exc}")

            finally:
                torch.cuda.empty_cache()

    log_path = output_dir / "prompts_log.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "chapter_id": chapter_id,
                "chapter_title": chapter_title,
                "format": chapter.get("format", "16:9"),
                "total_panels": len(panels),
                "panels": log,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    generated = 0
    for order, panel in enumerate(panels, 1):
        panel_id = clean_text(panel.get("panel_id")) or f"PANEL_{order:03d}"
        suffix = "" if NUM_VARIANTS == 1 else "_v1"
        if (output_dir / f"{order:03d}_{safe_name(panel_id)}{suffix}.png").is_file():
            generated += 1

    print()
    print("=" * 70)
    print("DONE")
    print(f"Generated: {generated}/{len(panels)}")
    print("Output:", output_dir)
    print("Log:", log_path)
    print("=" * 70)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate one image for every panel in chapter JSON.")
    parser.add_argument("json_file", nargs="?", default=str(DEFAULT_JSON), help="Chapter JSON file path.")
    args = parser.parse_args()

    json_path = Path(args.json_file)
    if not json_path.is_file():
        raise FileNotFoundError(
            f"Chapter JSON nahi mila: {json_path}\n\n"
            "Example:\npython generate_from_chapter.py chapter_v2.json"
        )

    generate(json_path)