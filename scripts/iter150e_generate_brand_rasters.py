"""Iter150E · Brand raster derivative generator.

Reads the authoritative owner-supplied TRUKVIA master PNG and produces
the authorised raster derivatives via lossless PIL LANCZOS resampling.
No redraw, no re-trace, no recolor, no reinterpretation.  Every output
is a proportional fit of the master onto a transparent RGBA canvas
(square derivatives are letterboxed to preserve wordmark + TM).

Outputs:
  frontend/public/brand/
    favicon-16.png              square, contain-fit
    favicon-32.png              square, contain-fit
    favicon-48.png              square, contain-fit
    favicon.ico                 multi-image .ico (16, 32, 48)
    apple-touch-icon-180.png    square, contain-fit, opaque BG for iOS
    android-chrome-192.png      square, contain-fit
    android-chrome-512.png      square, contain-fit
    trukvia-mark-64.png         wordmark, height 64 px (sidebar 2x)
    trukvia-mark-128.png        wordmark, height 128 px
    trukvia-wordmark-64.png     wordmark, 64 px tall
    trukvia-wordmark-128.png    wordmark, 128 px tall
    trukvia-login-mark.png      login page, height 128 px x 640 px wide

  backend/assets/brand/
    trukvia-pdf-header.png      PDF header raster, height ~830 px
                                (~40 mm printed @ 528 dpi source)
"""
from __future__ import annotations
from pathlib import Path
from PIL import Image

MASTER = Path("/app/frontend/public/brand/TRUKVIA_master.png")
FE_OUT = Path("/app/frontend/public/brand")
BE_OUT = Path("/app/backend/assets/brand")
IOS_BG = (255, 255, 255, 255)


def _open() -> Image.Image:
    im = Image.open(MASTER).convert("RGBA")
    return im


def _fit_square(im: Image.Image, size: int, opaque_bg=None) -> Image.Image:
    """Proportional fit onto a transparent (or opaque_bg) square canvas.
    Preserves the entire wordmark + TM by contain-fitting."""
    w, h = im.size
    ratio = min(size / w, size / h)
    new_w, new_h = max(1, int(round(w * ratio))), max(1, int(round(h * ratio)))
    resized = im.resize((new_w, new_h), Image.LANCZOS)
    if opaque_bg is not None:
        canvas = Image.new("RGBA", (size, size), opaque_bg)
    else:
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    off = ((size - new_w) // 2, (size - new_h) // 2)
    canvas.paste(resized, off, resized)
    return canvas


def _fit_rect(im: Image.Image, target_h: int, max_w: int | None = None) -> Image.Image:
    """Scale proportionally to `target_h` height.  If `max_w` is given,
    the derivative is placed centred on a transparent canvas of
    `max_w x target_h`; otherwise the natural width is preserved."""
    w, h = im.size
    ratio = target_h / h
    new_w, new_h = max(1, int(round(w * ratio))), target_h
    resized = im.resize((new_w, new_h), Image.LANCZOS)
    if max_w is None:
        return resized
    canvas = Image.new("RGBA", (max_w, target_h), (0, 0, 0, 0))
    off_x = max(0, (max_w - new_w) // 2)
    # Contain-fit: if the natural width overflows, keep the LANCZOS-
    # resized image cropped centred (never redraw / never distort).
    if new_w > max_w:
        crop_x = (new_w - max_w) // 2
        resized = resized.crop((crop_x, 0, crop_x + max_w, target_h))
        canvas.paste(resized, (0, 0), resized)
    else:
        canvas.paste(resized, (off_x, 0), resized)
    return canvas


def main() -> None:
    FE_OUT.mkdir(parents=True, exist_ok=True)
    BE_OUT.mkdir(parents=True, exist_ok=True)
    im = _open()

    # Square favicon set (transparent for browsers, opaque for iOS).
    f16 = _fit_square(im, 16)
    f32 = _fit_square(im, 32)
    f48 = _fit_square(im, 48)
    f180 = _fit_square(im, 180, opaque_bg=IOS_BG)
    f192 = _fit_square(im, 192)
    f512 = _fit_square(im, 512)

    f16.save(FE_OUT / "favicon-16.png", "PNG", optimize=True)
    f32.save(FE_OUT / "favicon-32.png", "PNG", optimize=True)
    f48.save(FE_OUT / "favicon-48.png", "PNG", optimize=True)
    f180.save(FE_OUT / "apple-touch-icon-180.png", "PNG", optimize=True)
    f192.save(FE_OUT / "android-chrome-192.png", "PNG", optimize=True)
    f512.save(FE_OUT / "android-chrome-512.png", "PNG", optimize=True)

    # Multi-image .ico bundling 16/32/48.
    f48.save(FE_OUT / "favicon.ico", format="ICO",
             sizes=[(16, 16), (32, 32), (48, 48)])

    # Wordmark rect derivatives.
    _fit_rect(im, 64).save(FE_OUT / "trukvia-mark-64.png", "PNG", optimize=True)
    _fit_rect(im, 128).save(FE_OUT / "trukvia-mark-128.png", "PNG", optimize=True)
    _fit_rect(im, 64).save(FE_OUT / "trukvia-wordmark-64.png", "PNG", optimize=True)
    _fit_rect(im, 128).save(FE_OUT / "trukvia-wordmark-128.png", "PNG", optimize=True)

    # Login mark — 128 px tall on a 640 px wide canvas.
    _fit_rect(im, 128, max_w=640).save(
        FE_OUT / "trukvia-login-mark.png", "PNG", optimize=True)

    # PDF header raster — ~830 px tall (≈ 40 mm printed @ 528 dpi).
    _fit_rect(im, 830).save(
        BE_OUT / "trukvia-pdf-header.png", "PNG", optimize=True)

    # Report the manifest.
    out = sorted([*FE_OUT.glob("*"), *BE_OUT.glob("*")])
    for p in out:
        try:
            with Image.open(p) as ii:
                print(f"{p}  {ii.size}  {ii.mode}  {p.stat().st_size} B")
        except Exception:
            print(f"{p}  ({p.stat().st_size} B, non-image)")


if __name__ == "__main__":
    main()
