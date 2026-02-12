import os
from io import BytesIO
from typing import List, Optional

import boto3
from botocore.config import Config
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from PIL import Image, ImageDraw, ImageFont

app = FastAPI()


@app.get("/")
def root():
    return {"ok": True, "service": "rerender-clean-studio"}


VERSION = "P1 v2026-02-12I"

# ---------- R2 client ----------
def r2_client():
    endpoint = os.environ.get("R2_ENDPOINT")
    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")

    if not endpoint or not access_key or not secret_key:
        raise HTTPException(status_code=500, detail="Missing R2 env vars")

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
def load_font_regular(size: int) -> ImageFont.FreeTypeFont:
    for path in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def load_font_bold(size: int) -> ImageFont.FreeTypeFont:
    for path in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def fit_text(draw, text, max_w, start_size, min_size=16, loader=load_font_regular):
    size = start_size
    while size >= min_size:
        font = loader(size)
        w, _ = text_size(draw, text, font)
        if w <= max_w:
            return font
        size -= 2
    return loader(min_size)


# ---------- Drawing helpers ----------
def draw_rounded_rect(draw: ImageDraw.ImageDraw, xy, radius: int, fill):
    try:
        draw.rounded_rectangle(xy, radius=radius, fill=fill)
    except Exception:
        draw.rectangle(xy, fill=fill)


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont):
    bbox = draw.textbbox((0, 0), text, font=font)
    return (bbox[2] - bbox[0], bbox[3] - bbox[1])


