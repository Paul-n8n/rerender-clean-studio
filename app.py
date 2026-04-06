import os
import re
import logging
from io import BytesIO
from typing import List, Optional

import boto3
from botocore.config import Config
from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import httpx

log = logging.getLogger(__name__)

app = FastAPI()


@app.get("/")
def root():
    return {"ok": True, "service": "rerender-clean-studio"}


VERSION = "P1+P2+P3+P4+P5+P6+P7+P8 v2026-04-03a"

# ======================== STICKER UI STANDARDS ========================
STICKER_RADIUS = 14
STICKER_BORDER_W = 3
STICKER_FILL = (245, 204, 74, 255)
STICKER_OUTLINE = (20, 20, 20, 255)
STICKER_TEXT = (20, 20, 20, 255)

# ======================== THEME COLOR MAPPING ============================
THEME_COLORS = {
    "yellow": {
        "text": (26, 26, 26, 255),
        "chip_text": (30, 30, 30, 255),
        "divider": (80, 80, 80, 180),
        "sticker_outline": (20, 20, 20, 255),
        "accent": (34, 34, 34, 255),
        "brand_color": (0, 0, 0, 90),
        "chip_bg": (0, 0, 0, 13),
        "chip_border": (34, 34, 34, 255),
        "stat_bg": (0, 0, 0, 13),
        "stat_val": (34, 34, 34, 255),
        "stat_lbl": (0, 0, 0, 160),
        "cta_bg": (26, 26, 26, 255),
        "cta_text": (245, 204, 74, 255),
        "watermark": (0, 0, 0, 8),
        "top_accent": (34, 34, 34, 255),
        "stripe_fill": (0, 0, 0, 13),
        "stripe_line": (0, 0, 0, 26),
        "badge_border": (34, 34, 34, 255),
        "badge_text": (34, 34, 34, 255),
        # P1 gradient bg: linear-gradient(155deg, #d4b200, #e6c400 35%, #ccaa00 70%, #b89900)
        "p1_grad_start": (212, 178, 0),
        "p1_grad_end": (184, 153, 0),
        "p1_glow": (0, 0, 0, 8),
    },
    "grey": {
        "text": (255, 255, 255, 255),
        "chip_text": (255, 255, 255, 166),
        "divider": (80, 80, 80, 180),
        "sticker_outline": (20, 20, 20, 255),
        "accent": (245, 204, 74, 255),
        "brand_color": (255, 255, 255, 90),
        "chip_bg": (255, 255, 255, 13),
        "chip_border": (245, 204, 74, 255),
        "stat_bg": (255, 255, 255, 13),
        "stat_val": (245, 204, 74, 255),
        "stat_lbl": (255, 255, 255, 77),
        "cta_bg": (245, 204, 74, 255),
        "cta_text": (17, 17, 17, 255),
        "watermark": (255, 255, 255, 5),
        "top_accent": (245, 204, 74, 255),
        "stripe_fill": (245, 204, 74, 15),
        "stripe_line": (245, 204, 74, 38),
        "badge_border": (245, 204, 74, 255),
        "badge_text": (245, 204, 74, 255),
        # P1 gradient bg: linear-gradient(155deg, #3d3d3d, #333 50%, #2a2a2a)
        "p1_grad_start": (61, 61, 61),
        "p1_grad_end": (42, 42, 42),
        "p1_glow": (255, 255, 255, 8),
    },
    "navy": {
        "text": (255, 255, 255, 255),
        "chip_text": (255, 255, 255, 191),
        "divider": (200, 200, 200, 180),
        "sticker_outline": (20, 20, 20, 255),
        "accent": (245, 204, 74, 255),
        "brand_color": (255, 255, 255, 115),
        "chip_bg": (255, 255, 255, 13),
        "chip_border": (245, 204, 74, 255),
        "stat_bg": (255, 255, 255, 13),
        "stat_val": (245, 204, 74, 255),
        "stat_lbl": (255, 255, 255, 97),
        "cta_bg": (245, 204, 74, 255),
        "cta_text": (17, 17, 17, 255),
        "watermark": (255, 255, 255, 6),
        "top_accent": (245, 204, 74, 255),
        "stripe_fill": (245, 204, 74, 15),
        "stripe_line": (245, 204, 74, 38),
        "badge_border": (245, 204, 74, 255),
        "badge_text": (245, 204, 74, 255),
        # P1 gradient bg: linear-gradient(155deg, #162952, #0f1d3d 50%, #0a1428)
        "p1_grad_start": (22, 41, 82),
        "p1_grad_end": (10, 20, 40),
        "p1_glow": (255, 255, 255, 10),
    },
    "teal": {
        "text": (255, 255, 255, 255),
        "chip_text": (255, 255, 255, 204),
        "divider": (200, 200, 200, 180),
        "sticker_outline": (20, 20, 20, 255),
        "accent": (245, 204, 74, 255),
        "brand_color": (255, 255, 255, 128),
        "chip_bg": (255, 255, 255, 15),
        "chip_border": (245, 204, 74, 255),
        "stat_bg": (255, 255, 255, 18),
        "stat_val": (245, 204, 74, 255),
        "stat_lbl": (255, 255, 255, 102),
        "cta_bg": (245, 204, 74, 255),
        "cta_text": (17, 17, 17, 255),
        "watermark": (255, 255, 255, 8),
        "top_accent": (245, 204, 74, 255),
        "stripe_fill": (245, 204, 74, 18),
        "stripe_line": (245, 204, 74, 46),
        "badge_border": (245, 204, 74, 255),
        "badge_text": (245, 204, 74, 255),
        # P1 gradient bg: linear-gradient(155deg, #0d5c5c, #0a4a4a 50%, #073838)
        "p1_grad_start": (13, 92, 92),
        "p1_grad_end": (7, 56, 56),
        "p1_glow": (255, 255, 255, 13),
    },
}

DEFAULT_THEME_COLORS = THEME_COLORS["yellow"]


def get_theme_colors(theme: str) -> dict:
    return THEME_COLORS.get((theme or "yellow").lower(), DEFAULT_THEME_COLORS)


ICON_SIZE = 80
ICON_TEXT_GAP = 8
CHIP_GAP_X = 50
DIVIDER_WIDTH = 2
DIVIDER_COLOR = (80, 80, 80, 180)
CHIP_TEXT_COLOR = (30, 30, 30, 255)

