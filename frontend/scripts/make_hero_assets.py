"""Turn ONE photograph you are allowed to use into the landing-page hero assets.

    pip install pillow
    python scripts/make_hero_assets.py path\\to\\photo.jpg --alt "Two volunteers hand out rice sacks to families outside a community hall" ^
        --credit "Photo: Your Name / Organization" --license "Used with written permission" --source-url https://example.org/photo

What it does: fixes the camera rotation, crops to 4:3, writes 1600 px and 800 px JPEG + WebP versions, STRIPS all metadata (GPS location, camera, dates),
and writes public/images/hero/hero.json, which the landing page reads. Until that file exists the page shows live open needs instead of a photo.
It refuses to run without a description (alt text) and a licence statement, because the page must always be able to say who may use the photo and what it shows."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageOps

SIZES = {"": (1600, 1200), "small": (800, 600)}
MAX_KB = 250


def build(src: Path, out: Path, alt: str, credit: str, licence: str, source_url: str) -> dict:
    img = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    if img.width < 1200:
        raise SystemExit(f"The photo is only {img.width}px wide; use one at least 1200px wide so it stays sharp on large screens.")
    out.mkdir(parents=True, exist_ok=True)
    files, sizes = {}, {}
    for name, (w, h) in SIZES.items():
        crop = ImageOps.fit(img, (w, h), method=Image.LANCZOS, centering=(0.5, 0.4))     # 4:3, slightly above centre so faces are not cut
        stem = f"hero-{w}"
        crop.save(out / f"{stem}.jpg", "JPEG", quality=82, optimize=True, progressive=True)   # no exif argument: metadata is dropped
        crop.save(out / f"{stem}.webp", "WEBP", quality=78, method=6)
        files[name or "main"] = stem
        sizes[stem] = {ext: (out / f"{stem}.{ext}").stat().st_size // 1024 for ext in ("jpg", "webp")}
    meta = {"image": f"{files['main']}.jpg", "webp": f"{files['main']}.webp", "small": f"{files['small']}.jpg", "small_webp": f"{files['small']}.webp",
            "width": SIZES[""][0], "height": SIZES[""][1], "alt": alt.strip(), "credit": credit.strip(), "license": licence.strip(), "source_url": source_url.strip()}
    (out / "hero.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for stem, s in sizes.items():
        for ext, kb in s.items():
            if kb > MAX_KB:
                print(f"note: {stem}.{ext} is {kb} KB; consider a simpler photo or lower quality for faster loading", file=sys.stderr)
    return {"meta": meta, "sizes_kb": sizes}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo", type=Path)
    ap.add_argument("--alt", required=True, help="what the photo shows, for screen readers")
    ap.add_argument("--license", required=True, help="who may use it and how, e.g. 'CC0', 'Unsplash License', 'Used with written permission'")
    ap.add_argument("--credit", default="")
    ap.add_argument("--source-url", default="")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "public" / "images" / "hero")
    a = ap.parse_args()
    if len(a.alt.strip()) < 20:
        raise SystemExit("--alt must describe the photo (at least 20 characters).")
    if not a.photo.is_file():
        raise SystemExit(f"Photo not found: {a.photo}")
    r = build(a.photo, a.out, a.alt, a.credit, a.license, a.source_url)
    print(json.dumps(r["sizes_kb"], indent=2)); print(f"Wrote {a.out / 'hero.json'}")


if __name__ == "__main__":
    main()
