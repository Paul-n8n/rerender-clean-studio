import os
from io import BytesIO
from typing import List, Optional

import boto3
from botocore.config import Config
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from PIL import Image, ImageDraw, ImageFont

app = FastAPI()

VERSION = "P1 v2026-02-09A"


# ---------- R2 client ----------
def r2_client():
    endpoint = os.environ.get("R2_ENDPOINT")
    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")

    if not endpoint or not access_key or not secret_key:
        raise HTTPException(status_code=500, detail="Missing R2 env vars")

    # IMPORTANT: endpoint must include scheme: https://
    if not endpoint.startswith("http://") and not endpoint.startswith("https://"):
        endpoint = "https://" + endpoint

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def r2_get_object_bytes(key: str) -> bytes:
    bucket = os.environ.get("R2_BUCKET")
    if not bucket:
        raise HTTPException(status_code=500, detail="Missing R2_BUCKET")

    s3 = r2_client()
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"R2 get_object failed: {e}")


# ---------- Fonts ----------
def load_font(size: int) -> ImageFont.FreeTypeFont:
    # Render images usually have DejaVu fonts available
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


# ---------- Drawing helpers ----------
def draw_rounded_rect(draw: ImageDraw.ImageDraw, xy, radius: int, fill):
    # Pillow supports rounded_rectangle on newer versions
    try:
        draw.rounded_rectangle(xy, radius=radius, fill=fill)
    except Exception:
        # fallback: normal rectangle
        draw.rectangle(xy, fill=fill)


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont):
    bbox = draw.textbbox((0, 0), text, font=font)
    return (bbox[2] - bbox[0], bbox[3] - bbox[1])


def fit_text(draw: ImageDraw.ImageDraw, text: str, max_w: int, start_size: int, min_size: int = 16):
    size = start_size
    while size >= min_size:
        font = load_font(size)
        w, _ = text_size(draw, text, font)
        if w <= max_w:
            return font
        size -= 2
    return load_font(min_size)


# ---------- Routes ----------
@app.get("/health")
def health():
    return {"ok": True, "version": VERSION}


@app.get("/r2/get-image")
def get_image(key: str):
    """
    Fetch an image from R2 and return it as PNG (for testing).
    Example key: raw/TEST-001/original.png
    """
    data = r2_get_object_bytes(key)
    try:
        hero = Image.open(BytesIO(data)).convert("RGBA")
        hero = trim_transparent(hero, pad=0)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Not a valid image: {e}")

    out = BytesIO()
    hero.save(out, format="PNG")
    return Response(content=out.getvalue(), media_type="image/png")


ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets", "p1")
BG_DIR = os.path.join(ASSETS_DIR, "backgrounds")

def load_bg(theme: str):
    t = (theme or "yellow").lower()
    path = os.path.join(BG_DIR, f"{t}.png")
    if not os.path.exists(path):
        path = os.path.join(BG_DIR, "yellow.png")
    return Image.open(path).convert("RGBA")

def trim_transparent(im: Image.Image, pad: int = 0) -> Image.Image:
    if im.mode != "RGBA":
        im = im.convert("RGBA")

    alpha = im.split()[-1]          # alpha channel
    bbox = alpha.getbbox()          # bbox where alpha > 0
    if not bbox:
        return im

    x0, y0, x1, y1 = bbox
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(im.width, x1 + pad)
    y1 = min(im.height, y1 + pad)
    return im.crop((x0, y0, x1, y1))

@app.get("/render/p1")
def render_p1(
    key: str = Query(..., description="R2 object key, e.g. raw/TEST-001/original.png"),
    brand: str = Query("Daiwa"),
    model: str = Query("RS"),
    chip1: str = Query("3BB"),
    chip2: str = Query("5.1:1"),
    chip3: str = Query("Max Drag 8kg"),
    theme: str = Query("yellow"),
):
    """
    Shopee P1 (1000x1000) compositor.
    """
    # 1) Load hero image from R2
    data = r2_get_object_bytes(key)
    try:
        hero = Image.open(BytesIO(data)).convert("RGBA")
        hero = trim_transparent(hero, pad=6)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Not a valid image: {e}")

    # 2) Create canvas
    W, H = 1000, 1000
    canvas = load_bg(theme).resize((W, H), Image.LANCZOS)
    draw = ImageDraw.Draw(canvas)

    # DEBUG: version stamp (remove later)
    draw.text((10, 960), "P1 v2026-02-09A", font=load_font(24), fill=(255, 0, 0, 255))

    # 3) Layout constants (Header zone)
    pad = 56
    top_pad = 44
    header_h = 260  # enough room for brand + model + chips (tweak 240~300)

    # keep header on the LEFT so it never fights with the hero
    header_left = pad
    header_top = top_pad
    header_right = int(W * 0.72)   # header content width limit (tweak 0.68~0.78)
    header_max_w = header_right - header_left

    # hero area starts below header
    hero_box = (0, header_h, W, H)

    # 4) Brand (small)
    brand_text = (brand or "").strip()
    brand_font = fit_text(draw, brand_text, max_w=header_max_w, start_size=46, min_size=26)
    bx, by = header_left, header_top
    draw.text((bx, by), brand_text, font=brand_font, fill=(20, 20, 20, 255))
    brand_h = text_size(draw, brand_text, brand_font)[1]

    # 4b) Model (BIG)
    model_text = (model or "").strip()
    model_y = by + brand_h + 6
    model_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=130)
    model_font = fit_text(draw, model_text, max_w=header_max_w, start_size=130, min_size=64)
    draw.text((bx, model_y), model_text, font=model_font, fill=(20, 20, 20, 255))
    model_h = text_size(draw, model_text, model_font)[1]


    # 5) Chips (VERTICAL stack near reel area)
    chips = [chip1, chip2, chip3]
    chip_font = load_font(38)

    chip_gap_y = 18
    chip_pad_x = 18
    chip_pad_y = 12
    chip_radius = 18

    chip_x = pad                 # left margin
    chip_y = int(H * 0.62)       # tweak 0.58~0.72 to match your reference

    for c in chips:
        if not c:
            continue

        tw, th = text_size(draw, c, chip_font)
        bw = tw + chip_pad_x * 2
        bh = th + chip_pad_y * 2

        bx0 = chip_x
        by0 = chip_y
        bx1 = chip_x + bw
        by1 = chip_y + bh

        draw_rounded_rect(draw, (bx0, by0, bx1, by1), radius=chip_radius, fill=(245, 246, 248, 255))
        draw.text((bx0 + chip_pad_x, by0 + chip_pad_y), c, font=chip_font, fill=(40, 40, 40, 255))

        chip_y += bh + chip_gap_y


    # 6) Make hero big + anchor to lower-right
    box_w = hero_box[2] - hero_box[0]
    box_h = hero_box[3] - hero_box[1]

    hero_w, hero_h = hero.size

    # target size: fill ~88% of available height (tweak 0.88 -> 0.92 if you want even bigger)
    target_h = int(box_h * 0.92)
    scale = target_h / hero_h

    new_w = max(1, int(hero_w * scale))
    new_h = max(1, int(hero_h * scale))
    hero_rs = hero.resize((new_w, new_h), resample=Image.LANCZOS)

    # anchor to CANVAS bottom-right (within pad)
    margin_right = 0
    margin_bottom = 0

    px = W - new_w
    py = H - new_h - 10

    # safety: don't go above header
    py = max(py, header_h)

    canvas.alpha_composite(hero_rs, (px, py))

    # 7) Output PNG
    out = BytesIO()
    canvas.convert("RGBA").save(out, format="PNG")
    return Response(content=out.getvalue(), media_type="image/png")

