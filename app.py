import os
from io import BytesIO
from typing import List, Optional

import boto3
from botocore.config import Config
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from PIL import Image, ImageDraw, ImageFont, ImageFilter

app = FastAPI()


@app.get("/")
def root():
    return {"ok": True, "service": "rerender-clean-studio"}


VERSION = "P1+P2+P3+P4 v2026-02-28b"

# ======================== STICKER UI STANDARDS ========================
STICKER_RADIUS = 14
STICKER_BORDER_W = 3
STICKER_FILL = (245, 204, 74, 255)
STICKER_OUTLINE = (20, 20, 20, 255)
STICKER_TEXT = (20, 20, 20, 255)

# ======================== THEME COLOR MAPPING ============================
THEME_COLORS = {
    "yellow": {
        "text": (20, 20, 20, 255),
        "chip_text": (30, 30, 30, 255),
        "divider": (80, 80, 80, 180),
        "sticker_outline": (20, 20, 20, 255),
    },
    "grey": {
        "text": (20, 20, 20, 255),
        "chip_text": (30, 30, 30, 255),
        "divider": (80, 80, 80, 180),
        "sticker_outline": (20, 20, 20, 255),
    },
    "navy": {
        "text": (255, 255, 255, 255),
        "chip_text": (240, 240, 240, 255),
        "divider": (200, 200, 200, 180),
        "sticker_outline": (20, 20, 20, 255),
    },
    "teal": {
        "text": (255, 255, 255, 255),
        "chip_text": (240, 240, 240, 255),
        "divider": (200, 200, 200, 180),
        "sticker_outline": (20, 20, 20, 255),
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


def fit_text_p3_model(draw, text, max_w, loader=load_font_bold):
    """
    Three-phase model name fitting for P3 cards.
      Phase 1 – single line, shrink 210 → 80 (step 2)
      Phase 2 – two-line word-wrap, shrink 136 → 52 (step 2),
                 most-balanced split (minimises max line width)
      Phase 3 – truncate at size 80 with "…"
    Returns (font, line1, line2_or_None).
    """
    # ── Phase 1: single line ──────────────────────────────────────────
    for size in range(210, 80 - 1, -2):
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


# =====================================================================
# Shared rendering engine — used by both /render/p1 and /render/p2
# P1 and P2 use identical layout; only the source image key differs.
# Layout: text top-left, size badge top-right, hero right-centre,
#         chips + CTA bottom-centre — all on the theme background.
# =====================================================================

def _render_product(
    hero: Image.Image,
    theme: str,
    brand: str,
    model: str,
    chip1: str,
    chip2: str,
    chip3: str,
) -> bytes:
    """Compose a 1000×1000 product card and return raw PNG bytes."""
    W, H = 1000, 1000
    canvas = load_bg(theme).resize((W, H), Image.LANCZOS)
    draw = ImageDraw.Draw(canvas)

    tc = get_theme_colors(theme)
    text_color      = tc["text"]
    chip_text_color = tc["chip_text"]
    divider_color   = tc["divider"]

    pad          = 56
    top_pad      = 44
    BOTTOM_SAFE  = 28
    CHIP_TOP_GAP = 16
    CTA_GAP_Y    = 20
    header_left  = pad
    header_top   = top_pad
    header_max_w = int(W * 0.65) - header_left

    brand_text = (brand or "").strip().upper()
    brand_font, brand_text = fit_text(draw, brand_text, max_w=header_max_w,
                                      start_size=56, min_size=34, loader=load_font_regular)
    brand_h = text_size(draw, brand_text, brand_font)[1]

    model_text = (model or "").strip().upper()
    model_font, model_text = fit_text(draw, model_text, max_w=header_max_w,
                                      start_size=200, min_size=72, loader=load_font_bold)
    model_y = header_top + brand_h - 6

    features = [(chip1 or "").strip(), (chip2 or "").strip()]
    features = [c for c in features if c]

    chip_font  = load_font_bold(36)
    cta_text   = "READY STOCK \u2022 FAST SHIP"
    cta_font   = load_font_bold(18)
    cta_pad_x  = 14
    cta_pad_y  = 6
    cta_tw, cta_th = text_size(draw, cta_text, cta_font)
    cta_w = cta_tw + cta_pad_x * 2
    cta_h = cta_th + cta_pad_y * 2

    chip_groups = []
    for i, c in enumerate(features):
        tw, th     = text_size(draw, c, chip_font)
        icon_file  = CHIP_ICONS.get(i)
        icon       = load_icon(icon_file, ICON_SIZE) if icon_file else None
        icon_w     = ICON_SIZE if icon else 0
        group_w    = (icon_w + ICON_TEXT_GAP + tw) if icon else tw
        group_h    = max(ICON_SIZE, th)
        chip_groups.append((c, tw, th, group_w, group_h, icon, icon_w))

    chip_row_h     = max((gh for _, _, _, _, gh, _, _ in chip_groups), default=0)
    num_dividers   = max(0, len(chip_groups) - 1)
    total_chips_w  = sum(gw for _, _, _, gw, _, _, _ in chip_groups)
    total_chips_w += num_dividers * (CHIP_GAP_X + DIVIDER_WIDTH)
    needed_below   = CHIP_TOP_GAP + chip_row_h + CTA_GAP_Y + cta_h + BOTTOM_SAFE

    hero_w, hero_h = hero.size
    TARGET_H_RATIO = 0.62
    target_h       = int(H * TARGET_H_RATIO)
    scale          = target_h / hero_h
    new_w          = max(1, int(hero_w * scale))
    new_h          = max(1, int(hero_h * scale))
    hero_rs        = hero.resize((new_w, new_h), resample=Image.LANCZOS)

    px = (W - new_w) // 2 + 100
    px = max(px, pad)
    px = min(px, W - new_w - 10)
    py = int(H * 0.22)
    max_hero_bottom = H - needed_below
    if py + new_h > max_hero_bottom:
        py = max_hero_bottom - new_h
        py = max(py, top_pad + 20)
    hero_bottom = py + new_h

    draw_text_align_left(draw, header_left, header_top, brand_text, brand_font, text_color)
    draw_text_align_left(draw, header_left, model_y,    model_text, model_font, text_color)

    size_text = (chip3 or "").strip()
    if size_text:
        badge_font = load_font_bold(38)
        bpx, bpy   = 22, 12
        tw, th     = text_size(draw, size_text, badge_font)
        bw, bh     = tw + bpx * 2, th + bpy * 2
        bx1        = W - pad
        by0        = top_pad + 12
        bx0        = bx1 - bw
        by1        = by0 + bh
        draw_sticker_pill(draw, bx0, by0, bx1, by1, size_text, badge_font)

    glow_cx = px + new_w // 2
    glow_cy = py + new_h // 2
    draw_radial_glow(canvas, glow_cx, glow_cy)
    draw = ImageDraw.Draw(canvas)

    canvas.alpha_composite(hero_rs, (px, py))
    draw = ImageDraw.Draw(canvas)

    chip_y_top    = hero_bottom + CHIP_TOP_GAP
    chip_y_center = chip_y_top + chip_row_h // 2
    chip_start_x  = (W - total_chips_w) // 2
    cur_x         = chip_start_x
    for idx, (c, tw, th, gw, gh, icon, icon_w) in enumerate(chip_groups):
        if icon:
            icon_y = chip_y_center - ICON_SIZE // 2
            canvas.alpha_composite(icon, (cur_x, icon_y))
            draw = ImageDraw.Draw(canvas)
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
    cta_x0 = (W - cta_w) // 2
    cta_y0 = chips_bottom + CTA_GAP_Y
    cta_y0 = min(cta_y0, H - BOTTOM_SAFE - cta_h)
    cta_x1 = cta_x0 + cta_w
    cta_y1 = cta_y0 + cta_h
    draw_sticker_pill(draw, cta_x0, cta_y0, cta_x1, cta_y1, cta_text, cta_font)

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
    theme: str = Query("yellow"),
):
    png = _render_product(_load_hero(key), theme, brand, model, chip1, chip2, chip3)
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
# /render/p3 — Spec Card (Technical Validation Slide)
# Layout: Brand + Model header, size-range badge, hero (55% height),
#         3 highlight chips (BB · gear ratio · max drag), spec table
#         (3 rows: gear ratio, max drag, weight).  Line capacity omitted
#         — varies per size; surfaced as chip3 instead.
# Canvas: 1024×1024, themed background (same assets as P1).
# =====================================================================

# Hero occupies 50% of canvas height — smaller than P1 to fit spec table
P3_FIT_RATIO    = 0.55
P3_HERO_X_SHIFT = 50           # slight right shift (px) to mirror P1 composition

# Spec table geometry
P3_SPEC_ROW_H      = 48           # height of each spec data row (px)  — was 44
P3_SPEC_PAD_Y      = 12           # inner vertical padding top/bottom    — was 10
P3_SPEC_HEADER_H   = 30           # height of "TECH SPECS" header row inside pill
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
    canvas = load_bg(theme).resize((W, H), Image.LANCZOS)
    draw   = ImageDraw.Draw(canvas)

    tc              = get_theme_colors(theme)
    text_color      = tc["text"]
    chip_text_color = tc["chip_text"]
    divider_color   = tc["divider"]

    pad          = 56
    top_pad      = 44
    BOTTOM_SAFE  = 28
    CHIP_TOP_GAP = 14
    SPEC_GAP_Y   = 32

    # ── Header: brand + model (top-left) ──────────────────────────────
    header_left  = pad
    header_top   = top_pad
    header_max_w = int(W * 0.62) - header_left

    brand_text = (brand or "").strip().upper()
    brand_font, brand_text = fit_text(
        draw, brand_text, max_w=header_max_w,
        start_size=60, min_size=32, loader=load_font_regular,
    )
    brand_h = text_size(draw, brand_text, brand_font)[1]

    model_text = (model or "").strip().upper()
    model_font, model_line1, model_line2 = fit_text_p3_model(
        draw, model_text, max_w=header_max_w, loader=load_font_bold,
    )
    model_y      = header_top + brand_h - 6
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

    # Position: slight right offset, leave room below for chips + spec table
    needed_below = CHIP_TOP_GAP + chip_row_h + SPEC_GAP_Y + spec_table_h + BOTTOM_SAFE
    px = (W - new_w) // 2 + P3_HERO_X_SHIFT
    px = max(px, pad)
    px = min(px, W - new_w - 10)
    py = int(H * 0.18)
    max_hero_bottom = H - needed_below
    if py + new_h > max_hero_bottom:
        py = max(top_pad + 20, max_hero_bottom - new_h)
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
):
    """
    P3 — spec card. Themed background, brand/model header, size-range
    badge, hero at 55% height, 3 highlight chips, 3-row spec table
    (Gear Ratio / Max Drag / Weight).
    chip3 = max drag range shown as scannable chip.
    line_capacity accepted for forward-compat but not rendered.
    """
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
P4_HERO_X_FRAC = 0.36   # hero left edge starts at 36% of W (right-anchored)
P4_HERO_Y_BIAS = -0.06  # nudge hero upward (fraction of H) to expose spool
P4_TEXT_W_FRAC = 0.42   # text block uses left 42% of canvas
P4_FEAT_Y_FRAC = 0.52   # Feature block starts at 52% down canvas
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
    canvas = load_bg(theme).resize((W, H), Image.LANCZOS)
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
    tag_font = load_font_bold(28)
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
    draw_text_align_left(draw, pad, top_pad,               brand_text, brand_font, text_color)
    draw_text_align_left(draw, pad, top_pad + brand_h - 4, model_text, model_font, text_color)

    # Thin separator line below model
    sep_y   = top_pad + brand_h - 4 + model_h + 10
    sep_end = int(W * P4_TEXT_W_FRAC) - 10
    sep_col = (text_color[0], text_color[1], text_color[2], 70)
    draw.line([(pad, sep_y), (sep_end, sep_y)], fill=sep_col, width=2)

    # ── Feature block ─────────────────────────────────────────────────
    feat_y = int(H * P4_FEAT_Y_FRAC)

    draw_text_align_left(draw, pad, feat_y, title_text, title_font, text_color)
    feat_y += title_h + 10

    if tag_text:
        tx0, ty0 = pad, feat_y
        tx1, ty1 = tx0 + tag_w, ty0 + tag_h
        draw_rounded_rect(draw, (tx0, ty0, tx1, ty1), radius=8, fill=tag_bg)
        draw.text((tx0 + P4_TAG_PAD_X, ty0 + P4_TAG_PAD_Y), tag_text, font=tag_font, fill=tag_fg)
        feat_y += tag_h + 12

    body_col = (text_color[0], text_color[1], text_color[2], 210)
    for line in body_lines:
        draw_text_align_left(draw, pad, feat_y, line, body_font, body_col)
        feat_y += body_lh + 4

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
