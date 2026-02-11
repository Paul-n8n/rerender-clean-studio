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

def load_font_regular(size: int) -> ImageFont.FreeTypeFont:
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            pass
    return ImageFont.load_default()

def load_font_bold(size: int) -> ImageFont.FreeTypeFont:
    for path in [
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

def draw_text_align_left(draw, bx, by, brand_text, brand_font, (20, 20, 20, 255))
    # compensates for glyph left-bearing so visual left edges align
    bbox = draw.textbbox((0, 0), text, font=font)
    left_bearing = bbox[0]
    draw.text((x - left_bearing, y), text, font=font, fill=fill)


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
    chip3: str = Query("RS1000-6000"),
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

    # LOCKED bottom stack layout
    BOTTOM_SAFE = 56          # bottom padding
    CHIP_TOP_GAP = 26         # gap from hero bottom to first chip
    CHIP_GAP_Y = 18           # gap between chip1 and chip2
    CTA_GAP_Y = 22            # gap from last chip to CTA


    # keep header on the LEFT so it never fights with the hero
    header_left = pad
    header_top = top_pad
    header_right = int(W * 0.78)   # header content width limit (tweak 0.68~0.78)
    header_max_w = header_right - header_left

    # hero area starts below header
    hero_box = (0, header_h, W, H)

    # 4) Brand (small, like "PIONEER") — REGULAR font
    brand_text = (brand or "").strip().upper()
    brand_font = fit_text(draw, brand_text, max_w=header_max_w, start_size=72, min_size=34)

    bx = header_left
    by = header_top

    # Optical alignment nudge (fixes "protruding" look)
    brand_x_nudge = 2
    draw.text((bx + brand_x_nudge, by), brand_text, font=brand_font, fill=(20, 20, 20, 255))
    brand_h = text_size(draw, brand_text, brand_font)[1]

    # 4b) Model (HUGE) — BOLD font
    model_text = (model or "").strip().upper()
    model_font = fit_text(draw, model_text, max_w=header_max_w, start_size=240, min_size=140)

    model_y = by + brand_h - 10
    draw.text((bx, model_y), model_text, font=model_font, fill=(20, 20, 20, 255))
    model_h = text_size(draw, model_text, model_font)[1]

    # 5) Top-right size badge (chip3)
    size_text = (chip3 or "").strip()
    if size_text:
        badge_font = load_font_bold(44)
        pad_x, pad_y = 26, 14

        tw, th = text_size(draw, size_text, badge_font)
        bw, bh = tw + pad_x * 2, th + pad_y * 2

        bx1 = W - pad
        by0 = top_pad + 18
        bx0 = bx1 - bw
        by1 = by0 + bh

        draw_rounded_rect(draw, (bx0, by0, bx1, by1), radius=18, fill=(245, 204, 74, 255))
        draw.rounded_rectangle((bx0, by0, bx1, by1), radius=18, outline=(20, 20, 20, 255), width=4)

        # center text inside badge
        bbox = draw.textbbox((0, 0), size_text, font=badge_font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        tx = bx0 + (bw - text_w) // 2
        ty = by0 + (bh - text_h) // 2 - 1
        draw.text((tx, ty), size_text, font=badge_font, fill=(20, 20, 20, 255))

    # 6) Hero (LOCKED) — RASCAL-scale geometry
    hero_w, hero_h = hero.size

    # LOCK: hero height ≈ 54% of canvas height (RASCAL-like 52–56%)
    TARGET_H_RATIO = 0.54
    target_h = int(H * TARGET_H_RATIO)
    scale = target_h / hero_h

    new_w = max(1, int(hero_w * scale))
    new_h = max(1, int(hero_h * scale))
    hero_rs = hero.resize((new_w, new_h), resample=Image.LANCZOS)

    # LOCK: right-aligned, hero top ≈ 28% of canvas (RASCAL-like)
    px = W - new_w
    py = int(H * 0.24)

    # Safety: never overlap header
    py = max(py, header_h)

    canvas.alpha_composite(hero_rs, (px, py))

    hero_left = px
    hero_top = py
    hero_right = px + new_w
    hero_bottom = py + new_h


    # 7) Chips (LOCKED) — always below hero
    features = [(chip1 or "").strip(), (chip2 or "").strip()]
    features = [c for c in features if c]

    chip_font = load_font(46)
    chip_pad_x = 22
    chip_pad_y = 14
    chip_radius = 18

    chip_x = pad
    chip_y = hero_bottom + CHIP_TOP_GAP  # locked start under hero

    chips_bottom = chip_y - CHIP_GAP_Y
    for c in features:
        tw, th = text_size(draw, c, chip_font)
        bw = tw + chip_pad_x * 2
        bh = th + chip_pad_y * 2

        # keep chips inside canvas
        if chip_y + bh > H - BOTTOM_SAFE:
            break

        draw_rounded_rect(
            draw,
            (chip_x, chip_y, chip_x + bw, chip_y + bh),
            radius=chip_radius,
            fill=(245, 246, 248, 255),
        )

        # vertically center text inside chip
        bbox = draw.textbbox((0, 0), c, font=chip_font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        tx = chip_x + chip_pad_x
        ty = chip_y + (bh - text_h) // 2 - 1

        draw.text((tx, ty), c, font=chip_font, fill=(40, 40, 40, 255))

        chip_y += bh + CHIP_GAP_Y
        chips_bottom = chip_y

    # 8) CTA (LOCKED) — always below chips, never clipped
    cta_text = "READY STOCK • FAST SHIP"
    cta_font = load_font_bold(40)
    cta_pad_x = 24
    cta_pad_y = 10
    cta_radius = 18
    cta_border_w = 4

    tw, th = text_size(draw, cta_text, cta_font)
    cta_w = tw + cta_pad_x * 2
    cta_h = th + cta_pad_y * 2

    # center-ish like RASCAL (slightly right)
    cta_x0 = int(W * 0.52) - cta_w // 2

    # locked position: below chips; clamp to bottom-safe
    cta_y0 = chips_bottom + CTA_GAP_Y
    cta_y0 = min(cta_y0, H - BOTTOM_SAFE - cta_h)

    cta_x1 = cta_x0 + cta_w
    cta_y1 = cta_y0 + cta_h

    draw_rounded_rect(draw, (cta_x0, cta_y0, cta_x1, cta_y1), radius=cta_radius, fill=(245, 204, 74, 255))
    draw.rounded_rectangle((cta_x0, cta_y0, cta_x1, cta_y1), radius=cta_radius, outline=(20, 20, 20, 255), width=cta_border_w)

    # center text inside CTA
    bbox = draw.textbbox((0, 0), cta_text, font=cta_font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    tx = cta_x0 + (cta_w - text_w) // 2
    ty = cta_y0 + (cta_h - text_h) // 2 - 1
    draw.text((tx, ty), cta_text, font=cta_font, fill=(20, 20, 20, 255))

    # 9) Output PNG
    out = BytesIO()
    canvas.convert("RGBA").save(out, format="PNG")
    return Response(content=out.getvalue(), media_type="image/png")

