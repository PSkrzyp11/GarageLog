"""Receipt files attached to refuels: checked, cleaned and shrunk before they are stored.

- The type is recognised from the file's content, never from its name or the browser's
  claim: a renamed file cannot pass as a photo.
- Photos are decoded and saved again as a new JPEG. That drops everything except the
  pixels — above all the EXIF metadata, where phones write the GPS location — and makes
  a crafted "image" harmless, because only freshly encoded pixels are ever served.
- Photos are shrunk to MAX_IMAGE_SIDE (a receipt stays readable, the database stays small).
- PDFs are kept as they are and only ever offered as a download (see the route).
"""

import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_RECEIPT_BYTES = 10 * 1024 * 1024
MAX_IMAGE_SIDE = 2000
# Refuse "decompression bombs": a small file that unpacks into a gigantic image.
MAX_IMAGE_PIXELS = 50_000_000
IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}

JPEG = "image/jpeg"
PDF = "application/pdf"


class ReceiptError(Exception):
    """The upload is not an acceptable receipt; the message is shown at the form field."""


@dataclass(frozen=True)
class PreparedReceipt:
    content_type: str  # JPEG or PDF
    data: bytes


def prepare_receipt(data: bytes) -> PreparedReceipt:
    if not data:
        raise ReceiptError("Wybrany plik jest pusty.")
    if len(data) > MAX_RECEIPT_BYTES:
        raise ReceiptError("Plik może mieć najwyżej 10 MB.")
    if data.startswith(b"%PDF-"):
        return PreparedReceipt(PDF, data)
    return PreparedReceipt(JPEG, _clean_image(data))


def _clean_image(data: bytes) -> bytes:
    not_an_image = ReceiptError("Dodaj zdjęcie (JPG, PNG, WebP) albo PDF.")
    try:
        with warnings.catch_warnings():
            # Pillow only warns between 1× and 2× its pixel limit; treat that as an error too.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in IMAGE_FORMATS:
                    raise not_an_image
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ReceiptError("Zdjęcie ma zbyt dużą rozdzielczość.")
                # Phones store the photo sideways plus an "rotate me" flag in EXIF; apply it
                # now, because the flag is removed together with the rest of the metadata.
                upright = ImageOps.exif_transpose(image)
                flat = _on_white(upright)
                flat.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
                output = io.BytesIO()
                flat.save(output, "JPEG", quality=85, optimize=True)
    except ReceiptError:
        raise
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,  # e.g. a truncated file
        ValueError,
        SyntaxError,  # raised by some Pillow decoders for malformed headers
    ) as exc:
        raise not_an_image from exc
    return output.getvalue()


def _on_white(image: Image.Image) -> Image.Image:
    """RGB for JPEG; transparent areas (e.g. a PNG screenshot) become white, not black."""
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")
