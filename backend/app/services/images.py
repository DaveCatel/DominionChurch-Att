"""Profile photos: turn whatever a member uploads into a small square JPEG.

Phone photos are often 3 to 5 MB and rotated by a hidden "orientation" flag. We straighten
them, crop to a square, shrink to 320 x 320 and re-save as JPEG (usually 15 to 40 KB), so
they load fast on slow connections and are cheap to keep in the database.
"""
import io
import warnings

AVATAR_SIZE = 320
MAX_PIXELS = 25_000_000  # refuse absurdly large pictures (decompression bombs)


class ImageError(Exception):
    """The picture could not be used. The text is safe to show the member."""


def prepare_avatar(data: bytes) -> tuple[bytes, str]:
    """Returns (JPEG bytes, content type)."""
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError:
        # Pillow is not installed: keep the original file (its size and type were checked)
        return data, "image/webp" if data[8:12] == b"WEBP" else ("image/png" if data[:4] == b"\x89PNG" else "image/jpeg")

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)  # treat as an error
            with Image.open(io.BytesIO(data)) as opened:
                opened.load()
                img = ImageOps.exif_transpose(opened)
                if img.mode in ("RGBA", "LA", "P"):
                    img = img.convert("RGBA")
                    flat = Image.new("RGB", img.size, (255, 255, 255))  # transparent areas become white
                    flat.paste(img, mask=img.split()[-1])
                    img = flat
                else:
                    img = img.convert("RGB")
                img = ImageOps.fit(img, (AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)
                out = io.BytesIO()
                img.save(out, "JPEG", quality=85, optimize=True, progressive=True)
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, ValueError, SyntaxError):
        raise ImageError("We could not read that picture. Try a different JPG, PNG or WebP photo.")
    return out.getvalue(), "image/jpeg"
