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

def draw_text_align_left(draw, x, y, text, font, fill):
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
    Shopee P1 (1000x1000) compositor — RASCAL style v2.
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
    draw.text((10, 960), "P1 v2026-02-09B", font=load_font(24), fill=(255, 0, 0, 255))

    # 3) Layout constants
    pad = 56
    top_pad = 44
    header_h = 240  # UPDATED: was 260

    # LOCKED bottom stack layout
    BOTTOM_SAFE = 56
    CHIP_TOP_GAP = 20   # UPDATED: was 26
    CHIP_GAP_Y = 16     # UPDATED: was 18
    CTA_GAP_Y = 20      # UPDATED: was 22

    # Header zone
    header_left = pad
    header_top = top_pad
    header_right = int(W * 0.58)  # UPDATED: was 0.78, narrower to not overlap badge
    header_max_w = header_right - header_left

    # 4) Brand (small) — REGULAR font
    brand_text = (brand or "").strip().upper()
    brand_font = fit_text(draw, brand_text, max_w=header_max_w, start_size=56, min_size=34)

    bx = header_left
    by = header_top
    brand_x_nudge = 2

    draw_text_align_left(
        draw,
        bx + brand_x_nudge,
        by,
        brand_text,
        brand_font,
        (20, 20, 20, 255),
    )
    brand_h = text_size(draw, brand_text, brand_font)[1]

    # 5) Model (HUGE) — BOLD font
    model_text = (model or "").strip().upper()
    model_font = fit_text(draw, model_text, max_w=header_max_w, start_size=200, min_size=120)

    model_y = by + brand_h - 6  # UPDATED: tighter gap

    draw_text_align_left(
        draw,
        bx,
        model_y,
        model_text,
        model_font,
        (20, 20, 20, 255),
    )
    model_h = text_size(draw, model_text, model_font)[1]

    # 6) Top-right size badge (chip3) — YELLOW FILL style
    size_text = (chip3 or "").strip()
    if size_text:
        badge_font = load_font_bold(38)  # UPDATED: was 44
        pad_x, pad_y = 22, 12  # UPDATED: was 26, 14

        tw, th = text_size(draw, size_text, badge_font)
        bw, bh = tw + pad_x * 2, th + pad_y * 2

        bx1 = W - pad
        by0 = top_pad + 12  # UPDATED: was 18
        bx0 = bx1 - bw
        by1 = by0 + bh

        # Yellow fill, black border (RASCAL style)
        draw_rounded_rect(draw, (bx0, by0, bx1, by1), radius=14, fill=(245, 204, 74, 255))
        draw.rounded_rectangle((bx0, by0, bx1, by1), radius=14, outline=(20, 20, 20, 255), width=3)

        # Center text inside badge
        bbox = draw.textbbox((0, 0), size_text, font=badge_font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        tx = bx0 + (bw - text_w) // 2
        ty = by0 + (bh - text_h) // 2 - 1
        draw.text((tx, ty), size_text, font=badge_font, fill=(20, 20, 20, 255))

    # 7) Hero — RASCAL-scale geometry (UPDATED)
    hero_w, hero_h = hero.size

    # UPDATED: hero height ≈ 60% of canvas (was 54%)
    TARGET_H_RATIO = 0.58
    target_h = int(H * TARGET_H_RATIO)
    scale = target_h / hero_h

    new_w = max(1, int(hero_w * scale))
    new_h = max(1, int(hero_h * scale))
    hero_rs = hero.resize((new_w, new_h), resample=Image.LANCZOS)

    # UPDATED: right-aligned with padding, hero top ~22%
    RIGHT_PAD = 16
    px = W - new_w - RIGHT_PAD
    py = int(H * 0.22)  # UPDATED: was 0.24

    # Safety: never overlap header
    py = max(py, header_h)

    canvas.alpha_composite(hero_rs, (px, py))

    hero_left = px
    hero_top = py
    hero_right = px + new_w
    hero_bottom = py + new_h

    # 8) Chips — always below hero, LEFT side
    features = [(chip1 or "").strip(), (chip2 or "").strip()]
    features = [c for c in features if c]

    chip_font = load_font_bold(40)  # UPDATED: was 46, use bold
    chip_pad_x = 20
    chip_pad_y = 12
    chip_radius = 14  # UPDATED: was 18

    chip_x = pad
    chip_y = hero_bottom + CHIP_TOP_GAP

    chips_bottom = chip_y  # Initialize
    
    for c in features:
        tw, th = text_size(draw, c, chip_font)
        bw = tw + chip_pad_x * 2
        bh = th + chip_pad_y * 2

        # Safety: keep chips inside canvas
        if chip_y + bh > H - BOTTOM_SAFE - 60:  # Reserve space for CTA
            break

        # White/light grey fill, subtle border
        draw_rounded_rect(
            draw,
            (chip_x, chip_y, chip_x + bw, chip_y + bh),
            radius=chip_radius,
            fill=(255, 255, 255, 245),  # UPDATED: pure white
        )
        draw.rounded_rectangle(
            (chip_x, chip_y, chip_x + bw, chip_y + bh),
            radius=chip_radius,
            outline=(60, 60, 60, 255),
            width=2
        )

        # Center text vertically inside chip
        bbox = draw.textbbox((0, 0), c, font=chip_font)
        text_h = bbox[3] - bbox[1]
        tx = chip_x + chip_pad_x
        ty = chip_y + (bh - text_h) // 2 - 1

        draw.text((tx, ty), c, font=chip_font, fill=(30, 30, 30, 255))

        chips_bottom = chip_y + bh
        chip_y += bh + CHIP_GAP_Y

    # 9) CTA — below chips, centered
    cta_text = "READY STOCK • FAST SHIP"
    cta_font = load_font_bold(36)  # UPDATED: was 40
    cta_pad_x = 22
    cta_pad_y = 10
    cta_radius = 14  # UPDATED: was 18
    cta_border_w = 3  # UPDATED: was 4

    tw, th = text_size(draw, cta_text, cta_font)
    cta_w = tw + cta_pad_x * 2
    cta_h = th + cta_pad_y * 2

    # Center horizontally (slightly right like RASCAL)
    cta_x0 = int(W * 0.50) - cta_w // 2  # UPDATED: was 0.52

    # Position: below chips, clamp to bottom-safe
    cta_y0 = chips_bottom + CTA_GAP_Y
    cta_y0 = min(cta_y0, H - BOTTOM_SAFE - cta_h)

    cta_x1 = cta_x0 + cta_w
    cta_y1 = cta_y0 + cta_h

    # Yellow fill, black border (RASCAL style)
    draw_rounded_rect(draw, (cta_x0, cta_y0, cta_x1, cta_y1), radius=cta_radius, fill=(245, 204, 74, 255))
    draw.rounded_rectangle((cta_x0, cta_y0, cta_x1, cta_y1), radius=cta_radius, outline=(20, 20, 20, 255), width=cta_border_w)

    # Center text inside CTA
    bbox = draw.textbbox((0, 0), cta_text, font=cta_font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    tx = cta_x0 + (cta_w - text_w) // 2
    ty = cta_y0 + (cta_h - text_h) // 2 - 1
    draw.text((tx, ty), cta_text, font=cta_font, fill=(20, 20, 20, 255))

    # 10) Output PNG
    out = BytesIO()
    canvas.convert("RGBA").save(out, format="PNG")
    return Response(content=out.getvalue(), media_type="image/png")

