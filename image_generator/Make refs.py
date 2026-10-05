# ============================================================
# make_refs.py   ->   python make_refs.py
#
# Har character ke 4 candidate portraits banata hai:
#   refs_candidates/rudransh_1.png ... rudransh_4.png
#   refs_candidates/rudransh_past_1.png ...
#   refs_candidates/chhoti_bua_1.png ...
#   refs_candidates/chandrika_1.png ...
#
# Phir har character ki SABSE ACHHI image ko `refs/` folder me
# copy karke ye naam do:
#   refs/rudransh.png
#   refs/rudransh_past.png
#   refs/chhoti_bua.png
#   refs/chandrika.png
#   refs/rudrasen.png
#   refs/someshwar.png
#   refs/rudransh_child.png  refs/rudransh_plain.png  refs/maid.png  refs/jealous_youth.png
# Locations:
#   refs/wedding_room.png  refs/mansion_courtyard.png  refs/city_meghnagar.png
#   refs/green_world.png   refs/neelmegh_cliff.png
# ============================================================

from pathlib import Path
import torch
from diffusers import StableDiffusionPipeline, DPMSolverMultistepScheduler

BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "models" / "meinamix_meinaV11.safetensors"
OUT = BASE_DIR / "refs_candidates"
OUT.mkdir(exist_ok=True)

STEPS = 45 
CFG = 7.0
SIZE = 512
VARIANTS = 4

QUALITY = "masterpiece, best quality, anime screencap, upper body, front view, looking at viewer, simple light grey background, soft lighting"
NEGATIVE = ("worst quality, low quality, lowres, blurry, bad anatomy, bad hands, deformed face, "
            "multiple people, text, watermark, 3d, chibi, modern clothes, photorealistic")

CHARACTERS = {
    "rudransh":      "1boy, teenager, short black hair, black eyes, red wedding robe with gold trim, calm expression",
    "rudransh_past": "1boy, young man, black hair, black eyes, torn black robe, sharp serious eyes",
    "chhoti_bua":    "1girl, teenage girl, long black hair, silver hairpin, light blue hanfu, gentle smile, snow white skin",
    "chandrika":     "1girl, beautiful girl, long straight black hair, snow white skin, white and pink hanfu, gold hair ornament, elegant calm expression",
    "rudrasen":      "1boy, elderly man, white hair, grey beard, dark red robe, stern powerful expression",
    "someshwar":     "1boy, old physician, white beard, green robe, kind wise expression",
    "rudransh_child": "1boy, child, 8 years old, short black hair, black eyes, plain white training robe, determined expression",
    "rudransh_plain": "1boy, teenager, short black hair, black eyes, plain white training robe with grey sash, calm expression",
    "maid":          "1girl, young maid, black hair in buns, simple pink hanfu, gentle expression",
    "jealous_youth": "1boy, young man, black hair tied up, blue robe with silver trim, jealous angry glare",
}

# Locations (no people) - landscape size
LOC_W, LOC_H = 768, 432
LOC_QUALITY = "masterpiece, best quality, anime screencap, scenery, no humans, detailed background"
LOCATIONS = {
    "wedding_room":      "ancient chinese bedroom interior, wooden canopy bed with silk blankets, huge red wedding banner hanging from ceiling, red lanterns, wooden furniture, paper window, dawn light",
    "mansion_courtyard": "ancient chinese clan mansion courtyard, red and gold tiled roofs, stone floor, wooden pillars, flame banners, dawn mist",
    "city_meghnagar":    "ancient chinese city street, wooden shopfronts, curved tiled roofs, stone road, city wall, far mountains, daylight",
    "green_world":       "vast boundless jade-green world, glowing green mist, endless meadow, floating green light particles, no horizon, ethereal",
    "neelmegh_cliff":    "misty bottomless chasm, cliff edge, blue clouds, floating mountains, stormy sky, epic fantasy landscape",
}

pipe = StableDiffusionPipeline.from_single_file(
    str(MODEL_PATH), torch_dtype=torch.float16, use_safetensors=True, safety_checker=None
)
pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, use_karras_sigmas=True)
pipe.enable_model_cpu_offload()
pipe.enable_attention_slicing()

for name, tags in CHARACTERS.items():
    for i in range(1, VARIANTS + 1):
        path = OUT / f"{name}_{i}.png"
        if path.is_file():
            continue
        g = torch.Generator(device="cuda").manual_seed(777 + i * 31)
        with torch.inference_mode():
            img = pipe(
                prompt=f"{QUALITY}, {tags}",
                negative_prompt=NEGATIVE,
                width=SIZE, height=SIZE,
                num_inference_steps=STEPS, guidance_scale=CFG,
                generator=g,
            ).images[0]
        img.save(path)
        print("saved", path)
        torch.cuda.empty_cache()

for name, tags in LOCATIONS.items():
    for i in range(1, VARIANTS + 1):
        path = OUT / f"{name}_{i}.png"
        if path.is_file():
            continue
        g = torch.Generator(device="cuda").manual_seed(1777 + i * 31)
        with torch.inference_mode():
            img = pipe(
                prompt=f"{LOC_QUALITY}, {tags}",
                negative_prompt="worst quality, low quality, lowres, blurry, people, person, text, watermark, 3d, photorealistic",
                width=LOC_W, height=LOC_H,
                num_inference_steps=STEPS, guidance_scale=CFG,
                generator=g,
            ).images[0]
        img.save(path)
        print("saved", path)
        torch.cuda.empty_cache()

print("\nDone. Best image ko refs/<name>.png naam se copy karo.")