# ======================== GLOW SETTINGS ===============================
GLOW_W = 500
GLOW_H = 250
GLOW_COLOR = (255, 255, 255)
GLOW_ALPHA = 60
GLOW_Y_OFFSET = 50
GLOW_NOISE = 3


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
    for path in [
        os.path.join(os.path.dirname(__file__), "assets", "fonts", "Inter_18pt-Medium.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def load_font_bold(size: int) -> ImageFont.FreeTypeFont:
    for path in [
        os.path.join(os.path.dirname(__file__), "assets", "fonts", "ArchivoNarrow-Bold.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]:
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
            return font, text
        size -= 2
    font = loader(min_size)
    truncated = text
    while len(truncated) > 1:
        truncated = truncated[:-1].rstrip()
        candidate = truncated + "…"
        w, _ = text_size(draw, candidate, font)
        if w <= max_w:
            return font, candidate
    return loader(min_size), text


def fit_text_p3_model(draw, text, max_w, loader=load_font_bold, start_size=210):
    """
    Three-phase model name fitting for P3 cards.
      Phase 1 – single line, shrink start_size → 80 (step 2)
      Phase 2 – two-line word-wrap, shrink 136 → 52 (step 2),
                 most-balanced split (minimises max line width)
      Phase 3 – truncate at size 80 with "…"
    Returns (font, line1, line2_or_None).
    """
    # ── Phase 1: single line ──────────────────────────────────────────
    for size in range(start_size, 80 - 1, -2):
        font = loader(size)
        w, _ = text_size(draw, text, font)
        if w <= max_w:
            return font, text, None

    # ── Phase 2: two-line wrap ────────────────────────────────────────
    words = text.split()
    if len(words) >= 2:
        for size in range(136, 52 - 1, -2):
            font = loader(size)
            best = None
            best_balance = float('inf')
            for i in range(1, len(words)):
                l1 = ' '.join(words[:i])
                l2 = ' '.join(words[i:])
                w1, _ = text_size(draw, l1, font)
                w2, _ = text_size(draw, l2, font)
                if w1 <= max_w and w2 <= max_w:
                    balance = max(w1, w2)
                    if balance < best_balance:
                        best_balance = balance
                        best = (l1, l2)
            if best:
                return font, best[0], best[1]

    # ── Phase 3: truncate at size 80 ─────────────────────────────────
    font = loader(80)
    truncated = text
    while len(truncated) > 1:
        truncated = truncated[:-1].rstrip()
        candidate = truncated + "…"
        w, _ = text_size(draw, candidate, font)
        if w <= max_w:
            return font, candidate, None
    return font, text, None


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


def draw_sticker_pill(draw, x0, y0, x1, y1, text, font):
    draw_rounded_rect(draw, (x0, y0, x1, y1), radius=STICKER_RADIUS, fill=STICKER_FILL)
    draw.rounded_rectangle((x0, y0, x1, y1), radius=STICKER_RADIUS,
                            outline=STICKER_OUTLINE, width=STICKER_BORDER_W)
    draw_text_centered_in_box(draw, x0, y0, x1 - x0, y1 - y0, text, font, STICKER_TEXT)


def draw_text_with_shadow(draw, x, y, text, font, fill, shadow_color=(0, 0, 0, 160), shadow_offset=2):
    """Draw text with a soft drop shadow for readability on any background."""
    for dx, dy in [(-1, shadow_offset), (1, shadow_offset), (0, shadow_offset), (0, 1)]:
        draw.text((x + dx, y + dy), text, font=font, fill=shadow_color)
    draw.text((x, y), text, font=font, fill=fill)


def _draw_spec_value(draw, x, row_top, row_h, text, font, fill, max_w):
    """
    Render a spec table value within a fixed-height row.

    Strategy (in order):
      1. Single line  — draw centered if it fits within max_w.
      2. Two lines    — split at the best natural break (space, slash,
                        comma, semicolon, pipe) so BOTH halves fit.
                        Prefer the split that most evenly balances widths.
      3. Truncate     — if no clean split exists, truncate line 1 with '…'.

    Row height is never changed; the caller owns layout geometry.
    """
    def _place_single(t, cy):
        bbox = draw.textbbox((0, 0), t, font=font)
        draw.text((x, cy - bbox[1]), t, font=font, fill=fill)

    _, lh = text_size(draw, text, font)
    w, _  = text_size(draw, text, font)

    # ── 1. Fits on one line ──────────────────────────────────────────
    if w <= max_w:
        _place_single(text, row_top + (row_h - lh) // 2)
        return

    # ── 2. Find best two-line split ──────────────────────────────────
    # '\u00b7' = middle-dot (·) recommended canonical separator for line_capacity
    SPLIT_CHARS = {' ', '/', ',', ';', '|', '\u00b7'}
    best_split  = None
    best_delta  = None   # lower = more balanced

    for pos in range(1, len(text)):
        ch = text[pos]
        if ch not in SPLIT_CHARS:
            continue

        if ch == '/':
            # Keep slash on line 1 (e.g. "PE0.8-200m/" / "PE1.0-150m")
            l1 = text[:pos + 1]
            l2 = text[pos + 1:].lstrip()
        elif ch in (',', ';', '|', '\u00b7'):
            # Strip separator itself from both sides
            l1 = text[:pos].rstrip()
            l2 = text[pos + 1:].lstrip()
        else:  # space
            l1 = text[:pos]
            l2 = text[pos + 1:]

        if not l1 or not l2:
            continue

        w1, _ = text_size(draw, l1, font)
        w2, _ = text_size(draw, l2, font)

        if w1 <= max_w and w2 <= max_w:
            delta = abs(w1 - w2)
            if best_delta is None or delta < best_delta:
                best_split = (l1, l2)
                best_delta = delta

    if best_split:
        l1, l2 = best_split
        _, lh1 = text_size(draw, l1, font)
        _, lh2 = text_size(draw, l2, font)
        gap     = 1
        total_h = lh1 + gap + lh2
        y1 = row_top + max(0, (row_h - total_h) // 2)
        y2 = y1 + lh1 + gap
        _place_single(l1, y1)
        _place_single(l2, y2)
        return

    # ── 3. No clean split — truncate with '…' ───────────────────────
    t = text
    while len(t) > 1:
        candidate = t[:-1].rstrip() + "…"
        cw, _     = text_size(draw, candidate, font)
        if cw <= max_w:
            _place_single(candidate, row_top + (row_h - lh) // 2)
            return
        t = t[:-1]
    _place_single(text[:1] + "…", row_top + (row_h - lh) // 2)


def draw_radial_glow(canvas: Image.Image, center_x: int, center_y: int,
                     glow_w: int = GLOW_W, glow_h: int = GLOW_H,
                     color: tuple = GLOW_COLOR, max_alpha: int = GLOW_ALPHA,
                     y_offset: int = GLOW_Y_OFFSET, noise_amp: int = GLOW_NOISE):
    import random
    cy = center_y + y_offset
    w, h = canvas.size
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    steps = 30
    for i in range(steps):
        t = i / steps
        ew = int(glow_w * (1.0 - t * 0.8))
        eh = int(glow_h * (1.0 - t * 0.8))
        a = int(max_alpha * t * t)
        if noise_amp > 0:
            a = max(0, min(255, a + random.randint(-noise_amp, noise_amp)))
        if a <= 0:
            continue
        x0 = center_x - ew
        y0 = cy - eh
        x1 = center_x + ew
        y1 = cy + eh
        glow_draw.ellipse((x0, y0, x1, y1), fill=(color[0], color[1], color[2], a))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=50))
    canvas.alpha_composite(glow)


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


def load_icon(filename: str, box_size: int) -> Optional[Image.Image]:
    path = os.path.join(ICONS_DIR, filename)
    if not os.path.exists(path):
        return None
    try:
        icon = Image.open(path).convert("RGBA")
        scale = min(box_size / icon.width, box_size / icon.height)
        new_w = max(1, int(icon.width * scale))
        new_h = max(1, int(icon.height * scale))
        icon = icon.resize((new_w, new_h), Image.LANCZOS)
        result = Image.new("RGBA", (box_size, box_size), (0, 0, 0, 0))
        offset_x = (box_size - new_w) // 2
        offset_y = (box_size - new_h) // 2
        result.alpha_composite(icon, (offset_x, offset_y))
        return result
    except Exception:
        return None


CHIP_ICONS = {
    # Icons removed — chips are now text-only for flexibility
}


# ---------- Routes ----------
@app.get("/health")
def health():
    return {"ok": True, "version": VERSION}


@app.post("/r2/upload")
async def r2_upload(key: str, file: UploadFile = File(...)):
    """Upload a file to R2. Used by marketing pipeline to store hero photos."""
    bucket = os.environ.get("R2_BUCKET")
    if not bucket:
        raise HTTPException(status_code=500, detail="Missing R2_BUCKET")
    s3 = r2_client()
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=file.content_type or "image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"R2 upload failed: {e}")
    return {"ok": True, "key": key, "size": len(data)}


@app.get("/r2/upload-from-url")
def r2_upload_from_url(source_url: str, key: str):
    """Download image from URL and upload to R2. Used by URL import pipeline."""
    import httpx
    try:
        resp = httpx.get(source_url, timeout=30, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Download failed: {e}")
    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Download returned {resp.status_code}")
    data = resp.content
    if not data or len(data) < 1000:
        raise HTTPException(status_code=400, detail="Downloaded file too small or empty")
    bucket = os.environ.get("R2_BUCKET")
    if not bucket:
        raise HTTPException(status_code=500, detail="Missing R2_BUCKET")
    s3 = r2_client()
    content_type = resp.headers.get("content-type", "image/jpeg")
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"R2 upload failed: {e}")
    return {"ok": True, "key": key, "size": len(data)}


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


# =====================================================================
# P1 rendering engine — K + Hybrid Mix design
# Two tiers: P1-A (budget, no stats) / P1-B (mid-premium, with stats)
# Uses gradient backgrounds (not PNG bg files)
# =====================================================================

def _make_gradient_bg(W: int, H: int, color_start: tuple, color_end: tuple) -> Image.Image:
    """Create a diagonal gradient background (155deg approx: top-left to bottom-right)."""
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    for y in range(H):
        for x in range(W):
            # 155deg gradient: progress based on mix of x and y
            t = (x * 0.42 + y * 0.91) / (W * 0.42 + H * 0.91)
            r = int(color_start[0] + (color_end[0] - color_start[0]) * t)
            g = int(color_start[1] + (color_end[1] - color_start[1]) * t)
            b = int(color_start[2] + (color_end[2] - color_start[2]) * t)
            canvas.putpixel((x, y), (r, g, b, 255))
    return canvas


def _make_gradient_bg_fast(W: int, H: int, color_start: tuple, color_end: tuple) -> Image.Image:
    """Fast gradient using numpy-like row blending."""
    import struct
    canvas = Image.new("RGBA", (W, H))
    pixels = []
    for y in range(H):
        for x in range(W):
            t = (x * 0.42 + y * 0.91) / (W * 0.42 + H * 0.91)
            r = int(color_start[0] + (color_end[0] - color_start[0]) * t)
            g = int(color_start[1] + (color_end[1] - color_start[1]) * t)
            b = int(color_start[2] + (color_end[2] - color_start[2]) * t)
            pixels.append((r, g, b, 255))
    canvas.putdata(pixels)
    return canvas


def _draw_diagonal_stripe(canvas: Image.Image, W: int, H: int, tc: dict):
    """Draw a subtle diagonal accent stripe + thin line (top-right to bottom)."""
    import math
    stripe = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stripe)
    sf = tc.get("stripe_fill", (245, 204, 74, 18))
    sl = tc.get("stripe_line", (245, 204, 74, 46))
    cx, cy = W - 80, H // 2
    band_w = 160
    angle = 12
    rad = math.radians(angle)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    for y_off in range(-H, H):
        x = cx + int(y_off * sin_a)
        y = cy + int(y_off * cos_a)
        if 0 <= y < H:
            alpha = int(sf[3] * max(0, 1 - abs(y_off) / (H * 0.8)))
            if alpha > 0:
                sd.line([(x - band_w // 2, y), (x + band_w // 2, y)],
                        fill=(sf[0], sf[1], sf[2], alpha))
    for y_off in range(-H, H):
        x = cx + 50 + int(y_off * sin_a)
        y = cy + int(y_off * cos_a)
        if 0 <= y < H and 0 <= x < W:
            stripe.putpixel((x, y), sl)
    canvas.alpha_composite(stripe)


def _draw_outlined_badge(draw: ImageDraw.ImageDraw, text: str, x1: int, y0: int,
                         font, border_color, text_color):
    """Draw an outlined rounded pill badge. Mockup: pad 4/14 → 10/35, border 1.5→4."""
    px, py = 35, 10  # mockup: padding 14px/4px → 35/10
    tw, th = text_size(draw, text, font)
    bw, bh = tw + px * 2, th + py * 2
    bx0 = x1 - bw
    by1 = y0 + bh
    draw.rounded_rectangle((bx0, y0, x1, by1), radius=bh // 2,
                           outline=border_color, width=4)  # mockup: 1.5px → 4
    draw_text_centered_in_box(draw, bx0, y0, bw, bh, text, font, text_color)


def _draw_stats_bar(canvas: Image.Image, y_top: int, W: int,
                    bearings: str, gear_ratio: str, max_drag: str, tc: dict):
    """Draw a 3-column stats bar. Dimensions from mockup ×2.5:
    left/right 14→35, gap 4→10, stat-val 19→48px, stat-lbl 7→18px,
    pill padding 7→18, border-radius 5→13.
    """
    pad_x = 35
    gap = 10
    bar_w = W - pad_x * 2
    pill_w = (bar_w - gap * 2) // 3
    pill_h = 95       # mockup stat area ~38px → 95
    radius = 13

    stat_bg = tc.get("stat_bg", (255, 255, 255, 18))
    stat_val_color = tc.get("stat_val", (245, 204, 74, 255))
    stat_lbl_color = tc.get("stat_lbl", (255, 255, 255, 102))

    val_font = load_font_bold(48)    # mockup: 19px → 48
    lbl_font = load_font_bold(18)    # mockup: 7px → 18

    stats = [
        (bearings or "\u2014", "BEARINGS"),
        (gear_ratio or "\u2014", "GEAR RATIO"),
        (max_drag or "\u2014", "MAX DRAG"),
    ]

    overlay = Image.new("RGBA", (W, canvas.size[1]), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)

    for i, (val, lbl) in enumerate(stats):
        px0 = pad_x + i * (pill_w + gap)
        od.rounded_rectangle((px0, y_top, px0 + pill_w, y_top + pill_h),
                             radius=radius, fill=stat_bg)
        # Value (centered, upper portion)
        vw, vh = text_size(od, val, val_font)
        vx = px0 + (pill_w - vw) // 2
        vy = y_top + 10
        od.text((vx, vy), val, font=val_font, fill=stat_val_color)
        # Label (centered, below value)
        lw, lh = text_size(od, lbl, lbl_font)
        lx = px0 + (pill_w - lw) // 2
        ly = y_top + pill_h - lh - 10
        od.text((lx, ly), lbl, font=lbl_font, fill=stat_lbl_color)

    canvas.alpha_composite(overlay)
    return pill_h


def _render_product(
    hero: Image.Image,
    theme: str,
    brand: str,
    model: str,
    chip1: str,
    chip2: str,
    chip3: str,
    chip4: str = "",
    chip5: str = "",
    bearings: str = "",
    gear_ratio: str = "",
    max_drag: str = "",
) -> bytes:
    """Compose a 1000x1000 P1 product card (K + Hybrid Mix design).

    All dimensions scaled exactly from the 400px HTML mockup (×2.5).
    P1-A = no stats (budget), P1-B = with stats bar (mid-premium).
    """
    W, H = 1000, 1000
    tc = get_theme_colors(theme)
    text_color = tc["text"]
    accent = tc.get("accent", (245, 204, 74, 255))

    # ── 0. Gradient background ───────────────────────────────────────
    grad_start = tc.get("p1_grad_start", (13, 92, 92))
    grad_end = tc.get("p1_grad_end", (7, 56, 56))
    canvas = _make_gradient_bg_fast(W, H, grad_start, grad_end)
    draw = ImageDraw.Draw(canvas)

    has_stats = any(s.strip() for s in [bearings, gear_ratio, max_drag])

    # ── Exact dimensions from 400px mockup × 2.5 ────────────────────
    LEFT   = 55       # mockup: left 22px
    TOP    = 45       # mockup: top 18px
    RIGHT  = 55       # mockup: right 18px → from right edge
    CTA_H  = 100      # mockup: height 40px
    STATS_H  = 110 if has_stats else 0   # mockup: stat row ~44px from bottom
    STATS_PAD = 35    # mockup: left/right 14px

    # ── 1. Gold top accent line (3px mockup → 8px) ───────────────────
    top_accent_color = tc.get("top_accent", accent)
    accent_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ad = ImageDraw.Draw(accent_overlay)
    for x in range(W):
        t = 1.0
        if x < W * 0.03:
            t = x / (W * 0.03)
        elif x > W * 0.97:
            t = (W - x) / (W * 0.03)
        a = int(top_accent_color[3] * t)
        if a > 0:
            ad.line([(x, 0), (x, 7)], fill=(top_accent_color[0], top_accent_color[1],
                                             top_accent_color[2], a))
    canvas.alpha_composite(accent_overlay)
    draw = ImageDraw.Draw(canvas)

    # ── 2. Diagonal stripe ───────────────────────────────────────────
    _draw_diagonal_stripe(canvas, W, H, tc)
    draw = ImageDraw.Draw(canvas)

    # ── 3. Ghost watermark (P1-B only) ───────────────────────────────
    # mockup: font-size 170px → 425px, bottom 55px → 138px from bottom
    if has_stats:
        wm_color = tc.get("watermark", (255, 255, 255, 8))
        wm_font = load_font_bold(425)
        wm_text = (model or "").strip().upper()
        if wm_text:
            wm_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            wm_draw = ImageDraw.Draw(wm_layer)
            ww, wh = text_size(wm_draw, wm_text, wm_font)
            wm_draw.text((W - ww + 25, H - CTA_H - STATS_H - wh + 20),
                         wm_text, font=wm_font, fill=wm_color)
            canvas.alpha_composite(wm_layer)
            draw = ImageDraw.Draw(canvas)

    # ── 4. Brand text (mockup: 12px → 30px, weight 600, letter-spacing 3.5→9px)
    brand_text = (brand or "").strip().upper()
    brand_color = tc.get("brand_color", (255, 255, 255, 128))
    brand_font = load_font_regular(30)
    brand_h = text_size(draw, brand_text, brand_font)[1]
    draw_text_align_left(draw, LEFT, TOP, brand_text, brand_font, brand_color)

    # ── 5. Gold accent line under brand (mockup: top 36 → 90, w 30 → 75, h 2.5 → 6)
    accent_line_y = 90
    draw.rectangle([(LEFT, accent_line_y), (LEFT + 75, accent_line_y + 6)],
                   fill=accent)

    # ── 6. Model text (mockup: top 44 → 110, font 46px → 115px, weight 900)
    model_text = (model or "").strip().upper()
    MODEL_Y = 110
    model_max_w = int(W * 0.65)
    model_font, model_text = fit_text(draw, model_text, max_w=model_max_w,
                                      start_size=115, min_size=60, loader=load_font_bold)
    model_h = text_size(draw, model_text, model_font)[1]
    draw_text_align_left(draw, LEFT, MODEL_Y, model_text, model_font, text_color)

    # ── 7. Outlined badge (mockup: top 18 → 45, right 18 → 45, font 10 → 25, pad 4/14 → 10/35)
    size_text = (chip3 or "").strip()
    if size_text:
        badge_font = load_font_bold(25)
        badge_border = tc.get("badge_border", accent)
        badge_text_c = tc.get("badge_text", accent)
        _draw_outlined_badge(draw, size_text, W - RIGHT, TOP + 5,
                             badge_font, badge_border, badge_text_c)

    # ── 8. Feature chips ─────────────────────────────────────────────
    # mockup: top 112 → 280, font 10 → 25, gap 5 → 13, pad 4/10 → 10/25, border 2.5 → 6
    features = [(chip1 or "").strip(), (chip2 or "").strip(),
                (chip4 or "").strip(), (chip5 or "").strip()]
    features = [c for c in features if c]

    CHIP_FONT_SZ = 25
    chip_font = load_font_bold(CHIP_FONT_SZ)
    chip_bg = tc.get("chip_bg", (255, 255, 255, 15))
    chip_border_color = tc.get("chip_border", accent)
    chip_text_color = tc.get("chip_text", (240, 240, 240, 255))

    # Measure chips for hero positioning
    chip_widths = []
    for c in features:
        tw, _ = text_size(draw, c, chip_font)
        chip_widths.append(tw)
    max_chip_w = max(chip_widths, default=0)

    CHIP_PAD_X = 25   # mockup: padding 10px → 25
    CHIP_PAD_Y = 10   # mockup: padding 4px → 10
    CHIP_BORDER_W = 6 # mockup: border-left 2.5px → 6
    CHIP_GAP = 13     # mockup: gap 5px → 13
    chip_right_edge = LEFT + max_chip_w + CHIP_PAD_X * 2 + CHIP_BORDER_W + 40 if features else LEFT

    # ── 9. Hero sizing and placement ─────────────────────────────────
    # mockup: top 68 → 170, right 22 → 55, 200×200 → 500×500
    hero_w, hero_h = hero.size
    HERO_RIGHT_MARGIN = RIGHT
    hero_zone_left = chip_right_edge if features else int(W * 0.28)
    hero_zone_right = W - HERO_RIGHT_MARGIN
    hero_zone_w = hero_zone_right - hero_zone_left
    HERO_TOP = 170    # mockup: top 68px → 170
    hero_zone_bottom = H - CTA_H - STATS_H - 10
    hero_zone_h = hero_zone_bottom - HERO_TOP

    # Hero must cover at least 1/3 of card area visually.
    # Allow hero to extend left behind chips (rendered behind text, z-order).
    # Use full right 65% of card as hero zone for sizing.
    hero_size_zone_w = int(W * 0.65)
    hero_size_zone_h = hero_zone_h
    MIN_HERO = 600    # minimum hero dimension — ensures 1/3 coverage
    target_sz = max(min(hero_size_zone_w, hero_size_zone_h), MIN_HERO)
    scale = target_sz / max(hero_w, hero_h)
    new_w = max(1, int(hero_w * scale))
    new_h = max(1, int(hero_h * scale))
    # Clamp: don't exceed available height
    if new_h > hero_zone_h:
        scale = hero_zone_h / hero_h
        new_w = max(1, int(hero_w * scale))
        new_h = max(1, int(hero_h * scale))
    hero_rs = hero.resize((new_w, new_h), resample=Image.LANCZOS)

    # Position: center-right (60% mark) so hero doesn't overlap left text
    hero_center_x = int(W * 0.58)
    px = hero_center_x - new_w // 2
    py = HERO_TOP + (hero_zone_h - new_h) // 2
    if py + new_h > hero_zone_bottom:
        py = hero_zone_bottom - new_h
    py = max(py, HERO_TOP)

    # Glow + Hero composite
    draw_radial_glow(canvas, px + new_w // 2, py + new_h // 2)
    draw = ImageDraw.Draw(canvas)
    canvas.alpha_composite(hero_rs, (px, py))
    draw = ImageDraw.Draw(canvas)

    # ── 10. Draw feature chips (mockup: top 112 → 280) ──────────────
    if features:
        CHIPS_TOP = 280   # mockup: top 112px → 280
        chip_h = CHIP_FONT_SZ + CHIP_PAD_Y * 2
        chip_start_y = CHIPS_TOP

        for c in features:
            tw, th = text_size(draw, c, chip_font)
            cw = tw + CHIP_PAD_X * 2 + CHIP_BORDER_W
            chip_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            cd = ImageDraw.Draw(chip_overlay)
            cd.rounded_rectangle(
                (LEFT, chip_start_y, LEFT + cw, chip_start_y + chip_h),
                radius=10, fill=chip_bg)
            canvas.alpha_composite(chip_overlay)
            draw = ImageDraw.Draw(canvas)
            # Left border accent
            draw.rectangle(
                [(LEFT, chip_start_y + 4),
                 (LEFT + CHIP_BORDER_W, chip_start_y + chip_h - 4)],
                fill=chip_border_color)
            # Chip text
            text_y = chip_start_y + (chip_h - th) // 2
            draw.text((LEFT + CHIP_BORDER_W + CHIP_PAD_X - 5, text_y),
                      c, font=chip_font, fill=chip_text_color)
            chip_start_y += chip_h + CHIP_GAP

    # ── 11. Bottom gradient fade (mockup: height 30 → 75) ───────────
    fade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fade)
    fade_h = 75
    fade_top = H - CTA_H - STATS_H - fade_h
    for y in range(fade_h):
        a = int(26 * (y / fade_h))
        fd.line([(0, fade_top + y), (W, fade_top + y)], fill=(0, 0, 0, a))
    canvas.alpha_composite(fade)
    draw = ImageDraw.Draw(canvas)

    # ── 12. Stats bar (P1-B only) ────────────────────────────────────
    # mockup: bottom 44, left/right 14, gap 4, stat-val 19→48, stat-lbl 7→18
    if has_stats:
        stats_y = H - CTA_H - STATS_H
        _draw_stats_bar(canvas, stats_y, W, bearings, gear_ratio, max_drag, tc)
        draw = ImageDraw.Draw(canvas)

    # ── 13. Full-width CTA bar (mockup: h 40 → 100, font 13 → 33) ──
    cta_bg = tc.get("cta_bg", (245, 204, 74, 255))
    cta_text_color = tc.get("cta_text", (17, 17, 17, 255))
    draw.rectangle([(0, H - CTA_H), (W, H)], fill=cta_bg)
    cta_font = load_font_bold(33)
    cta_full = "READY STOCK  \u25C6  FAST SHIP"
    cw, ch = text_size(draw, cta_full, cta_font)
    cx = (W - cw) // 2
    cy = H - CTA_H + (CTA_H - ch) // 2 - 4  # nudge up for visual center
    draw.text((cx, cy), cta_full, font=cta_font, fill=cta_text_color)

    out = BytesIO()
    canvas.convert("RGBA").save(out, format="PNG")
    return out.getvalue()


def _load_hero(key: str) -> Image.Image:
    """Load hero from R2, trim transparency."""
    data = r2_get_object_bytes(key)
    try:
        hero = Image.open(BytesIO(data)).convert("RGBA")
        return trim_transparent(hero, pad=6)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Not a valid image: {e}")


@app.get("/render/p1")
def render_p1(
    key:   str = Query(...),
    brand: str = Query("Daiwa"),
    model: str = Query("RS"),
    chip1: str = Query("3BB"),
    chip2: str = Query("5.1:1"),
    chip3: str = Query("RS1000-6000"),
    chip4: str = Query(""),
    chip5: str = Query(""),
    theme: str = Query("yellow"),
    bearings:   str = Query(""),
    gear_ratio: str = Query(""),
    max_drag:   str = Query(""),
):
    png = _render_product(
        _load_hero(key), theme, brand, model,
        chip1, chip2, chip3, chip4, chip5,
        bearings=bearings, gear_ratio=gear_ratio, max_drag=max_drag,
    )
    return Response(content=png, media_type="image/png")


# =====================================================================
# /render/p2 — Pure photo output (no text, no chips)
# Pipeline: 1024×1024 white canvas → alpha shadow → centered cutout
# Shadow params locked: dx=0 dy=15 blur=20 opacity=11%
# Product fit: 78% of canvas height, horizontally centred
# =====================================================================

P2_CANVAS_W  = 1024
P2_CANVAS_H  = 1024
P2_FIT_RATIO = 0.78          # product occupies 78% of canvas height
P2_SHADOW_DX = 0             # shadow x-offset (px)
P2_SHADOW_DY = 15            # shadow y-offset (px)  — was 18, reduced to soften
P2_SHADOW_BLUR   = 20        # gaussian blur radius  — was 28, reduced to cut ring
P2_SHADOW_ALPHA  = 28        # 11% of 255 ≈ 28      — was 46 (18%), now ~11%


def _render_p2_white(hero: Image.Image) -> bytes:
    """
    Composite a transparent-background cutout onto a white 1024×1024 canvas
    with a deterministic alpha-derived drop shadow.
    """
    W, H = P2_CANVAS_W, P2_CANVAS_H

    # --- Scale hero to fit 78% of canvas height ---
    hw, hh  = hero.size
    target_h = int(H * P2_FIT_RATIO)
    scale    = target_h / hh
    new_w    = max(1, int(hw * scale))
    new_h    = max(1, int(hh * scale))
    hero_rs  = hero.resize((new_w, new_h), Image.LANCZOS)

    # --- Centred placement ---
    px = (W - new_w) // 2
    py = (H - new_h) // 2

    # --- Build alpha-based shadow ---
    # Extract alpha channel of the resized hero, blur it, fill with shadow colour
    shadow_base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    alpha_mask   = hero_rs.split()[3]                    # alpha channel
    silhouette   = Image.new("RGBA", (new_w, new_h), (0, 0, 0, P2_SHADOW_ALPHA))
    silhouette.putalpha(alpha_mask)
    shadow_base.paste(silhouette, (px + P2_SHADOW_DX, py + P2_SHADOW_DY))
    shadow_blurred = shadow_base.filter(ImageFilter.GaussianBlur(radius=P2_SHADOW_BLUR))

    # --- Composite: white → shadow → hero ---
    canvas = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    canvas.alpha_composite(shadow_blurred)
    canvas.alpha_composite(hero_rs, (px, py))

    out = BytesIO()
    canvas.convert("RGB").save(out, format="PNG")   # RGB — no transparency needed
    return out.getvalue()


@app.get("/render/p2")
def render_p2(key: str = Query(...)):
    """
    P2 — pure beauty shot.
    White background, deterministic shadow, no text.
    Only 'key' (R2 path to transparent cutout) is required.
    """
    hero = _load_hero(key)
    return Response(content=_render_p2_white(hero), media_type="image/png")


# =====================================================================
# P3 Specs Auto-Extraction from specs_paste
# Parses the first row of a multi-model spec text to extract
# gear_ratio, max_drag, weight for P3's single-model spec table.
# =====================================================================

def _extract_p3_specs_from_paste(raw: str) -> dict:
    """
    Parse specs_paste text and extract gear_ratio, max_drag, weight
    from the first data row. Handles formats like:
      "1000 | BB:5+1 | Ratio:5.1:1 | Wt:220g | Drag:6kg"
      "Model BB Ratio Weight Drag\\n1000 5+1 5.1:1 220g 6kg"
    Returns dict with keys: gear_ratio, max_drag, weight, bearings
    """
    result = {}
    lines = [l.strip() for l in raw.strip().split("\n") if l.strip()]
    if not lines:
        return result

    # Strategy 1: Key:Value format (from scraper E1)
    # e.g. "1000 | BB:5+1 | Ratio:5.1:1 | Wt:220g | Drag:6kg"
    for line in lines:
        parts = re.split(r"\s*\|\s*", line)
        for part in parts:
            kv = part.split(":", 1)
            if len(kv) == 2:
                k, v = kv[0].strip().lower(), kv[1].strip()
                if k in ("ratio", "gear_ratio", "gear ratio", "nisbah", "nisbah gear"):
                    result.setdefault("gear_ratio", v)
                elif k in ("drag", "max_drag", "max drag", "seretan", "seretan max"):
                    result.setdefault("max_drag", v)
                elif k in ("wt", "weight", "berat", "reel wt", "reel weight"):
                    result.setdefault("weight", v)
                elif k in ("bb", "bearings", "bearing"):
                    result.setdefault("bearings", v)

    if result:
        return result

    # Strategy 2: Try to parse from _parse_specs_paste (reuse P6 parser)
    try:
        specs_data = _parse_specs_paste(raw)
        if specs_data:
            first = specs_data[0]
            if first.get("ratio"):
                result["gear_ratio"] = first["ratio"]
            if first.get("drag"):
                result["max_drag"] = first["drag"]
            if first.get("wt"):
                result["weight"] = first["wt"]
            if first.get("bb"):
                result["bearings"] = first["bb"]
    except Exception:
        pass

    return result


# =====================================================================
# /render/p3 — Spec Card (Technical Validation Slide)
# Layout: Brand + Model header, size-range badge, hero (55% height),
#         3 highlight chips (BB · gear ratio · max drag), spec table
#         (3 rows: gear ratio, max drag, weight).  Line capacity omitted
#         — varies per size; surfaced as chip3 instead.
# Canvas: 1024×1024, themed background (same assets as P1).
# =====================================================================

# Hero occupies 40% of canvas height — compact to fit chips + spec table below
P3_FIT_RATIO    = 0.51
P3_HERO_X_SHIFT = 0            # centred horizontally (no shift)

# Spec table geometry
P3_SPEC_ROW_H      = 36           # height of each spec data row (px)  — tight
P3_SPEC_PAD_Y      = 6            # inner vertical padding top/bottom    — tight
P3_SPEC_HEADER_H   = 22           # height of "TECH SPECS" header row inside pill
P3_SPEC_RADIUS     = 14           # corner radius of table background pill
P3_SPEC_LABELS     = ["Gear Ratio", "Max Drag", "Weight"]   # 3 rows; Line Cap. removed (varies per size)

# Subtle table background: dark themes get white tint, light themes get dark tint
_P3_SPEC_BG_DARK  = (255, 255, 255, 28)   # white overlay on teal/navy  — slightly more visible
_P3_SPEC_BG_LIGHT = (0,   0,   0,   20)   # black overlay on yellow/grey
_P3_DARK_THEMES   = {"teal", "navy"}


def _render_p3(
    hero: Image.Image,
    theme: str,
    brand: str,
    model: str,
    chip1: str,
    chip2: str,
    chip3: str,
    size_range: str,
    gear_ratio: str,
    max_drag: str,
    weight: str,
) -> bytes:
    """Compose a 1024×1024 P3 spec card and return raw PNG bytes.
    Chips: chip1=BB count, chip2=gear ratio, chip3=max drag (range).
    Spec table: Gear Ratio / Max Drag / Weight (3 rows).
    Line capacity omitted — varies per size variant.
    """
    W, H = 1024, 1024
    _tc = get_theme_colors(theme)
    canvas = _make_gradient_bg_fast(W, H, _tc.get("p1_grad_start", (13, 92, 92)), _tc.get("p1_grad_end", (7, 56, 56)))
    draw   = ImageDraw.Draw(canvas)

    tc              = get_theme_colors(theme)
    text_color      = tc["text"]
    chip_text_color = tc["chip_text"]
    divider_color   = tc["divider"]

    pad          = 56
    top_pad      = 36
    BOTTOM_SAFE  = 14
    CHIP_TOP_GAP = 8
    SPEC_GAP_Y   = 12

    # ── Header: brand + model (top-left) ──────────────────────────────
    header_left  = pad
    header_top   = top_pad
    header_max_w = int(W * 0.62) - header_left

    brand_text = (brand or "").strip().upper()
    brand_font, brand_text = fit_text(
        draw, brand_text, max_w=header_max_w,
        start_size=44, min_size=28, loader=load_font_regular,
    )
    brand_h = text_size(draw, brand_text, brand_font)[1]

    model_text = (model or "").strip().upper()
    model_font, model_line1, model_line2 = fit_text_p3_model(
        draw, model_text, max_w=header_max_w, loader=load_font_bold,
        start_size=100,   # compact header to fit reel + spec table
    )
    model_y      = header_top + brand_h - 4
    model_line_h = text_size(draw, model_line1, model_font)[1]

    # ── Chip metrics ──────────────────────────────────────────────────
    chip_font  = load_font_bold(34)
    features   = [(chip1 or "").strip(), (chip2 or "").strip(), (chip3 or "").strip()]
    features   = [c for c in features if c]

    chip_groups = []
    for i, c in enumerate(features):
        tw, th    = text_size(draw, c, chip_font)
        icon_file = CHIP_ICONS.get(i)
        icon      = load_icon(icon_file, ICON_SIZE) if icon_file else None
        icon_w    = ICON_SIZE if icon else 0
        group_w   = (icon_w + ICON_TEXT_GAP + tw) if icon else tw
        group_h   = max(ICON_SIZE, th)
        chip_groups.append((c, tw, th, group_w, group_h, icon, icon_w))

    chip_row_h    = max((gh for _, _, _, _, gh, _, _ in chip_groups), default=0)
    num_dividers  = max(0, len(chip_groups) - 1)
    total_chips_w = sum(gw for _, _, _, gw, _, _, _ in chip_groups)
    total_chips_w += num_dividers * (CHIP_GAP_X + DIVIDER_WIDTH)

    # ── Spec table metrics ────────────────────────────────────────────
    spec_values  = [gear_ratio, max_drag, weight]
    n_rows       = len(P3_SPEC_LABELS)
    # Total pill height = top-pad + header + data rows + bottom-pad
    spec_table_h = P3_SPEC_PAD_Y + P3_SPEC_HEADER_H + n_rows * P3_SPEC_ROW_H + P3_SPEC_PAD_Y

    spec_font_label  = load_font_regular(26)
    spec_font_value  = load_font_bold(26)
    spec_font_header = load_font_bold(18)      # "TECH SPECS" section label

    # ── Hero: scale to 50% canvas height ─────────────────────────────
    hw, hh   = hero.size
    target_h = int(H * P3_FIT_RATIO)
    scale    = target_h / hh
    new_w    = max(1, int(hw * scale))
    new_h    = max(1, int(hh * scale))
    hero_rs  = hero.resize((new_w, new_h), Image.LANCZOS)

    # Position: centred in the zone between header bottom and chips/spec area
    needed_below = CHIP_TOP_GAP + chip_row_h + SPEC_GAP_Y + spec_table_h + BOTTOM_SAFE
    # Use actual model text bottom — no fixed floor, let compact header save space
    actual_header_bottom = model_y + model_line_h + (model_line_h + 2 if model_line2 else 0) + 10
    header_bottom_y = actual_header_bottom
    max_hero_bottom = H - needed_below
    available_h = max_hero_bottom - header_bottom_y
    # Centre hero vertically in the available zone
    py = header_bottom_y + (available_h - new_h) // 2
    py = max(py, header_bottom_y)
    # Centre hero horizontally
    px = (W - new_w) // 2 + P3_HERO_X_SHIFT
    px = max(px, pad)
    px = min(px, W - new_w - 10)
    hero_bottom = py + new_h

    # ── Draw text header ──────────────────────────────────────────────
    draw_text_align_left(draw, header_left, header_top, brand_text,  brand_font,  text_color)
    draw_text_align_left(draw, header_left, model_y,    model_line1, model_font,  text_color)
    if model_line2:
        draw_text_align_left(draw, header_left, model_y + model_line_h + 2, model_line2, model_font, text_color)

    # ── Size range badge (top-right) ──────────────────────────────────
    sr_text = (size_range or "").strip()
    if sr_text:
        badge_font = load_font_bold(34)
        bpx, bpy   = 20, 10
        btw, bth   = text_size(draw, sr_text, badge_font)
        bw, bh     = btw + bpx * 2, bth + bpy * 2
        bx1        = W - pad
        by0        = top_pad + 10
        bx0        = bx1 - bw
        by1        = by0 + bh
        draw_sticker_pill(draw, bx0, by0, bx1, by1, sr_text, badge_font)

    # ── Glow + hero composite ─────────────────────────────────────────
    draw_radial_glow(canvas, px + new_w // 2, py + new_h // 2)
    draw = ImageDraw.Draw(canvas)
    canvas.alpha_composite(hero_rs, (px, py))
    draw = ImageDraw.Draw(canvas)

    # ── Chips row ─────────────────────────────────────────────────────
    chip_y_top    = hero_bottom + CHIP_TOP_GAP
    chip_y_center = chip_y_top + chip_row_h // 2
    chip_start_x  = (W - total_chips_w) // 2
    cur_x         = chip_start_x

    for idx, (c, tw, th, gw, gh, icon, icon_w) in enumerate(chip_groups):
        if icon:
            icon_y = chip_y_center - ICON_SIZE // 2
            canvas.alpha_composite(icon, (cur_x, icon_y))
            draw   = ImageDraw.Draw(canvas)
            text_x = cur_x + icon_w + ICON_TEXT_GAP
        else:
            text_x = cur_x
        bbox   = draw.textbbox((0, 0), c, font=chip_font)
        text_h = bbox[3] - bbox[1]
        text_y = chip_y_center - text_h // 2 - bbox[1]
        draw.text((text_x, text_y), c, font=chip_font, fill=chip_text_color)
        cur_x += gw
        if idx < len(chip_groups) - 1:
            div_x     = cur_x + CHIP_GAP_X // 2
            div_y_top = chip_y_center - int(chip_row_h * 0.35)
            div_y_bot = chip_y_center + int(chip_row_h * 0.35)
            draw.line([(div_x, div_y_top), (div_x, div_y_bot)],
                      fill=divider_color, width=DIVIDER_WIDTH)
            cur_x += CHIP_GAP_X + DIVIDER_WIDTH

    chips_bottom = chip_y_top + chip_row_h

    # ── Spec table ────────────────────────────────────────────────────
    table_y  = chips_bottom + SPEC_GAP_Y
    table_x0 = pad
    table_x1 = W - pad
    table_w  = table_x1 - table_x0

    # Subtle translucent background pill
    spec_bg      = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    spec_bg_draw = ImageDraw.Draw(spec_bg)
    bg_fill      = _P3_SPEC_BG_DARK if (theme or "").lower() in _P3_DARK_THEMES else _P3_SPEC_BG_LIGHT
    spec_bg_draw.rounded_rectangle(
        (table_x0, table_y, table_x1, table_y + spec_table_h),
        radius=P3_SPEC_RADIUS,
        fill=bg_fill,
    )
    canvas.alpha_composite(spec_bg)
    draw = ImageDraw.Draw(canvas)

    # Column positions: label left (24px inset), value at 38% of table width
    col_label_x  = table_x0 + 24
    col_value_x  = table_x0 + int(table_w * 0.38)
    max_value_w  = (table_x1 - 16) - col_value_x   # right edge minus 16px inset

    is_dark = (theme or "").lower() in _P3_DARK_THEMES
    label_fill  = (255, 255, 255, 160) if is_dark else (60, 60, 60, 180)
    header_fill = (255, 255, 255, 110) if is_dark else (80, 80, 80, 140)

    # ── "TECH SPECS" header row ────────────────────────────────────────
    header_text_y = table_y + P3_SPEC_PAD_Y + (P3_SPEC_HEADER_H - 18) // 2
    draw.text((col_label_x, header_text_y), "TECH SPECS", font=spec_font_header, fill=header_fill)

    # Thin divider below header
    header_div_y = table_y + P3_SPEC_PAD_Y + P3_SPEC_HEADER_H - 1
    draw.line(
        [(table_x0 + 16, header_div_y), (table_x1 - 16, header_div_y)],
        fill=divider_color, width=1,
    )

    # ── Data rows (start below header) ────────────────────────────────
    data_top = table_y + P3_SPEC_PAD_Y + P3_SPEC_HEADER_H   # y where first data row begins

    for i, (label, value) in enumerate(zip(P3_SPEC_LABELS, spec_values)):
        row_top = data_top + i * P3_SPEC_ROW_H
        text_y  = row_top + (P3_SPEC_ROW_H - 26) // 2

        draw.text((col_label_x, text_y), label, font=spec_font_label, fill=label_fill)
        _draw_spec_value(
            draw, col_value_x, row_top, P3_SPEC_ROW_H,
            value, spec_font_value, text_color, max_value_w,
        )

        # Row divider (not after last row)
        if i < n_rows - 1:
            div_y = row_top + P3_SPEC_ROW_H - 1
            draw.line(
                [(table_x0 + 16, div_y), (table_x1 - 16, div_y)],
                fill=divider_color, width=1,
            )

    out = BytesIO()
    canvas.convert("RGBA").save(out, format="PNG")
    return out.getvalue()


@app.get("/render/p3")
def render_p3(
    key:           str = Query(...),
    brand:         str = Query("Daiwa"),
    model:         str = Query("RS"),
    chip1:         str = Query("3BB"),          # e.g. "5+1BB"
    chip2:         str = Query("5.1:1"),         # e.g. "5.1–6.2:1"
    chip3:         str = Query("6 kg"),          # max drag — e.g. "6–12 kg"
    theme:         str = Query("yellow"),
    size_range:    str = Query("RS1000-6000"),
    gear_ratio:    str = Query("\u2014"),
    max_drag:      str = Query("\u2014"),
    weight:        str = Query("\u2014"),
    line_capacity: str = Query("\u2014"),        # accepted but not rendered (varies per size)
    specs_paste:   str = Query(""),              # multi-model specs text; auto-extracts gear_ratio/max_drag/weight if individual fields are dashes
):
    """
    P3 — spec card. Themed background, brand/model header, size-range
    badge, hero at 55% height, 3 highlight chips, 3-row spec table
    (Gear Ratio / Max Drag / Weight).
    chip3 = max drag range shown as scannable chip.
    line_capacity accepted for forward-compat but not rendered.

    If specs_paste is provided and individual spec fields are still default
    dashes, auto-extracts from the first spec row in specs_paste.
    """
    # Auto-extract from specs_paste if individual fields are dashes
    if specs_paste and specs_paste.strip():
        _extracted = _extract_p3_specs_from_paste(specs_paste)
        if gear_ratio == "\u2014" and _extracted.get("gear_ratio"):
            gear_ratio = _extracted["gear_ratio"]
        if max_drag == "\u2014" and _extracted.get("max_drag"):
            max_drag = _extracted["max_drag"]
        if weight == "\u2014" and _extracted.get("weight"):
            weight = _extracted["weight"]
        # Also auto-fill chips from specs if they're defaults
        if chip1 == "3BB" and _extracted.get("bearings"):
            chip1 = _extracted["bearings"]
        if chip2 == "5.1:1" and _extracted.get("gear_ratio"):
            chip2 = _extracted["gear_ratio"]
        if chip3 == "6 kg" and _extracted.get("max_drag"):
            chip3 = _extracted["max_drag"]

    hero = _load_hero(key)
    png  = _render_p3(
        hero, theme, brand, model, chip1, chip2, chip3,
        size_range, gear_ratio, max_drag, weight,
    )
    return Response(content=png, media_type="image/png")


# =====================================================================
# /render/p4 — Feature Highlight Card
# Layout: Compact Brand + Model header (top-left), auto-zoomed hero
#         (120% scale, right-anchored, top-biased so spool/rotor is
#         prominent), Feature Title + Tag pill + Feature Body block.
# Hero:   Reuses P3_DETAIL_CUTOUT (already in R2).
# Canvas: 1024×1024, themed background (same assets as P1/P3).
# =====================================================================

P4_HERO_SCALE  = 1.20   # hero height = 120% of canvas height
P4_HERO_X_FRAC = 0.24   # hero left edge starts at 24% of W (show more reel)
P4_HERO_Y_BIAS = -0.06  # nudge hero upward (fraction of H) to expose spool
P4_TEXT_W_FRAC = 0.42   # text block uses left 42% of canvas
P4_FEAT_Y_FRAC = 0.40   # Feature block starts at 40% down canvas
P4_TAG_PAD_X   = 14     # tag pill inner x padding
P4_TAG_PAD_Y   = 7      # tag pill inner y padding


def _wrap_lines_p4(draw, text: str, max_w: int, font) -> list:
    """Wrap text into at most 2 lines that each fit within max_w.
    Falls back to truncating with '…' if no word-split works."""
    words = text.split()
    if not words:
        return [""]
    if text_size(draw, text, font)[0] <= max_w:
        return [text]
    for i in range(1, len(words)):
        l1 = ' '.join(words[:i])
        l2 = ' '.join(words[i:])
        if text_size(draw, l1, font)[0] <= max_w and text_size(draw, l2, font)[0] <= max_w:
            return [l1, l2]
    t = text
    while len(t) > 1:
        candidate = t[:-1].rstrip() + "\u2026"
        if text_size(draw, candidate, font)[0] <= max_w:
            return [candidate]
        t = t[:-1]
    return [text]


def _render_p4(
    hero: Image.Image,
    theme: str,
    brand: str,
    model: str,
    feature_title: str,
    feature_body: str,
    feature_tag: str,
) -> bytes:
    """Compose a 1024×1024 P4 Feature Highlight card and return raw PNG bytes."""
    W, H   = 1024, 1024
    _tc = get_theme_colors(theme)
    canvas = _make_gradient_bg_fast(W, H, _tc.get("p1_grad_start", (13, 92, 92)), _tc.get("p1_grad_end", (7, 56, 56)))
    draw   = ImageDraw.Draw(canvas)

    tc         = get_theme_colors(theme)
    text_color = tc["text"]
    is_dark    = (theme or "yellow").lower() in _P3_DARK_THEMES

    pad        = 56
    top_pad    = 44
    text_max_w = int(W * P4_TEXT_W_FRAC) - pad

    # ── Brand (compact 40pt) ──────────────────────────────────────────
    brand_text = (brand or "").strip().upper()
    brand_font, brand_text = fit_text(
        draw, brand_text, max_w=text_max_w,
        start_size=40, min_size=24, loader=load_font_regular,
    )
    brand_h = text_size(draw, brand_text, brand_font)[1]

    # ── Model (compact, 80 → 32pt) ────────────────────────────────────
    model_text = (model or "").strip().upper()
    model_font, model_text = fit_text(
        draw, model_text, max_w=text_max_w,
        start_size=80, min_size=32, loader=load_font_bold,
    )
    model_h = text_size(draw, model_text, model_font)[1]

    # ── Hero: 120% scale, right-anchored, top-biased ──────────────────
    hw, hh  = hero.size
    new_h   = max(1, int(H * P4_HERO_SCALE))
    scale   = new_h / hh
    new_w   = max(1, int(hw * scale))
    hero_rs = hero.resize((new_w, new_h), Image.LANCZOS)
    px      = int(W * P4_HERO_X_FRAC)
    py      = int((H - new_h) / 2 + H * P4_HERO_Y_BIAS)

    # ── Feature title metrics ─────────────────────────────────────────
    title_text = (feature_title or "").strip().upper()
    title_font, title_text = fit_text(
        draw, title_text, max_w=text_max_w,
        start_size=60, min_size=32, loader=load_font_bold,
    )
    title_h = text_size(draw, title_text, title_font)[1]

    # ── Feature tag pill metrics ──────────────────────────────────────
    tag_text = (feature_tag or "").strip()
    tag_font = load_font_bold(32)
    tag_bg   = STICKER_FILL              if is_dark else (20, 20, 20, 220)
    tag_fg   = STICKER_TEXT              if is_dark else (255, 255, 255, 255)
    tag_w = tag_h = 0
    if tag_text:
        tw, th = text_size(draw, tag_text, tag_font)
        tag_w  = tw + P4_TAG_PAD_X * 2
        tag_h  = th + P4_TAG_PAD_Y * 2

    # ── Feature body metrics ──────────────────────────────────────────
    body_text  = (feature_body or "").strip()
    body_font  = load_font_regular(32)
    body_lines = _wrap_lines_p4(draw, body_text, text_max_w, body_font)
    body_lh    = text_size(draw, "Ag", body_font)[1]

    # ── Glow + hero composite ─────────────────────────────────────────
    draw_radial_glow(canvas, px + new_w // 2, py + new_h // 2)
    draw = ImageDraw.Draw(canvas)
    canvas.alpha_composite(hero_rs, (px, py))
    draw = ImageDraw.Draw(canvas)

    # ── Brand + model header ──────────────────────────────────────────
    model_y = top_pad + brand_h - 4
    draw_text_align_left(draw, pad, top_pad,   brand_text, brand_font, text_color)
    draw_text_align_left(draw, pad, model_y,   model_text, model_font, text_color)

    # Thin separator line below model — use bbox[3] for actual bottom
    _model_bbox = draw.textbbox((pad, model_y), model_text, font=model_font)
    sep_y   = _model_bbox[3] + 14
    sep_end = int(W * P4_TEXT_W_FRAC) - 10
    sep_col = (text_color[0], text_color[1], text_color[2], 180)
    draw.line([(pad, sep_y), (sep_end, sep_y)], fill=sep_col, width=2)

    # ── Feature block ─────────────────────────────────────────────────
    feat_y = int(H * P4_FEAT_Y_FRAC)

    draw_text_align_left(draw, pad, feat_y, title_text, title_font, text_color)

    if tag_text:
        # Use bbox for precise title bottom, then centre tag pill between title and body
        _title_bbox = draw.textbbox((pad, feat_y), title_text, font=title_font)
        title_bottom = _title_bbox[3]
        # Measure body height to calculate even spacing
        body_top_estimate = title_bottom + tag_h + 120  # rough total span
        gap_above = 56   # title → tag pill
        gap_below = 44   # tag pill → body (visually matches because pill has internal padding)
        tx0 = pad
        ty0 = title_bottom + gap_above
        tx1, ty1 = tx0 + tag_w, ty0 + tag_h
        draw_rounded_rect(draw, (tx0, ty0, tx1, ty1), radius=8, fill=tag_bg)
        # Centre text inside pill using anchor='mm'
        pill_cx = tx0 + tag_w // 2
        pill_cy = ty0 + tag_h // 2
        draw.text((pill_cx, pill_cy), tag_text, font=tag_font, fill=tag_fg, anchor='mm')
        feat_y = ty1 + gap_below
    else:
        feat_y += title_h + 56

    body_col = (text_color[0], text_color[1], text_color[2], 210)
    for line in body_lines:
        draw_text_align_left(draw, pad, feat_y, line, body_font, body_col)
        feat_y += body_lh + 10

    out = BytesIO()
    canvas.convert("RGBA").save(out, format="PNG")
    return out.getvalue()


@app.get("/render/p4")
def render_p4(
    key:           str = Query(...),
    brand:         str = Query("Daiwa"),
    model:         str = Query("Procaster LT"),
    theme:         str = Query("grey"),
    feature_title: str = Query("POWER DRAG"),
    feature_body:  str = Query("Smooth, strong drag for fighting big fish."),
    feature_tag:   str = Query(""),
):
    """
    P4 — Feature Highlight card.
    Auto-zoomed hero (120% scale, right-anchored, top-biased),
    compact Brand/Model header, Feature Title + Tag pill + Body block.
    """
    hero = _load_hero(key)
    png  = _render_p4(hero, theme, brand, model, feature_title, feature_body, feature_tag)
    return Response(content=png, media_type="image/png")


# =====================================================================
# /render/p5 — In-Hand / Trust Card
# Layout: Full-bleed photo background (scale-to-cover, center crop),
#         dark gradient top + bottom for text readability,
#         Brand + Model header (top-left), Trust badge pill (top-right),
#         2-chip row centered at bottom.
# Fallback: P5_INHAND_CUTOUT → P2_ANGLE_CUTOUT → P3_DETAIL_CUTOUT
#           → P1_HERO_CUTOUT  (tries each until one exists in R2).
# Canvas: 1024×1024.  Output: RGB PNG (full-bleed, no transparency).
# =====================================================================

P5_GRAD_BOTTOM_H = 0.45   # bottom gradient covers this fraction of canvas
P5_GRAD_TOP_H    = 0.22   # top gradient covers this fraction of canvas
P5_CHIP_BOTTOM   = 52     # px from bottom edge to chip row baseline
P5_CHIP_SIZE     = 38     # chip font size


def _normalize_pk(product_key: str) -> str:
    """Normalize product_key to match R2 path format used by Worker upload.
    'SOLARIA | SZ=1000-5000' -> 'SOLARIA___SZ_1000_5000'"""
    s = product_key.upper().replace("|", "__")
    s = re.sub(r"[^A-Z0-9]+", "_", s)
    s = s.strip("_")
    return s


def _load_p5_hero(product_key: str, group: str):
    """Try slots in priority order until one exists in R2.
    Returns (PIL Image RGBA, slot_name_used)."""
    slots = [
        "P5_INHAND_CUTOUT",
        "P2_ANGLE_CUTOUT",
        "P3_DETAIL_CUTOUT",
        "P1_HERO_CUTOUT",
    ]
    bucket = os.environ.get("R2_BUCKET")
    if not bucket:
        raise HTTPException(status_code=500, detail="Missing R2_BUCKET")
    s3 = r2_client()
    pk_norm = _normalize_pk(product_key)
    for slot in slots:
        for ext in ("png", "jpg", "jpeg"):
            key = f"raw/{pk_norm}/{group}/{slot}.{ext}"
            try:
                obj  = s3.get_object(Bucket=bucket, Key=key)
                data = obj["Body"].read()
                img  = Image.open(BytesIO(data)).convert("RGBA")
                return img, slot
            except Exception:
                continue
    raise HTTPException(
        status_code=404,
        detail=f"No hero image found for {product_key}/{group} (tried all slots)",
    )


def _scale_to_cover(img: Image.Image, W: int, H: int) -> Image.Image:
    """Scale image to fill W×H (cover mode) then center-crop."""
    iw, ih = img.size
    scale  = max(W / iw, H / ih)
    new_w  = max(1, int(iw * scale))
    new_h  = max(1, int(ih * scale))
    img    = img.resize((new_w, new_h), Image.LANCZOS)
    left   = (new_w - W) // 2
    top    = (new_h - H) // 2
    return img.crop((left, top, left + W, top + H))


def _render_p5(
    hero:      Image.Image,
    slot_used: str,
    theme:     str,
    brand:     str,
    model:     str,
    chip1:     str,
    chip2:     str,
    badge:     str,
) -> bytes:
    """Compose a 1024×1024 P5 Trust card and return raw PNG bytes.

    Two rendering modes:
      • Full-bleed  (slot_used == P5_INHAND_CUTOUT) — real photo covers
        canvas, dark gradients top+bottom, white text always.
      • Composite   (fallback slot) — themed background + centered cutout,
        theme text colour. Avoids white-fringe artefacts on cutout edges.
    """
    W, H = 1024, 1024

    is_inhand = (slot_used == "P5_INHAND_CUTOUT")
    pad       = 48
    top_pad   = 36

    # Detect if "in-hand" photo is actually a bg-removed cutout
    # If so, treat it as composite mode (themed bg) instead of full-bleed
    hero_has_transparency = hero.convert("RGBA").getchannel("A").getextrema()[0] < 200
    use_fullbleed = is_inhand and not hero_has_transparency

    if use_fullbleed:
        # ── Full-bleed photo mode (opaque in-hand photo) ───────────────
        hero_rgba = hero.convert("RGBA")
        canvas = _scale_to_cover(hero_rgba, W, H)
        draw   = ImageDraw.Draw(canvas)
        text_color = (255, 255, 255, 255)

        # Bottom gradient
        bot_grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        bg_draw  = ImageDraw.Draw(bot_grad)
        bot_h    = int(H * P5_GRAD_BOTTOM_H)
        for y in range(bot_h):
            a = int(140 * (y / bot_h) ** 1.6)
            bg_draw.line([(0, H - bot_h + y), (W, H - bot_h + y)], fill=(0, 0, 0, a))
        canvas.alpha_composite(bot_grad)

        # Top gradient
        top_grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        tg_draw  = ImageDraw.Draw(top_grad)
        top_h    = int(H * P5_GRAD_TOP_H)
        for y in range(top_h):
            a = int(100 * (1 - y / top_h) ** 1.8)
            tg_draw.line([(0, y), (W, y)], fill=(0, 0, 0, a))
        canvas.alpha_composite(top_grad)
        draw = ImageDraw.Draw(canvas)

    else:
        # ── Composite mode (fallback cutout on themed background) ──────
        # Use themed bg so cutout edge anti-aliasing blends correctly
        _tc = get_theme_colors(theme)
        canvas = _make_gradient_bg_fast(W, H, _tc.get("p1_grad_start", (13, 92, 92)), _tc.get("p1_grad_end", (7, 56, 56)))
        draw   = ImageDraw.Draw(canvas)
        tc         = get_theme_colors(theme)
        text_color = tc["text"]

        # Scale hero to ~78% height, centred (same as P2 but with glow)
        hw, hh  = hero.size
        target_h = int(H * 0.78)
        scale    = target_h / hh
        new_w    = max(1, int(hw * scale))
        new_h    = max(1, int(hh * scale))
        hero_rs  = hero.resize((new_w, new_h), Image.LANCZOS)

        # ── Edge feathering: blur alpha channel to soften cutout edges ──
        r, g, b, a = hero_rs.split()
        a_feathered = a.filter(ImageFilter.GaussianBlur(radius=2))
        hero_rs = Image.merge("RGBA", (r, g, b, a_feathered))

        px       = (W - new_w) // 2
        py       = (H - new_h) // 2

        draw_radial_glow(canvas, px + new_w // 2, py + new_h // 2)
        draw = ImageDraw.Draw(canvas)
        canvas.alpha_composite(hero_rs, (px, py))
        draw = ImageDraw.Draw(canvas)

    # ── Brand + model (top-left) ──────────────────────────────────────
    text_max_w = int(W * 0.62) - pad

    brand_text = (brand or "").strip().upper()
    brand_font, brand_text = fit_text(
        draw, brand_text, max_w=text_max_w,
        start_size=40, min_size=24, loader=load_font_regular,
    )
    brand_h = text_size(draw, brand_text, brand_font)[1]

    model_text = (model or "").strip().upper()
    model_font, model_text = fit_text(
        draw, model_text, max_w=text_max_w,
        start_size=80, min_size=32, loader=load_font_bold,
    )

    draw_text_align_left(draw, pad, top_pad,               brand_text, brand_font, text_color)
    draw_text_align_left(draw, pad, top_pad + brand_h - 4, model_text, model_font, text_color)

    # ── Trust badge (top-right) ────────────────────────────────────────
    badge_text = (badge or "").strip().upper()
    if badge_text:
        bf       = load_font_bold(26)
        bpx, bpy = 16, 8
        btw, bth = text_size(draw, badge_text, bf)
        bw, bh   = btw + bpx * 2, bth + bpy * 2
        bx1      = W - pad
        by0      = top_pad + 8
        bx0      = bx1 - bw
        by1      = by0 + bh
        draw_sticker_pill(draw, bx0, by0, bx1, by1, badge_text, bf)

    # ── 2-chip row (bottom, centered) ────────────────────────────────
    chip_font = load_font_bold(P5_CHIP_SIZE)
    features  = [(chip1 or "").strip(), (chip2 or "").strip()]
    features  = [c for c in features if c]

    if features:
        chip_groups = []
        for c in features:
            tw, th = text_size(draw, c, chip_font)
            chip_groups.append((c, tw, th))

        n_div     = max(0, len(chip_groups) - 1)
        total_w   = sum(tw for _, tw, _ in chip_groups) + n_div * (CHIP_GAP_X + DIVIDER_WIDTH)
        chip_row_h = max(th for _, _, th in chip_groups)
        chip_y    = H - P5_CHIP_BOTTOM - chip_row_h
        cur_x     = (W - total_w) // 2

        for idx, (c, tw, th) in enumerate(chip_groups):
            ty = chip_y + (chip_row_h - th) // 2
            draw_text_align_left(draw, cur_x, ty, c, chip_font, text_color)
            cur_x += tw
            if idx < len(chip_groups) - 1:
                div_x  = cur_x + CHIP_GAP_X // 2
                div_cy = chip_y + chip_row_h // 2
                draw.line(
                    [(div_x, div_cy - 14), (div_x, div_cy + 14)],
                    fill=(255, 255, 255, 150), width=2,
                )
                cur_x += CHIP_GAP_X + DIVIDER_WIDTH

    out = BytesIO()
    canvas.convert("RGB").save(out, format="PNG")
    return out.getvalue()


@app.get("/render/p5")
def render_p5(
    product_key: str = Query(...),
    group:       str = Query("A"),
    brand:       str = Query("Daiwa"),
    model:       str = Query("Procaster LT"),
    theme:       str = Query("grey"),
    chip1:       str = Query(""),
    chip2:       str = Query(""),
    badge:       str = Query("READY STOCK"),
):
    """
    P5 — In-Hand / Trust card.
    Full-bleed photo, auto-fallback: P5_INHAND_CUTOUT → P2_ANGLE_CUTOUT
    → P3_DETAIL_CUTOUT → P1_HERO_CUTOUT.
    Brand/Model top-left, trust badge top-right, 2 chips bottom-center.
    """
    hero, slot_used = _load_p5_hero(product_key, group)
    png = _render_p5(hero, slot_used, theme, brand, model, chip1, chip2, badge)
    return Response(content=png, media_type="image/png",
                    headers={"X-Used-Slot": slot_used})


# =====================================================================
# /render/p6 — Specs Comparison Table
# Parses specs_paste (multi-model spec text from seller page) into a
# structured comparison table.  Ghost reel watermark (reuses P8 loader).
# Falls back to "NO SPECS DATA" message when specs_paste is empty.
# =====================================================================

P6_TAG_PAD_X       = 16
P6_TAG_PAD_Y       = 9
P6_TABLE_PAD       = 40     # left/right padding inside card
P6_TABLE_TOP       = 165    # y where table starts (below header)
P6_COL_HEADER_H    = 48     # height of column header row
P6_DATA_ROW_H      = 46     # height of each data row
P6_TABLE_RADIUS    = 14     # corner radius of table background pill
P6_WATERMARK_ALPHA = 28     # ghost reel alpha (~11% of 255)
P6_WATERMARK_BLUR  = 10     # GaussianBlur radius for ghost effect

# Spec keys to extract from paste text (order = column order in table)
# LINE CAPACITY skipped — too detailed / varies per spool
P6_SPEC_KEYS = ["BB", "RATIO", "WEIGHT", "DRAG"]
P6_COL_LABELS = {
    "MODEL":  "MODEL",
    "BB":     "BB",
    "RATIO":  "RATIO",
    "WEIGHT": "WT (g)",
    "DRAG":   "DRAG",
}

# Aliases for colon/dash parsing — seller pages use many different labels
_P6_PARSE_ALIASES = {
    # Ball bearings
    "BALL BEARING":    "BB",
    "BALL BEARINGS":   "BB",
    "BB":              "BB",
    "BEARING":         "BB",
    "BEARINGS":        "BB",
    # Gear ratio
    "GEAR RATIO":      "RATIO",
    "RATIO":           "RATIO",
    "RATION":          "RATIO",         # common typo
    "NISBAH GEAR":     "RATIO",         # Malay
    # Weight
    "WEIGHT":          "WEIGHT",
    "BODY WEIGHT":     "WEIGHT",
    "REEL WEIGHT":     "WEIGHT",
    "REEL WT":         "WEIGHT",
    "NET WEIGHT":      "WEIGHT",
    "WT":              "WEIGHT",
    "BERAT":           "WEIGHT",         # Malay
    # Max drag
    "MAX DRAG":        "DRAG",
    "DRAG":            "DRAG",
    "DRAG POWER":      "DRAG",
    "DRAG MAX":        "DRAG",
    "HANDLING POWER":  "DRAG",
    # Skip — not rendered
    "PE":              "_SKIP",
    "LINE CAPACITY":   "_SKIP",
    "LINE CAP":        "_SKIP",
    "SPOOL":           "_SKIP",
    "RETRIEVE PER TURN": "_SKIP",
    "MONO KAPASITI":   "_SKIP",          # Malay
    "BRAID KAPASITI":  "_SKIP",          # Malay
    "KAPASITI":        "_SKIP",          # Malay
    "KNOB TYPE":       "_SKIP",
    "BRAID CAPACITY":  "_SKIP",
    "MONO CAPACITY":   "_SKIP",
    "BRAID LINE":      "_SKIP",
    "MONO LINE":       "_SKIP",
}

# Fuzzy regex patterns for specs with NO separator (e.g. "Weight (g) 312")
# Each tuple: (compiled regex, canonical key)
# Regex must match the LABEL portion; group(1) captures the VALUE.
_P6_FUZZY_PATTERNS = [
    # Weight — "Weight (g) 312", "Weight 312 Gram"
    (re.compile(
        r'(?:weight|berat|reel\s*weight|body\s*weight|net\s*weight|wt)\b'
        r'(?:\s*\([^)]*\))?\s+'                       # optional (g), (kg) etc.
        r'(.+)', re.I), "WEIGHT"),
    # Gear ratio — "Gear ratio 6.2"
    (re.compile(
        r'(?:gear\s*ratio|nisbah\s*gear|ratio|ration)\b'
        r'(?:\s*\([^)]*\))?\s+'
        r'(.+)', re.I), "RATIO"),
    # Max drag — "Max drag force 9", "Maximum drag force (Kg) 13"
    (re.compile(
        r'(?:max(?:imum)?\s*drag(?:\s*force)?|drag\s*(?:max|power)?)\b'
        r'(?:\s*\([^)]*\))?\s+'
        r'(.+)', re.I), "DRAG"),
    # Ball bearings — "Ball/roller bearing 8/1"
    (re.compile(
        r'(?:ball[/\s]*(?:roller\s*)?bear(?:ing|ings)?|bear(?:ing|ings)|bb)\b'
        r'(?:\s*\([^)]*\))?\s+'
        r'(.+)', re.I), "BB"),
    # Skip patterns — "Max line winding length ...", "Line capacity ..."
    (re.compile(
        r'(?:line\s*cap|winding|retriev|crank|capacity|kapasiti|knob)', re.I),
        "_SKIP"),
]


def _parse_specs_paste(raw: str) -> list:
    """Parse multi-model specs text into list of dicts.

    Supports multiple seller-page formats:
      1. Line-per-spec:   MODEL: SLR1000 / BALL BEARINGS: 5 / ...
      2. Bare model name:  CRZ3000 (no MODEL: prefix, next lines are specs)
      3. Bullet-separated: BTL IV 1000 \u2022 Ratio : 5.2 \u2022 Weight : 222g
      4. Circle-separated: Weight (g) 400 \u25cf Gear ratio 6.2 \u25cf ...
      5. Comma-separated:  Weight (g) 312, Gear ratio 6.2, Max drag 9
      6. Dash separators:  Gear Ratio - 4.2 (when no colon present)
      7. No separator:     Weight (g) 312  (fuzzy regex label matching)
      8. Malay labels:     NISBAH GEAR, BERAT, KAPASITI, etc.

    Returns: [{"MODEL": "SLR1000", "BB": "5", "RATIO": "5.2:1", ...}, ...]
    Each dict has keys: MODEL, BB, RATIO, WEIGHT, DRAG (missing = "\u2014")
    """
    if not raw or not raw.strip():
        return []

    models = []
    current = {}

    # --- Pre-process: split lines on bullets / circles / commas ---
    segments = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # Split on bullet \u2022 or black circle \u25cf
        if "\u2022" in line or "\u25cf" in line:
            for part in re.split("[\u2022\u25cf]", line):
                part = part.strip()
                if part:
                    segments.append(part)
        # Split on ", " (comma-space) when line has 3+ items (spec list)
        elif ", " in line and line.count(", ") >= 2:
            for part in line.split(", "):
                part = part.strip()
                if part:
                    segments.append(part)
        else:
            segments.append(line)

    for seg in segments:
        # Skip line-capacity detail lines (". 0.25mm / 310m")
        if seg.startswith("."):
            continue

        # --- Strip leading dash prefix ("- GEAR RATIO:" or "-BALL BEARING:") ---
        # Only strip if segment contains a colon (spec line), not for feature bullets
        core = seg
        if re.match(r"^-\s*", seg) and ":" in seg:
            core = re.sub(r"^-\s*", "", seg).strip()

        # --- Strip trailing parenthetical (supplementary info) ---
        # e.g. "Pattern 2500 (6.2:1 - Max winding 84cm)" -> "Pattern 2500"
        core = re.sub(r"\s*\(.*\)\s*$", "", core).strip()
        if not core:
            continue

        # --- 1. Try colon separator ---
        label = value = None
        if ":" in core:
            l, _, v = core.partition(":")
            l_up = l.strip().upper()
            v_s = v.strip()

            # MODEL / MODEL NUMBER / MODEL NO prefix → new model
            if (l_up == "MODEL" or l_up.startswith("MODEL ")) and v_s:
                if current:
                    models.append(current)
                current = {"MODEL": v_s.upper()}
                continue

            # Strip parenthetical from label: "WEIGHT(G)" → "WEIGHT"
            l_clean = re.sub(r"\s*\(.*\)", "", l_up).strip()

            # Known alias via colon (try exact, then cleaned)
            c = _P6_PARSE_ALIASES.get(l_up) or _P6_PARSE_ALIASES.get(l_clean)
            if not c:
                # Prefix match: "LINE CAPACITY PE (NO./M)" starts with "LINE CAPACITY"
                for alias_key, alias_val in _P6_PARSE_ALIASES.items():
                    if l_up.startswith(alias_key) or l_clean.startswith(alias_key):
                        c = alias_val
                        break
            if c:
                if c != "_SKIP" and c in P6_SPEC_KEYS and v_s:
                    current[c] = v_s
                continue

        # --- 2. Try dash separator (only if label is a known alias) ---
        if "-" in core:
            l, _, v = core.partition("-")
            l_up = l.strip().upper()
            if l_up in _P6_PARSE_ALIASES:
                c = _P6_PARSE_ALIASES[l_up]
                if c != "_SKIP" and c in P6_SPEC_KEYS:
                    current[c] = v.strip()
                continue

        # --- 3. Fuzzy regex matching (no separator needed) ---
        # For specs like "Weight (g) 312", "Ball/roller bearing 8/1"
        fuzzy_matched = False
        for pat, fcanon in _P6_FUZZY_PATTERNS:
            m = pat.search(core)
            if m:
                fuzzy_matched = True
                if fcanon != "_SKIP" and fcanon in P6_SPEC_KEYS:
                    val = m.group(1).strip() if m.lastindex else ""
                    if val:
                        current[fcanon] = val
                break
        if fuzzy_matched:
            continue

        # --- 4. Bare model name ---
        # Strip trailing colon (e.g. "Pattern 4500:")
        candidate = core.rstrip(":").strip().upper()
        # Filter out section headers, feature bullets, marketing text
        _NOISE_EXACT = {"FEATURES", "FEATURE", "SPECIFICATIONS", "SPECS",
                        "SPEC", "DESCRIPTION", "DETAILS", "OVERVIEW",
                        "HIGHLIGHTS", "STANDARD", "OPTIONAL", "INCLUDED",
                        "ACCESSORIES"}
        _NOISE_WORDS = {"SPINNING REEL", "FISHING REEL", "BAITCASTING",
                        "BAITCAST REEL", "REEL SERIES"}
        if (1 < len(candidate) <= 50
                and any(c.isalpha() for c in candidate)
                and not candidate.startswith("-")
                and "SPECIFICATION" not in candidate
                and candidate not in _NOISE_EXACT
                and not any(nw in candidate for nw in _NOISE_WORDS)):
            if current:
                models.append(current)
            current = {"MODEL": candidate}

    # Don't forget the last model
    if current:
        models.append(current)

    # Fill missing specs with "\u2014"
    for m in models:
        for k in P6_SPEC_KEYS:
            if k not in m:
                m[k] = "\u2014"
        if "MODEL" not in m:
            m["MODEL"] = "\u2014"

    # Remove junk models with NO spec data (all "\u2014") — caused by
    # marketing text, section headers, feature bullets being misidentified
    models = [m for m in models
              if any(m.get(k, "\u2014") != "\u2014" for k in P6_SPEC_KEYS)]

    return models


def _render_p6(
    watermark_img:  Optional[Image.Image],
    slot_used:      str,
    theme:          str,
    brand:          str,
    model:          str,
    chip1:          str,
    chip2:          str,
    chip3:          str,
    specs_data:     list,
) -> bytes:
    """Compose a 1024×1024 P6 Specs Comparison Table card.

    Layout:
      - Theme background + optional ghost reel watermark
      - Top-left: brand + model
      - Top-right: "FULL SPECS" pill badge
      - Translucent table with column headers + data rows
      - Bottom: chip bar (BB / gear ratio / max drag)
    """
    W, H       = 1024, 1024
    pad        = P6_TABLE_PAD
    top_pad    = 36
    tc         = get_theme_colors(theme)
    text_color = tc["text"]
    chip_text_color = tc["chip_text"]
    divider_color   = tc["divider"]
    is_dark    = (theme or "").lower() in _P3_DARK_THEMES

    # ── Background ────────────────────────────────────────────────────
    _tc = get_theme_colors(theme)
    canvas = _make_gradient_bg_fast(W, H, _tc.get("p1_grad_start", (13, 92, 92)), _tc.get("p1_grad_end", (7, 56, 56)))

    # ── Ghost reel watermark (same approach as P8) ────────────────────
    if watermark_img is not None:
        target_h = int(H * 0.80)
        wm_scale = target_h / watermark_img.height
        wm_w     = max(1, int(watermark_img.width * wm_scale))
        wm_h     = target_h
        wm = watermark_img.resize((wm_w, wm_h), Image.LANCZOS)
        wm = wm.filter(ImageFilter.GaussianBlur(radius=P6_WATERMARK_BLUR))
        r_ch, g_ch, b_ch, a_ch = wm.split()
        a_ch = a_ch.point(lambda p: int(p * P6_WATERMARK_ALPHA / 255))
        wm = Image.merge("RGBA", (r_ch, g_ch, b_ch, a_ch))
        wx = int(W * 0.65) - wm_w // 2
        wy = (H - wm_h) // 2
        if wx < 0:
            wm = wm.crop((-wx, 0, wm_w, wm_h))
            wx = 0
        if wy < 0:
            wm = wm.crop((0, -wy, wm.width, wm_h))
            wy = 0
        canvas.alpha_composite(wm, (wx, wy))

    # Radial glow — centre
    draw_radial_glow(canvas, W // 2, H // 2)
    draw = ImageDraw.Draw(canvas)

    # ── Brand + model (top-left) ──────────────────────────────────────
    header_max_w = int(W * 0.55) - pad
    brand_text   = (brand or "").strip().upper()
    brand_font, brand_text = fit_text(
        draw, brand_text, max_w=header_max_w,
        start_size=40, min_size=24, loader=load_font_regular)
    brand_h = text_size(draw, brand_text, brand_font)[1]

    model_text = (model or "").strip().upper()
    model_font, model_text = fit_text(
        draw, model_text, max_w=header_max_w,
        start_size=72, min_size=28, loader=load_font_bold)

    draw_text_align_left(draw, pad, top_pad, brand_text, brand_font, text_color)
    draw_text_align_left(draw, pad, top_pad + brand_h - 4, model_text, model_font, text_color)

    # ── "FULL SPECS" pill (top-right) ─────────────────────────────────
    pill_font = load_font_bold(22)
    pill_text = "FULL SPECS"
    pw, ph    = text_size(draw, pill_text, pill_font)
    # Build pill rect from right edge
    pill_r    = W - pad
    pill_l    = pill_r - pw - P6_TAG_PAD_X * 2
    pill_t    = top_pad + 8
    pill_b    = pill_t + ph + P6_TAG_PAD_Y * 2
    pill_rect = [pill_l, pill_t, pill_r, pill_b]
    draw.rounded_rectangle(pill_rect, radius=20, outline=text_color[:3], width=2)
    # Centre text inside pill using anchor='mm'
    pill_cx   = (pill_l + pill_r) // 2
    pill_cy   = (pill_t + pill_b) // 2
    draw.text((pill_cx, pill_cy), pill_text, font=pill_font, fill=text_color, anchor='mm')

    # ── Chip bar (bottom) ─────────────────────────────────────────────
    chip_font  = load_font_bold(32)
    features   = [(chip1 or "").strip(), (chip2 or "").strip(), (chip3 or "").strip()]
    features   = [c for c in features if c]

    chip_groups = []
    for i, c in enumerate(features):
        tw, th    = text_size(draw, c, chip_font)
        icon_file = CHIP_ICONS.get(i)
        icon      = load_icon(icon_file, ICON_SIZE) if icon_file else None
        icon_w    = ICON_SIZE if icon else 0
        group_w   = (icon_w + ICON_TEXT_GAP + tw) if icon else tw
        group_h   = max(ICON_SIZE, th)
        chip_groups.append((c, tw, th, group_w, group_h, icon, icon_w))

    total_chips_w = sum(gw for _, _, _, gw, _, _, _ in chip_groups) + \
                    max(0, len(chip_groups) - 1) * (CHIP_GAP_X + DIVIDER_WIDTH) if chip_groups else 0
    chip_row_h    = max((gh for _, _, _, _, gh, _, _ in chip_groups), default=0)

    # Position chip bar at bottom with safe margin
    CHIP_BOTTOM_MARGIN = 24
    chip_y_top    = H - CHIP_BOTTOM_MARGIN - chip_row_h if chip_groups else H
    chip_y_center = chip_y_top + chip_row_h // 2

    # ── Specs table ───────────────────────────────────────────────────
    n_models  = len(specs_data)
    all_cols  = ["MODEL"] + P6_SPEC_KEYS   # 5 columns
    n_cols    = len(all_cols)
    table_x0  = pad
    table_x1  = W - pad
    table_w   = table_x1 - table_x0

    # Calculate available height for table (between header and chip bar)
    table_bottom_limit = chip_y_top - 20 if chip_groups else H - 40
    table_top  = P6_TABLE_TOP

    if n_models == 0:
        # ── No specs data — show fallback message ────────────────────
        no_data_font = load_font_bold(36)
        nd_text = "NO SPECS DATA"
        ndw, ndh = text_size(draw, nd_text, no_data_font)
        faded = (*text_color[:3], 120)
        draw.text(((W - ndw) // 2, (H - ndh) // 2), nd_text, font=no_data_font, fill=faded)
    else:
        # Dynamic row height: fit all models + header in available space
        avail_h    = table_bottom_limit - table_top
        row_h      = min(P6_DATA_ROW_H, max(28, (avail_h - P6_COL_HEADER_H) // n_models))
        table_h    = P6_COL_HEADER_H + row_h * n_models

        # Column widths: MODEL gets 30%, rest split evenly
        model_col_w = int(table_w * 0.30)
        spec_col_w  = (table_w - model_col_w) // (n_cols - 1)

        col_xs = [table_x0]   # MODEL column start
        for i in range(1, n_cols):
            col_xs.append(table_x0 + model_col_w + spec_col_w * (i - 1))

        # Translucent table background pill
        bg_fill = _P3_SPEC_BG_DARK if is_dark else _P3_SPEC_BG_LIGHT
        spec_bg = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        spec_bg_draw = ImageDraw.Draw(spec_bg)
        spec_bg_draw.rounded_rectangle(
            (table_x0, table_top, table_x1, table_top + table_h),
            radius=P6_TABLE_RADIUS, fill=bg_fill,
        )
        canvas.alpha_composite(spec_bg)
        draw = ImageDraw.Draw(canvas)

        header_fill = (255, 255, 255, 180) if is_dark else (60, 60, 60, 200)
        label_fill  = (255, 255, 255, 160) if is_dark else (60, 60, 60, 180)
        value_fill  = text_color

        # ── Column header row ─────────────────────────────────────────
        header_font = load_font_bold(20)
        header_y    = table_top + (P6_COL_HEADER_H - 20) // 2

        for ci, col_key in enumerate(all_cols):
            label = P6_COL_LABELS.get(col_key, col_key)
            cx    = col_xs[ci] + 12
            draw.text((cx, header_y), label, font=header_font, fill=header_fill)

        # Divider below header
        div_y = table_top + P6_COL_HEADER_H - 1
        draw.line([(table_x0 + 12, div_y), (table_x1 - 12, div_y)],
                  fill=divider_color, width=1)

        # ── Data rows ─────────────────────────────────────────────────
        # Adaptive font size based on number of models
        if n_models <= 4:
            data_font_size = 26
        elif n_models <= 6:
            data_font_size = 23
        else:
            data_font_size = 19

        data_font       = load_font_regular(data_font_size)
        model_name_font = load_font_bold(data_font_size)
        data_top        = table_top + P6_COL_HEADER_H

        for ri, m in enumerate(specs_data):
            ry = data_top + ri * row_h
            text_y = ry + (row_h - data_font_size) // 2

            for ci, col_key in enumerate(all_cols):
                val = m.get(col_key, "—")
                cx  = col_xs[ci] + 12
                # MODEL column uses bold font
                f = model_name_font if ci == 0 else data_font
                # Truncate if too wide
                col_w_avail = (col_xs[ci + 1] if ci + 1 < n_cols else table_x1) - col_xs[ci] - 20
                tw, _ = text_size(draw, val, f)
                if tw > col_w_avail and len(val) > 4:
                    while tw > col_w_avail and len(val) > 4:
                        val = val[:-1]
                        tw, _ = text_size(draw, val + "…", f)
                    val = val + "…"
                draw.text((cx, text_y), val, font=f, fill=value_fill)

            # Row divider (not after last row)
            if ri < n_models - 1:
                rd_y = ry + row_h - 1
                draw.line([(table_x0 + 12, rd_y), (table_x1 - 12, rd_y)],
                          fill=divider_color, width=1)

    # ── Draw chip bar ─────────────────────────────────────────────────
    if chip_groups:
        cur_x = (W - total_chips_w) // 2
        for idx, (c, tw, th, gw, gh, icon, icon_w) in enumerate(chip_groups):
            if icon:
                icon_y = chip_y_center - ICON_SIZE // 2
                canvas.alpha_composite(icon, (cur_x, icon_y))
                draw   = ImageDraw.Draw(canvas)
                text_x = cur_x + icon_w + ICON_TEXT_GAP
            else:
                text_x = cur_x
            bbox   = draw.textbbox((0, 0), c, font=chip_font)
            text_h = bbox[3] - bbox[1]
            text_y = chip_y_center - text_h // 2 - bbox[1]
            draw.text((text_x, text_y), c, font=chip_font, fill=chip_text_color)
            cur_x += gw
            if idx < len(chip_groups) - 1:
                div_x     = cur_x + CHIP_GAP_X // 2
                div_y_top = chip_y_center - int(chip_row_h * 0.35)
                div_y_bot = chip_y_center + int(chip_row_h * 0.35)
                draw.line([(div_x, div_y_top), (div_x, div_y_bot)],
                          fill=divider_color, width=DIVIDER_WIDTH)
                cur_x += CHIP_GAP_X + DIVIDER_WIDTH

    # ── Output ────────────────────────────────────────────────────────
    out = BytesIO()
    canvas.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


@app.get("/render/p6")
def render_p6(
    product_key:  str = Query(""),
    group:        str = Query("A"),
    brand:        str = Query(""),
    model:        str = Query(""),
    theme:        str = Query("grey"),
    chip1:        str = Query(""),
    chip2:        str = Query(""),
    chip3:        str = Query(""),
    specs_paste:  str = Query(""),
):
    """
    P6 — Specs Comparison Table.
    Parses specs_paste text (multi-model specs from seller page) into a
    structured comparison table with ghost reel watermark.
    If specs_paste is empty, renders a "NO SPECS DATA" fallback card.
    """
    import traceback

    # Parse specs text
    specs_data = _parse_specs_paste(specs_paste)

    # Load optional ghost watermark (same as P8 — never raises)
    watermark_img, slot_used = None, ""
    if product_key:
        watermark_img, slot_used = _load_p8_watermark(product_key, group)

    try:
        png = _render_p6(
            watermark_img, slot_used, theme,
            brand, model, chip1, chip2, chip3,
            specs_data,
        )
    except Exception as e:
        raise HTTPException(status_code=500,
                            detail=f"P6 render error: {e}\n{traceback.format_exc()}")
    return Response(content=png, media_type="image/png",
                    headers={"X-Specs-Models": str(len(specs_data)),
                             "X-Watermark-Slot": slot_used})


# =====================================================================
# P7 — Bundle & Box Proof
# =====================================================================

P7_LEFT_W            = 480    # left column / right panel boundary (cutout mode)
P7_BADGE_PAD_X       = 12
P7_BADGE_PAD_Y       = 6
P7_GRAD_START        = 500    # y where bottom gradient starts (photo mode)
P7_MAX_ITEMS         = 5      # max bundle bullets before "+ N more"
P7_REEL_HEIGHT_RATIO = 0.72   # reel fills 72% of card height (measured after alpha-crop)


def _load_p7_hero(product_key: str, group: str) -> tuple:
    """Waterfall: P7_BOX_PHOTO → P7_BOX_CUTOUT → P2_ANGLE_CUTOUT → P3_DETAIL_CUTOUT → P1_HERO_CUTOUT."""
    bucket = os.environ.get("R2_BUCKET")
    if not bucket:
        raise HTTPException(status_code=500, detail="Missing R2_BUCKET")
    s3 = r2_client()
    slots = ["P7_BOX_PHOTO", "P7_BOX_CUTOUT",
             "P2_ANGLE_CUTOUT", "P3_DETAIL_CUTOUT", "P1_HERO_CUTOUT"]
    pk_norm = _normalize_pk(product_key)
    for slot in slots:
        for ext in ("png", "jpg", "jpeg"):
            key = f"raw/{pk_norm}/{group}/{slot}.{ext}"
            try:
                obj  = s3.get_object(Bucket=bucket, Key=key)
                data = obj["Body"].read()
                img  = Image.open(BytesIO(data)).convert("RGBA")
                return img, slot
            except Exception:
                continue
    raise HTTPException(status_code=404,
                        detail=f"No hero found for {product_key}/{group}")


def _parse_bundle_items(raw: str) -> list:
    """Split pipe-separated bundle string, cap at P7_MAX_ITEMS with overflow line."""
    items = [i.strip() for i in raw.split("|") if i.strip()]
    if len(items) > P7_MAX_ITEMS:
        extra = len(items) - (P7_MAX_ITEMS - 1)
        items = items[: P7_MAX_ITEMS - 1] + [f"+ {extra} more"]
    return items


def _render_p7(
    hero:           Image.Image,
    slot_used:      str,
    theme:          str,
    brand:          str,
    model:          str,
    bundle_items:   str,
    warranty_type:  str,
    trust_badges:   str,
    packaging_note: str,
    badge:          str,
) -> bytes:
    W, H     = 1024, 1024
    pad      = 48
    top_pad  = 36
    is_photo = (slot_used == "P7_BOX_PHOTO")

    # ── Background ────────────────────────────────────────────────────
    if is_photo:
        # Full-bleed: scale-to-cover, center crop
        scale = max(W / hero.width, H / hero.height)
        rw    = max(1, int(hero.width  * scale))
        rh    = max(1, int(hero.height * scale))
        bg    = hero.resize((rw, rh), Image.LANCZOS)
        ox    = (rw - W) // 2
        oy    = (rh - H) // 2
        canvas = bg.crop((ox, oy, ox + W, oy + H)).copy()
        text_color = (255, 255, 255, 255)

        # Left scrim — dark panel so white text stays readable
        scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(scrim).rectangle(
            [0, 0, P7_LEFT_W + 120, H], fill=(0, 0, 0, 150))
        canvas.alpha_composite(scrim)

        # Bottom gradient — extra depth under bundle items
        grad_h = H - P7_GRAD_START
        grad   = Image.new("RGBA", (W, grad_h), (0, 0, 0, 0))
        gd     = ImageDraw.Draw(grad)
        for y in range(grad_h):
            a = int(80 * y / grad_h)
            gd.line([(0, y), (W, y)], fill=(0, 0, 0, a))
        canvas.alpha_composite(grad, (0, P7_GRAD_START))

    else:
        # Theme background
        _tc = get_theme_colors(theme)
        canvas = _make_gradient_bg_fast(W, H, _tc.get("p1_grad_start", (13, 92, 92)), _tc.get("p1_grad_end", (7, 56, 56)))
        tc         = get_theme_colors(theme)
        text_color = tc["text"]

        # Radial glow on right side
        draw_radial_glow(canvas, P7_LEFT_W + (W - P7_LEFT_W) // 2, H // 2)

        # Crop transparent padding so ratio measures the actual reel body, not whitespace.
        if hero.mode == 'RGBA':
            bbox = hero.split()[3].getbbox()   # alpha channel bounding box
            if bbox:
                hero = hero.crop(bbox)

        # Scale reel to 82% of card height; centre at 65% of canvas width.
        # Width is intentionally unconstrained — PIL clips any right-side overflow.
        target_h = int(H * P7_REEL_HEIGHT_RATIO)           # 839 px @ 1024
        scale    = target_h / hero.height
        rw = max(1, int(hero.width  * scale))
        rh = target_h
        hero_rs  = hero.resize((rw, rh), Image.LANCZOS)
        hx = int(W * 0.65) - rw // 2                       # centre reel at 65% of canvas
        hy = max(0, (H - rh) // 2 - 40)                    # 40px above vertical centre
        canvas.alpha_composite(hero_rs, (max(0, hx), max(0, hy)))

    draw = ImageDraw.Draw(canvas)

    # ── Trust badge pills (top-right, max 2) ─────────────────────────
    badge_list = [b.strip() for b in trust_badges.split("|") if b.strip()][:2]
    badge_font = load_font_bold(18)
    bx = W - pad
    by = top_pad
    for btxt in reversed(badge_list):
        bw, bh = text_size(draw, btxt, badge_font)
        pill_w = bw + P7_BADGE_PAD_X * 2
        pill_h = bh + P7_BADGE_PAD_Y * 2
        bx    -= pill_w
        pill_rect = [bx, by, bx + pill_w, by + pill_h]
        draw.rounded_rectangle(pill_rect, radius=12,
                                fill=STICKER_FILL[:3] + (220,),
                                outline=STICKER_OUTLINE[:3], width=1)
        draw.text((bx + pill_w // 2, by + pill_h // 2),
                  btxt, font=badge_font, fill=STICKER_TEXT, anchor='mm')
        bx -= 8   # gap between pills

    # ── Brand + model ─────────────────────────────────────────────────
    text_max_w = P7_LEFT_W - pad * 2
    brand_text = (brand or "").strip().upper()
    brand_font, brand_text = fit_text(
        draw, brand_text, max_w=text_max_w,
        start_size=36, min_size=22, loader=load_font_regular)
    brand_h = text_size(draw, brand_text, brand_font)[1]

    model_text = (model or "").strip().upper()
    model_font, model_text = fit_text(
        draw, model_text, max_w=text_max_w,
        start_size=72, min_size=28, loader=load_font_bold)
    model_h = text_size(draw, model_text, model_font)[1]

    y = top_pad
    draw_text_align_left(draw, pad, y, brand_text, brand_font, text_color)
    y += brand_h + 2
    draw_text_align_left(draw, pad, y, model_text, model_font, text_color)
    y += model_h + 32

    # ── "WHAT'S IN THE BOX" header ────────────────────────────────────
    witb_font = load_font_bold(22)
    witb_text = "WHAT'S IN THE BOX"
    witb_h    = text_size(draw, witb_text, witb_font)[1]
    draw.text((pad, y), witb_text, font=witb_font,
              fill=(*text_color[:3], 200))
    y += witb_h + 8

    # Thin rule under header
    draw.line([(pad, y), (P7_LEFT_W - pad, y)],
              fill=(*text_color[:3], 80), width=1)
    y += 12

    # ── Bundle item bullets ───────────────────────────────────────────
    items     = _parse_bundle_items(bundle_items)
    item_font = load_font_regular(30)    # +15% for Shopee thumbnail legibility
    item_h    = text_size(draw, "Ag", item_font)[1]
    for item in items:
        draw.text((pad, y), "\u2022  " + item, font=item_font, fill=text_color)
        y += item_h + 10                # +4px breathing room between bullets

    y += 10

    # ── Warranty type ─────────────────────────────────────────────────
    if warranty_type and warranty_type.strip():
        wt_font = load_font_bold(26)    # bolder + larger — trust signal, not footnote
        wt_text = warranty_type.strip()
        draw.text((pad, y), wt_text, font=wt_font,
                  fill=(*text_color[:3], 210))
        y += text_size(draw, wt_text, wt_font)[1] + 8

    # ── Packaging note ────────────────────────────────────────────────
    if packaging_note and packaging_note.strip():
        pn_font = load_font_regular(18)
        draw.text((pad, y), packaging_note.strip(), font=pn_font,
                  fill=(*text_color[:3], 120))

    # ── "ACTUAL ITEM" watermark for non-box fallback slots ───────────
    if not is_photo and slot_used not in ("P7_BOX_PHOTO", "P7_BOX_CUTOUT"):
        ai_font = load_font_regular(16)
        ai_text = "ACTUAL ITEM"
        aiw, aih = text_size(draw, ai_text, ai_font)
        draw.text(
            (P7_LEFT_W + (W - P7_LEFT_W - aiw) // 2, H - pad - aih),
            ai_text, font=ai_font, fill=(*text_color[:3], 80))

    # ── Output ────────────────────────────────────────────────────────
    out = BytesIO()
    canvas.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


@app.get("/render/p7")
def render_p7(
    product_key:    str = Query(...),
    group:          str = Query("A"),
    brand:          str = Query(""),
    model:          str = Query(""),
    theme:          str = Query("grey"),
    bundle_items:   str = Query(""),
    warranty_type:  str = Query(""),
    trust_badges:   str = Query(""),
    packaging_note: str = Query(""),
    badge:          str = Query(""),
):
    """
    P7 — Bundle & Box Proof card.
    Waterfall: P7_BOX_PHOTO -> P7_BOX_CUTOUT -> P2_ANGLE_CUTOUT -> P3_DETAIL_CUTOUT -> P1_HERO_CUTOUT.
    BOX_PHOTO slot -> full-bleed background + left scrim.
    All other slots -> theme background with asset on right panel.
    """
    hero, slot_used = _load_p7_hero(product_key, group)
    png = _render_p7(
        hero, slot_used, theme,
        brand, model,
        bundle_items, warranty_type, trust_badges, packaging_note, badge,
    )
    return Response(content=png, media_type="image/png",
                    headers={"X-Used-Slot": slot_used})


# ==========================================================================
# P8 — STORE PROMISE / GUARANTEE CARD
# ==========================================================================

P8_WATERMARK_ALPHA = 32     # reel ghost opacity (0-255); ~12% visible
P8_WATERMARK_BLUR  = 8      # GaussianBlur radius for soft ghost effect
P8_MAX_PROMISES    = 6      # max promise bullet lines before truncation
P8_HEADER_SIZE     = 88     # starting font size for header (fit_text shrinks if needed)


def _load_p8_watermark(product_key: str, group: str) -> tuple:
    """Optional reel watermark for P8.  Tries P1->P2->P3 cutout slots in R2.
    Returns (PIL RGBA image, slot_name) or (None, '').  NEVER raises."""
    try:
        bucket = os.environ.get("R2_BUCKET")
        if not bucket:
            return None, ""
        s3 = r2_client()
        pk_norm = _normalize_pk(product_key)
        for slot in ("P1_HERO_CUTOUT", "P2_ANGLE_CUTOUT", "P3_DETAIL_CUTOUT"):
            for ext in ("png", "jpg", "jpeg"):
                key = f"raw/{pk_norm}/{group}/{slot}.{ext}"
                try:
                    obj  = s3.get_object(Bucket=bucket, Key=key)
                    data = obj["Body"].read()
                    img  = Image.open(BytesIO(data)).convert("RGBA")
                    return img, slot
                except Exception:
                    continue
        return None, ""
    except Exception:
        return None, ""


P8_DEFAULT_PROMISES = [
    "READY STOCK",
    "100% ORIGINAL",
    "WARRANTY SUPPORT",
    "SHIPS IN 24H",
    "SAFE PACKING",
]

def _parse_promise_lines(raw: str) -> list:
    """Split pipe-separated promise string; cap at P8_MAX_PROMISES items.
    Falls back to P8_DEFAULT_PROMISES when input is empty."""
    items = [i.strip() for i in raw.split("|") if i.strip()][:P8_MAX_PROMISES]
    return items if items else P8_DEFAULT_PROMISES


def _render_p8(
    watermark_img: Optional[Image.Image],
    slot_used:     str,
    theme:         str,
    brand:         str,
    model:         str,
    promise_lines: str,
    small_print:   str,
    badge:         str,
) -> bytes:
    """Compose a 1024x1024 P8 Store Promise card and return raw PNG bytes.

    Layout:
      - Theme background + optional radial glow
      - Ghost reel watermark (right-centre, blurred, ~12% alpha) if R2 asset exists
      - Top-left: brand + model
      - Header: SHOP GUARANTEE (or badge text) in large bold + gold accent line
      - Promise bullets with checkmark prefix (bold, uppercase)
      - Optional small_print at bottom-left
    """
    W, H       = 1024, 1024
    pad        = 56
    tc         = get_theme_colors(theme)
    text_color = tc["text"]

    # ── Background ────────────────────────────────────────────────────
    _tc = get_theme_colors(theme)
    canvas = _make_gradient_bg_fast(W, H, _tc.get("p1_grad_start", (13, 92, 92)), _tc.get("p1_grad_end", (7, 56, 56)))

    # Radial glow — right-side depth
    draw_radial_glow(canvas, W * 2 // 3, H // 2)

    # ── Ghost reel watermark ──────────────────────────────────────────
    if watermark_img is not None:
        # Scale watermark to 88% of canvas height
        target_h  = int(H * 0.88)
        wm_scale  = target_h / watermark_img.height
        wm_w      = max(1, int(watermark_img.width  * wm_scale))
        wm_h      = target_h
        wm = watermark_img.resize((wm_w, wm_h), Image.LANCZOS)

        # Soften for ghost effect
        wm = wm.filter(ImageFilter.GaussianBlur(radius=P8_WATERMARK_BLUR))

        # Reduce alpha channel uniformly
        r_ch, g_ch, b_ch, a_ch = wm.split()
        a_ch = a_ch.point(lambda p: int(p * P8_WATERMARK_ALPHA / 255))
        wm   = Image.merge("RGBA", (r_ch, g_ch, b_ch, a_ch))

        # Centre watermark at 65% of canvas width
        wx = int(W * 0.65) - wm_w // 2
        wy = (H - wm_h) // 2

        # Pre-clip left/top overflow so alpha_composite stays in-bounds
        if wx < 0:
            wm = wm.crop((-wx, 0, wm_w, wm_h))
            wx = 0
        if wy < 0:
            wm = wm.crop((0, -wy, wm.width, wm_h))
            wy = 0

        canvas.alpha_composite(wm, (wx, wy))

    draw = ImageDraw.Draw(canvas)
    y    = pad

    # ── Brand ─────────────────────────────────────────────────────────
    brand_text = (brand or "").strip().upper()
    if brand_text:
        b_font = load_font_regular(30)
        draw_text_align_left(draw, pad, y, brand_text, b_font,
                             (*text_color[:3], 180))
        y += text_size(draw, brand_text, b_font)[1] + 4

    # ── Model ─────────────────────────────────────────────────────────
    model_text = (model or "").strip().upper()
    if model_text:
        m_font, model_text = fit_text(
            draw, model_text, max_w=W - pad * 2,
            start_size=60, min_size=24, loader=load_font_bold)
        draw_text_align_left(draw, pad, y, model_text, m_font, text_color)
        y += text_size(draw, model_text, m_font)[1] + 20
    elif brand_text:
        y += 12

    y += 20  # breathing room before header

    # ── Header ("SHOP GUARANTEE" or badge) ────────────────────────────
    header_raw  = (badge.strip() if badge.strip() else "SHOP GUARANTEE").upper()
    h_font, header_text = fit_text(
        draw, header_raw, max_w=W - pad * 2,
        start_size=P8_HEADER_SIZE, min_size=40, loader=load_font_bold)
    draw_text_align_left(draw, pad, y, header_text, h_font, text_color)
    # Use bbox[3] (actual bottom pixel) not bbox[3]-bbox[1] (height) to avoid
    # the gold-line-through-text bug when top bearing (bbox[1]) > 0 for large fonts
    y += draw.textbbox((0, 0), header_text, font=h_font)[3] + 18

    # Gold accent line beneath header
    draw.line([(pad, y), (pad + 140, y)],
              fill=STICKER_FILL[:3] + (210,), width=4)
    y += 32

    # ── Promise bullets ────────────────────────────────────────────────
    items  = _parse_promise_lines(promise_lines)
    p_font = load_font_bold(44)
    p_h    = text_size(draw, "Ag", p_font)[1]

    # Distribute bullets evenly in remaining space so card never looks blank
    sp_reserve = 48 if (small_print and small_print.strip()) else 0
    avail_h    = (H - pad - sp_reserve) - y
    n          = max(1, len(items))
    gap        = max(24, min(72, (avail_h - n * p_h) // (n + 1)))

    y += gap // 2   # half-gap indent before first bullet

    # ☒ checkbox drawn with PIL (font-independent), black, vertically centred
    cb    = int(p_h * 0.62)   # checkbox size proportional to line height
    ins   = max(5, cb // 5)   # inset for the X strokes
    cb_lw = 2                  # line width for box + X
    # Measure actual top bearing so checkbox aligns with visible text, not bbox origin
    _tb   = draw.textbbox((0, 0), "Ag", font=p_font)
    cb_fill = (*text_color[:3], 255)   # black (matches theme text colour)
    for item in items:
        cb_x = pad
        # Centre checkbox on visible text: offset by top bearing + centre within text height
        cb_y = y + _tb[1] + (_tb[3] - _tb[1] - cb) // 2
        # Outer box
        draw.rectangle([cb_x, cb_y, cb_x + cb, cb_y + cb],
                       outline=cb_fill, width=cb_lw)
        # X strokes inside box
        draw.line([(cb_x + ins, cb_y + ins),
                   (cb_x + cb - ins, cb_y + cb - ins)],
                  fill=cb_fill, width=cb_lw)
        draw.line([(cb_x + cb - ins, cb_y + ins),
                   (cb_x + ins, cb_y + cb - ins)],
                  fill=cb_fill, width=cb_lw)
        draw.text((pad + cb + 14, y), item.upper(), font=p_font, fill=text_color)
        y += p_h + gap

    # ── Small print ───────────────────────────────────────────────────
    if small_print and small_print.strip():
        sp_font = load_font_regular(18)
        sp_text = small_print.strip()
        _, sp_h = text_size(draw, sp_text, sp_font)
        draw.text((pad, H - pad - sp_h), sp_text,
                  font=sp_font, fill=(*text_color[:3], 100))

    # ── Output ────────────────────────────────────────────────────────
    out = BytesIO()
    canvas.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


@app.get("/render/p8")
def render_p8(
    product_key:   str = Query(...),
    group:         str = Query("A"),
    brand:         str = Query(""),
    model:         str = Query(""),
    theme:         str = Query("grey"),
    promise_lines: str = Query(
        ""),
    small_print:   str = Query(""),
    badge:         str = Query(""),
):
    """
    P8 -- Store Promise / Guarantee card.
    Faint reel watermark (right-centre) from R2 if available:
      P1_HERO_CUTOUT -> P2_ANGLE_CUTOUT -> P3_DETAIL_CUTOUT.
    Promise bullets with checkmark prefix.  No mandatory hero image.
    """
    wm_img, slot_used = _load_p8_watermark(product_key, group)
    png = _render_p8(
        wm_img, slot_used, theme,
        brand, model,
        promise_lines, small_print, badge,
    )
    return Response(content=png, media_type="image/png",
                    headers={"X-Used-Slot": slot_used or "none"})


# ---------- /prep-video-frame ----------
@app.get("/prep-video-frame")
def prep_video_frame(
    image_url: str,
    save_key: str = "",
    style: str = "studio_dark",
    theme: str = "teal",
    width: int = 1080,
    height: int = 1920,
):
    """
    Compose a video input frame: cutout on dark studio background at 9:16.
    Downloads cutout from image_url, centres it on a dark gradient bg,
    optionally saves to R2 at save_key.
    """
    import urllib.request

    # Download cutout
    try:
        req = urllib.request.Request(image_url, headers={"User-Agent": "compositor/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            cutout_data = resp.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to download cutout: {e}")

    cutout = Image.open(BytesIO(cutout_data)).convert("RGBA")
    cutout = trim_transparent(cutout, pad=0)

    # Build dark studio background (locked Phase 1 rule: dark studio for video)
    bg = Image.new("RGBA", (width, height), (15, 15, 20, 255))

    # Add subtle gradient overlay for depth
    gradient = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(gradient)
    for y in range(height):
        # Dark at top/bottom, slightly lighter in middle
        t = abs(y - height * 0.45) / (height * 0.55)
        alpha = int(min(t * 60, 60))
        draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
    bg = Image.alpha_composite(bg, gradient)

    # Scale cutout to fit: 70% of frame height, maintain aspect ratio
    max_h = int(height * 0.70)
    max_w = int(width * 0.85)
    cw, ch = cutout.size
    scale = min(max_w / cw, max_h / ch)
    new_w = int(cw * scale)
    new_h = int(ch * scale)
    cutout_resized = cutout.resize((new_w, new_h), Image.LANCZOS)

    # Centre on canvas
    x = (width - new_w) // 2
    y = (height - new_h) // 2
    bg.paste(cutout_resized, (x, y), cutout_resized)

    # Convert to RGB (no alpha for video frame)
    frame = bg.convert("RGB")

    # Save to R2 if save_key provided
    buf = BytesIO()
    frame.save(buf, format="PNG", optimize=True)
    png_bytes = buf.getvalue()

    if save_key:
        bucket = os.environ.get("R2_BUCKET")
        if bucket:
            try:
                s3 = r2_client()
                s3.put_object(Bucket=bucket, Key=save_key, Body=png_bytes, ContentType="image/png")
            except Exception as e:
                pass  # Non-fatal — frame still returned

    return Response(content=png_bytes, media_type="image/png",
                    headers={"X-Save-Key": save_key or "none"})


# ---------- /prep-post-image ----------
@app.get("/prep-post-image")
def prep_post_image(
    hero_key: str = "",
    image_url: str = "",
    save_key: str = "",
    style: str = "gradient",
    theme: str = "teal",
    width: int = 1080,
    height: int = 1080,
    brand: str = "",
    model: str = "",
    size: str = "",
    bg_mode: str = "gradient",
):
    """
    Compose a social-post image: product cutout on themed background at 1:1.
    If image_url provided, downloads from URL (e.g. BiRefNet output).
    Otherwise downloads from R2 via hero_key.
    Saves to R2 at save_key, returns JSON with r2_url.
    """
    import urllib.request

    # 1. Load cutout — prefer image_url (bg-removed), fallback to R2 hero_key
    if image_url:
        try:
            req = urllib.request.Request(image_url, headers={"User-Agent": "compositor/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to download image: {e}")
    elif hero_key:
        data = r2_get_object_bytes(hero_key)
    else:
        raise HTTPException(status_code=400, detail="Either hero_key or image_url required")
    cutout = Image.open(BytesIO(data)).convert("RGBA")
    cutout = trim_transparent(cutout, pad=0)

    # 2. Build background — brighter gradient for post (not P1 dark gradient)
    _tc = get_theme_colors(theme)
    # Use lighter gradient: blend P1 start color with white for brighter tone
    gs = _tc.get("p1_grad_start", (13, 92, 92))
    ge = _tc.get("p1_grad_end", (7, 56, 56))
    # Brighten by 60% towards white
    bright_start = tuple(min(255, int(c + (255 - c) * 0.3)) for c in gs)
    bright_end = tuple(min(255, int(c + (255 - c) * 0.1)) for c in ge)
    bg = _make_gradient_bg_fast(width, height, bright_start, bright_end)

    # 3. Scale cutout to fit: 70% of height (make room for text at bottom)
    max_h = int(height * 0.70)
    max_w = int(width * 0.85)
    cw, ch = cutout.size
    scale = min(max_w / cw, max_h / ch)
    new_w, new_h = int(cw * scale), int(ch * scale)
    cutout_resized = cutout.resize((new_w, new_h), Image.LANCZOS)

    # 4. Position product — offset up to leave space for text at bottom
    x = (width - new_w) // 2
    y = int(height * 0.08)  # 8% from top

    # 5. Drop shadow — dark blurred copy behind product
    shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shadow_offset_x, shadow_offset_y = 8, 12
    shadow_alpha = cutout_resized.split()[3]  # get alpha channel
    shadow_fill = Image.new("RGBA", cutout_resized.size, (0, 0, 0, 100))
    shadow_fill.putalpha(shadow_alpha)
    shadow.paste(shadow_fill, (x + shadow_offset_x, y + shadow_offset_y))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=15))
    bg = Image.alpha_composite(bg.convert("RGBA"), shadow)

    # 6. Subtle rim glow behind product — theme-colored halo
    glow_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_color = _tc.get("p1_grad_start", (13, 92, 92))
    glow_fill = Image.new("RGBA", (new_w + 40, new_h + 40), (*glow_color, 60))
    glow_fill = glow_fill.filter(ImageFilter.GaussianBlur(radius=30))
    glow_layer.paste(glow_fill, (x - 20, y - 20))
    bg = Image.alpha_composite(bg, glow_layer)

    # 7. Paste product cutout on top
    bg.paste(cutout_resized, (x, y), cutout_resized)

    # 8. Vignette — subtle edge darkening
    vignette = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    vig_draw = ImageDraw.Draw(vignette)
    for i in range(50):
        alpha = int(30 * (1 - i / 50))
        vig_draw.rectangle([i, i, width - i, height - i], outline=(0, 0, 0, alpha))
    bg = Image.alpha_composite(bg, vignette)

    # 9. Brand + Model text at bottom
    if brand or model:
        draw = ImageDraw.Draw(bg)
        text_y = int(height * 0.82)
        # Brand name — bold, larger
        if brand:
            brand_font = load_font_bold(38)
            brand_text = brand.upper()
            bw, bh = text_size(draw, brand_text, brand_font)
            bx = (width - bw) // 2
            # White text with shadow
            draw_text_with_shadow(draw, bx, text_y, brand_text, brand_font,
                                  fill=(255, 255, 255, 240),
                                  shadow_color=(0, 0, 0, 120), shadow_offset=2)
            text_y += bh + 4
        # Model name — regular, slightly smaller
        if model:
            model_font = load_font_regular(30)
            model_text = model.upper()
            mw, mh = text_size(draw, model_text, model_font)
            mx = (width - mw) // 2
            draw_text_with_shadow(draw, mx, text_y, model_text, model_font,
                                  fill=(255, 255, 255, 200),
                                  shadow_color=(0, 0, 0, 100), shadow_offset=1)

    # 10. Save to R2
    frame = bg.convert("RGB")
    buf = BytesIO()
    frame.save(buf, format="PNG", optimize=True)
    png_bytes = buf.getvalue()

    r2_url = ""
    if save_key:
        bucket = os.environ.get("R2_BUCKET")
        if bucket:
            try:
                s3 = r2_client()
                s3.put_object(Bucket=bucket, Key=save_key, Body=png_bytes, ContentType="image/png")
                r2_url = f"https://rerender-clean-studio.onrender.com/r2/get-image?key={save_key}"
            except Exception:
                pass

    # 6. Return JSON (TG: Send Post expects $json.r2_url)
    return {"ok": True, "r2_url": r2_url, "save_key": save_key}


# =====================================================================
# /remove-bg — Background Removal Utility
# Fetches image from URL, removes background using rembg, returns
# transparent PNG. Used by Supplier Scraper to convert website product
# photos into compositor-ready cutouts.
# =====================================================================

_rembg_session = None

def _get_rembg_session():
    """Lazy-load rembg session (downloads model on first call)."""
    global _rembg_session
    if _rembg_session is None:
        try:
            from rembg import new_session
            _rembg_session = new_session("u2netp")
            log.info("rembg session loaded (u2netp)")
        except ImportError:
            raise HTTPException(status_code=500, detail="rembg not installed")
    return _rembg_session


@app.get("/remove-bg")
def remove_bg_get(url: str = Query(..., description="Image URL to remove background from")):
    """
    GET /remove-bg?url=<image_url>
    Downloads image from URL, removes background, returns transparent PNG.
    Uses u2netp model (fast, lightweight).
    """
    from rembg import remove

    # 1. Fetch image
    try:
        resp = httpx.get(url, timeout=30.0, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch image: {e}")

    # 2. Open and remove background
    try:
        img = Image.open(BytesIO(resp.content)).convert("RGBA")
        session = _get_rembg_session()
        result = remove(img, session=session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Background removal failed: {e}")

    # 3. Return transparent PNG
    buf = BytesIO()
    result.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@app.post("/remove-bg")
async def remove_bg_post(file: UploadFile = File(...)):
    """
    POST /remove-bg (multipart file upload)
    Removes background from uploaded image, returns transparent PNG.
    """
    from rembg import remove

    data = await file.read()
    try:
        img = Image.open(BytesIO(data)).convert("RGBA")
        session = _get_rembg_session()
        result = remove(img, session=session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Background removal failed: {e}")

    buf = BytesIO()
    result.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")
