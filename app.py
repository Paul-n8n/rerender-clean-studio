import os
import re
from io import BytesIO
from typing import List, Optional

import boto3
from botocore.config import Config
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from PIL import Image, ImageDraw, ImageFont, ImageFilter

app = FastAPI()


@app.get("/")
def root():
    return {"ok": True, "service": "rerender-clean-studio"}


VERSION = "P1+P2+P3+P4+P5+P6+P7+P8 v2026-03-16c"

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


@app.post("/r2/upload")
async def upload_to_r2(key: str = Query(...), file: UploadFile = File(...)):
    """Upload an image to R2 at the given key path."""
    bucket = os.environ.get("R2_BUCKET")
    if not bucket:
        raise HTTPException(status_code=500, detail="Missing R2_BUCKET")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    # Validate it's an image (just check PIL can open it)
    try:
        img = Image.open(BytesIO(data))
        img.load()  # force decode without verify() which can reject valid JPEGs
    except Exception:
        raise HTTPException(status_code=400, detail="Not a valid image file")

    s3 = r2_client()
    content_type = file.content_type or "image/png"
    s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)

    return {"ok": True, "key": key, "size": len(data)}


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
    chip4: str = "",
    chip5: str = "",
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

    features = [(chip1 or "").strip(), (chip2 or "").strip(),
                 (chip4 or "").strip(), (chip5 or "").strip()]
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
    # --- Compute model text bottom for chip placement ---
    model_h = text_size(draw, model_text, model_font)[1]
    model_bottom = model_y + model_h

    # --- needed_below: only CTA (chips moved above hero) ---
    needed_below = CTA_GAP_Y + cta_h + BOTTOM_SAFE

    # --- Draw header text ---
    draw_text_align_left(draw, header_left, header_top, brand_text, brand_font, text_color)
    draw_text_align_left(draw, header_left, model_y,    model_text, model_font, text_color)

    # --- Draw badge (chip3 / size) at top-right ---
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

    # --- Measure chip text width to auto-separate from hero ---
    max_chip_tw = max((tw for _, tw, _, _, _, _, _ in chip_groups), default=0)
    CHIP_HERO_GAP = 40           # minimum px gap between widest chip and hero left edge
    chip_right_edge = header_left + max_chip_tw + CHIP_HERO_GAP

    # --- Hero sizing: fit into the right zone (between chip_right_edge and canvas edge) ---
    hero_w, hero_h = hero.size
    right_zone_w   = W - chip_right_edge - 20   # available width for hero
    TARGET_H_RATIO = 0.68
    target_h       = int(H * TARGET_H_RATIO)
    scale_h        = target_h / hero_h
    scale_w        = right_zone_w / hero_w
    scale          = min(scale_h, scale_w)       # fit whichever is tighter
    new_w          = max(1, int(hero_w * scale))
    new_h          = max(1, int(hero_h * scale))
    hero_rs        = hero.resize((new_w, new_h), resample=Image.LANCZOS)

    # Position hero slightly left of right-zone centre (30% into the zone)
    right_zone_left_bias = chip_right_edge + int(right_zone_w * 0.30)
    px             = right_zone_left_bias - new_w // 2
    px             = max(px, chip_right_edge)
    px             = min(px, W - new_w - 10)
    py             = int(H * 0.22)
    max_hero_bottom = H - needed_below
    if py + new_h > max_hero_bottom:
        py = max_hero_bottom - new_h
    hero_bottom = py + new_h

    # --- Glow + Hero composite ---
    glow_cx = px + new_w // 2
    glow_cy = py + new_h // 2
    draw_radial_glow(canvas, glow_cx, glow_cy)
    draw = ImageDraw.Draw(canvas)

    canvas.alpha_composite(hero_rs, (px, py))
    draw = ImageDraw.Draw(canvas)

    # --- Draw chips LEFT-aligned, upper-third of reel area ---
    CHIP_LINE_GAP  = 6           # space between stacked chip lines
    total_chip_h = sum(gh for _, _, _, _, gh, _, _ in chip_groups) + CHIP_LINE_GAP * max(0, len(chip_groups) - 1)
    # Align chips at ~40% of reel height (upper body area)
    chip_anchor_y = py + int(new_h * 0.40)
    chip_cur_y = chip_anchor_y - total_chip_h // 2

    for idx, (c, tw, th, gw, gh, icon, icon_w) in enumerate(chip_groups):
        line_center_y = chip_cur_y + gh // 2
        text_x = header_left
        bbox   = draw.textbbox((0, 0), c, font=chip_font)
        text_h = bbox[3] - bbox[1]
        text_y = line_center_y - text_h // 2 - bbox[1]
        draw.text((text_x, text_y), c, font=chip_font, fill=chip_text_color)
        chip_cur_y += gh + CHIP_LINE_GAP

    # --- CTA pill below hero ---
    cta_x0 = (W - cta_w) // 2
    cta_y0 = hero_bottom + CTA_GAP_Y
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
    chip4: str = Query(""),
    chip5: str = Query(""),
    theme: str = Query("yellow"),
):
    png = _render_product(_load_hero(key), theme, brand, model, chip1, chip2, chip3, chip4, chip5)
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
    canvas = load_bg(theme).resize((W, H), Image.LANCZOS)
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
    feat_y += title_h + 40

    if tag_text:
        tx0, ty0 = pad, feat_y
        tx1, ty1 = tx0 + tag_w, ty0 + tag_h
        draw_rounded_rect(draw, (tx0, ty0, tx1, ty1), radius=8, fill=tag_bg)
        draw.text((tx0 + P4_TAG_PAD_X, ty0 + P4_TAG_PAD_Y), tag_text, font=tag_font, fill=tag_fg)
        feat_y += tag_h + 28

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

    if is_inhand:
        # ── Full-bleed photo mode ──────────────────────────────────────
        canvas = _scale_to_cover(hero.convert("RGBA"), W, H)
        draw   = ImageDraw.Draw(canvas)
        text_color = (255, 255, 255, 255)

        # Bottom gradient
        bot_grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        bg_draw  = ImageDraw.Draw(bot_grad)
        bot_h    = int(H * P5_GRAD_BOTTOM_H)
        for y in range(bot_h):
            a = int(210 * (y / bot_h) ** 1.6)
            bg_draw.line([(0, H - bot_h + y), (W, H - bot_h + y)], fill=(0, 0, 0, a))
        canvas.alpha_composite(bot_grad)

        # Top gradient
        top_grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        tg_draw  = ImageDraw.Draw(top_grad)
        top_h    = int(H * P5_GRAD_TOP_H)
        for y in range(top_h):
            a = int(170 * (1 - y / top_h) ** 1.8)
            tg_draw.line([(0, y), (W, y)], fill=(0, 0, 0, a))
        canvas.alpha_composite(top_grad)
        draw = ImageDraw.Draw(canvas)

    else:
        # ── Composite mode (fallback cutout on themed background) ──────
        # Use themed bg so cutout edge anti-aliasing blends correctly
        canvas = load_bg(theme).resize((W, H), Image.LANCZOS)
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
    canvas = load_bg(theme).resize((W, H), Image.LANCZOS)

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
        canvas = load_bg(theme).resize((W, H), Image.LANCZOS)
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


def _parse_promise_lines(raw: str) -> list:
    """Split pipe-separated promise string; cap at P8_MAX_PROMISES items."""
    return [i.strip() for i in raw.split("|") if i.strip()][:P8_MAX_PROMISES]


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
    canvas = load_bg(theme).resize((W, H), Image.LANCZOS)

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
        "READY STOCK|100% ORIGINAL|WARRANTY SUPPORT|SHIPS IN 24H|SECURE CHECKOUT"),
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
