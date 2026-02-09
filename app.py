import os
from io import BytesIO
from typing import List, Optional

import boto3
from botocore.config import Config
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from PIL import Image, ImageDraw, ImageFont

app = FastAPI()


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
    return {"ok": True}


@app.get("/r2/get-image")
def get_image(key: str):
    """
    Fetch an image from R2 and return it as PNG (for testing).
    Example key: raw/TEST-001/original.png
    """
    data = r2_get_object_bytes(key)
    try:
        hero = Image.open(BytesIO(data)).convert("RGBA")
        hero = trim_transparent(hero, pad=6)
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

def trim_transparent(im: Image.Image, pad: int = 2) -> Image.Image:
    """
    Crops transparent border around an RGBA image.
    pad keeps a tiny margin so it doesn't cut too tight.
    """
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    bbox = im.getbbox()  # bbox of non-zero pixels (includes alpha)
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

    # 3) Layout constants
    pad = 56
    header_h = 220  # top area reserved for brand/model + chips
    hero_box = (pad, header_h, W - pad, H - pad)

    # 4) Brand + Model text
    title = f"{brand} {model}".strip()
    title_font = fit_text(draw, title, max_w=W - pad * 2, start_size=72, min_size=34)

    tx, ty = pad, 40
    draw.text((tx, ty), title, font=title_font, fill=(20, 20, 20, 255))

    # 5) Chips row
    chips: List[str] = [chip1, chip2, chip3]
    chip_font = load_font(34)
    chip_y = ty + text_size(draw, title, title_font)[1] + 22
    chip_gap = 14
    chip_x = pad

    for c in chips:
        if not c:
            continue
        tw, th = text_size(draw, c, chip_font)
        bx0 = chip_x
        by0 = chip_y
        bx1 = chip_x + tw + 26
        by1 = chip_y + th + 16

        # light gray chip
        draw_rounded_rect(draw, (bx0, by0, bx1, by1), radius=18, fill=(245, 246, 248, 255))
        # chip text
        draw.text((bx0 + 13, by0 + 8), c, font=chip_font, fill=(40, 40, 40, 255))

        chip_x = bx1 + chip_gap

    # 6) Make hero big + anchor to lower-right
    box_w = hero_box[2] - hero_box[0]
    box_h = hero_box[3] - hero_box[1]

    hero_w, hero_h = hero.size

    # target size: fill ~88% of available height (tweak 0.88 -> 0.92 if you want even bigger)
    target_h = int(box_h * 0.88)
    scale = target_h / hero_h

    new_w = max(1, int(hero_w * scale))
    new_h = max(1, int(hero_h * scale))
    hero_rs = hero.resize((new_w, new_h), resample=Image.LANCZOS)

    # anchor lower-right with margins
    margin_right = 40
    margin_bottom = 40

    px = hero_box[2] - new_w - margin_right
    py = hero_box[3] - new_h - margin_bottom

    # safety: don't go above header
    py = max(py, header_h)

    canvas.alpha_composite(hero_rs, (px, py))

    # 7) Output PNG
    out = BytesIO()
    canvas.convert("RGBA").save(out, format="PNG")
    return Response(content=out.getvalue(), media_type="image/png")