def draw_text_align_left(draw, x, y, text, font, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    left_bearing = bbox[0]
    draw.text((x - left_bearing, y), text, font=font, fill=fill)


def draw_text_centered_in_box(draw, box_x0, box_y0, box_w, box_h, text, font, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    tx = box_x0 + (box_w - text_w) // 2 - bbox[0]
    ty = box_y0 + (box_h - text_h) // 2 - bbox[1]
    draw.text((tx, ty), text, font=font, fill=fill)


def trim_transparent(im: Image.Image, pad: int = 0) -> Image.Image:
    if im.mode != "RGBA":
        im = im.convert("RGBA")

    alpha = im.split()[-1]
    bbox = alpha.getbbox()
    if not bbox:
        return im

    x0, y0, x1, y1 = bbox
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(im.width, x1 + pad)
    y1 = min(im.height, y1 + pad)
    return im.crop((x0, y0, x1, y1))


# ---------- Icon loading ----------
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets", "p1")
BG_DIR = os.path.join(ASSETS_DIR, "backgrounds")
ICONS_DIR = os.path.join(ASSETS_DIR, "icons")


def load_icon(filename: str, target_h: int) -> Optional[Image.Image]:
    """Load a PNG icon from assets/p1/icons/ and scale to target height."""
    path = os.path.join(ICONS_DIR, filename)
    if not os.path.exists(path):
        return None
    try:
        icon = Image.open(path).convert("RGBA")
        ratio = target_h / icon.height
        new_w = max(1, int(icon.width * ratio))
        icon = icon.resize((new_w, target_h), Image.LANCZOS)
        return icon
    except Exception:
        return None


CHIP_ICONS = {
    0: "bearings_1.png",
    1: "Gear_Ratio_1.png",
}


# ---------- Routes ----------
@app.get("/health")
def health():
    return {"ok": True, "version": VERSION}


@app.get("/r2/get-image")
def get_image(key: str):
    data = r2_get_object_bytes(key)
    try:
        hero = Image.open(BytesIO(data)).convert("RGBA")
        hero = trim_transparent(hero, pad=0)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Not a valid image: {e}")

    out = BytesIO()
    hero.save(out, format="PNG")
    return Response(content=out.getvalue(), media_type="image/png")


def load_bg(theme: str):
    t = (theme or "yellow").lower()
    path = os.path.join(BG_DIR, f"{t}.png")
    if not os.path.exists(path):
        path = os.path.join(BG_DIR, "yellow.png")
    return Image.open(path).convert("RGBA")


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

    # 3) Layout constants
    pad = 56
    top_pad = 44
    BOTTOM_SAFE = 28

    CHIP_TOP_GAP = 16
    CHIP_GAP_X = 50         # wide gap between chip groups
    CTA_GAP_Y = 20
    ICON_TEXT_GAP = 14       # gap between icon and text
    ICON_H = 60              # icon height — thumb-safe at Shopee grid

    header_left = pad
    header_top = top_pad
    header_max_w = int(W * 0.55) - header_left

    # 4) BRAND text
    brand_text = (brand or "").strip().upper()
    brand_font = fit_text(draw, brand_text, max_w=header_max_w,
                          start_size=56, min_size=34, loader=load_font_regular)
    brand_h = text_size(draw, brand_text, brand_font)[1]

    # 5) MODEL text
    model_text = (model or "").strip().upper()
    model_font = fit_text(draw, model_text, max_w=header_max_w,
                          start_size=200, min_size=100, loader=load_font_bold)
    model_y = header_top + brand_h - 6

    # 6) Pre-compute chip & CTA sizes
    features = [(chip1 or "").strip(), (chip2 or "").strip()]
    features = [c for c in features if c]

    chip_font = load_font_bold(36)       # bigger for thumb readability

    cta_text = "READY STOCK \u2022 FAST SHIP"
    cta_font = load_font_bold(18)
    cta_pad_x = 14
    cta_pad_y = 6
    cta_radius = 8
    cta_border_w = 2

    cta_tw, cta_th = text_size(draw, cta_text, cta_font)
    cta_w = cta_tw + cta_pad_x * 2
    cta_h = cta_th + cta_pad_y * 2

    # Load icons and measure chip groups
    chip_groups = []
    for i, c in enumerate(features):
        tw, th = text_size(draw, c, chip_font)
        icon_file = CHIP_ICONS.get(i)
        icon = load_icon(icon_file, ICON_H) if icon_file else None
        icon_w = icon.width if icon else 0

        if icon:
            group_w = icon_w + ICON_TEXT_GAP + tw
        else:
            group_w = tw

        group_h = max(ICON_H, th)
        chip_groups.append((c, tw, th, group_w, group_h, icon, icon_w))

    chip_row_h = max((gh for _, _, _, _, gh, _, _ in chip_groups), default=0)

    total_chips_w = 0
    if chip_groups:
        total_chips_w = sum(gw for _, _, _, gw, _, _, _ in chip_groups)
        total_chips_w += CHIP_GAP_X * (len(chip_groups) - 1)

    needed_below = CHIP_TOP_GAP + chip_row_h + CTA_GAP_Y + cta_h + BOTTOM_SAFE

    # 7) HERO — ~62% height
    hero_w, hero_h = hero.size

    TARGET_H_RATIO = 0.62
    target_h = int(H * TARGET_H_RATIO)
    scale = target_h / hero_h

    new_w = max(1, int(hero_w * scale))
    new_h = max(1, int(hero_h * scale))
    hero_rs = hero.resize((new_w, new_h), resample=Image.LANCZOS)

    px = (W - new_w) // 2 + 100
    px = max(px, pad)
    px = min(px, W - new_w - 10)

    py = int(H * 0.22)

    max_hero_bottom = H - needed_below
    if py + new_h > max_hero_bottom:
        py = max_hero_bottom - new_h
        py = max(py, top_pad + 20)

    hero_bottom = py + new_h

    # DRAW ORDER: text first, then hero on top

    draw_text_align_left(draw, header_left + 2, header_top,
                         brand_text, brand_font, (20, 20, 20, 255))

    draw_text_align_left(draw, header_left, model_y,
                         model_text, model_font, (20, 20, 20, 255))

    # Size badge (chip3)
    size_text = (chip3 or "").strip()
    if size_text:
        badge_font = load_font_bold(38)
        bpx, bpy = 22, 12

        tw, th = text_size(draw, size_text, badge_font)
        bw, bh = tw + bpx * 2, th + bpy * 2

        bx1 = W - pad
        by0 = top_pad + 12
        bx0 = bx1 - bw
        by1 = by0 + bh

        draw_rounded_rect(draw, (bx0, by0, bx1, by1), radius=14,
                          fill=(245, 204, 74, 255))
        draw.rounded_rectangle((bx0, by0, bx1, by1), radius=14,
                               outline=(20, 20, 20, 255), width=3)
        draw_text_centered_in_box(draw, bx0, by0, bw, bh,
                                  size_text, badge_font, (20, 20, 20, 255))

    # Composite hero ON TOP of text
    canvas.alpha_composite(hero_rs, (px, py))
    draw = ImageDraw.Draw(canvas)

    # 8) CHIPS — icon + text, centered row
    chip_y_top = hero_bottom + CHIP_TOP_GAP
    chip_y_center = chip_y_top + chip_row_h // 2
    chip_start_x = (W - total_chips_w) // 2

    cur_x = chip_start_x
    for c, tw, th, gw, gh, icon, icon_w in chip_groups:
        if icon:
            icon_y = chip_y_center - icon.height // 2
            canvas.alpha_composite(icon, (cur_x, icon_y))
            draw = ImageDraw.Draw(canvas)

            text_x = cur_x + icon_w + ICON_TEXT_GAP
        else:
            text_x = cur_x

        bbox = draw.textbbox((0, 0), c, font=chip_font)
        text_h = bbox[3] - bbox[1]
        text_y = chip_y_center - text_h // 2 - bbox[1]
        draw.text((text_x, text_y), c, font=chip_font, fill=(30, 30, 30, 255))

        cur_x += gw + CHIP_GAP_X

    chips_bottom = chip_y_top + chip_row_h

    # 9) CTA — below chips, centered
    cta_x0 = (W - cta_w) // 2
    cta_y0 = chips_bottom + CTA_GAP_Y
    cta_y0 = min(cta_y0, H - BOTTOM_SAFE - cta_h)

    cta_x1 = cta_x0 + cta_w
    cta_y1 = cta_y0 + cta_h

    draw_rounded_rect(draw, (cta_x0, cta_y0, cta_x1, cta_y1),
                      radius=cta_radius, fill=(245, 204, 74, 255))
    draw.rounded_rectangle((cta_x0, cta_y0, cta_x1, cta_y1),
                           radius=cta_radius, outline=(20, 20, 20, 255),
                           width=cta_border_w)
    draw_text_centered_in_box(draw, cta_x0, cta_y0, cta_w, cta_h,
                              cta_text, cta_font, (20, 20, 20, 255))

    # 10) Output PNG
    out = BytesIO()
    canvas.convert("RGBA").save(out, format="PNG")
    return Response(content=out.getvalue(), media_type="image/png")
