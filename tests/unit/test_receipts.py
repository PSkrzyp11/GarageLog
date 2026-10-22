import io
import re

import pytest
from PIL import Image

from app.receipts import (
    JPEG,
    MAX_IMAGE_SIDE,
    MAX_RECEIPT_BYTES,
    PDF,
    ReceiptError,
    prepare_receipt,
)

GPS_IFD = 0x8825


def image_bytes(
    size: tuple[int, int] = (300, 200),
    image_format: str = "JPEG",
    mode: str = "RGB",
    color: object = "red",
    exif: Image.Exif | None = None,
) -> bytes:
    output = io.BytesIO()
    extra = {"exif": exif} if exif is not None else {}
    Image.new(mode, size, color).save(output, image_format, **extra)
    return output.getvalue()


def decoded(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


@pytest.mark.parametrize("image_format", ["JPEG", "PNG", "WEBP"])
def test_photos_are_stored_as_jpeg(image_format: str) -> None:
    receipt = prepare_receipt(image_bytes(image_format=image_format))

    assert receipt.content_type == JPEG
    assert decoded(receipt.data).format == "JPEG"


def test_location_and_other_metadata_are_removed() -> None:
    exif = Image.Exif()
    exif[0x010F] = "Telefon Jana"  # camera maker
    exif.get_ifd(GPS_IFD)[2] = (52.0, 13.0, 0.0)  # latitude
    original = image_bytes(exif=exif)
    assert decoded(original).getexif()  # the test photo really has metadata

    receipt = prepare_receipt(original)

    assert not decoded(receipt.data).getexif()
    assert b"Telefon Jana" not in receipt.data


def test_a_sideways_phone_photo_is_turned_upright() -> None:
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation: rotate 90° clockwise to display
    receipt = prepare_receipt(image_bytes(size=(300, 200), exif=exif))

    assert decoded(receipt.data).size == (200, 300)


def test_large_photos_are_shrunk() -> None:
    receipt = prepare_receipt(image_bytes(size=(4000, 3000)))

    assert decoded(receipt.data).size == (MAX_IMAGE_SIDE, 1500)


def test_transparent_areas_become_white() -> None:
    receipt = prepare_receipt(image_bytes(image_format="PNG", mode="RGBA", color=(0, 0, 0, 0)))

    red, green, blue = decoded(receipt.data).getpixel((10, 10))
    assert min(red, green, blue) > 240


def test_pdf_is_kept_as_it_is() -> None:
    pdf = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"

    receipt = prepare_receipt(pdf)

    assert receipt.content_type == PDF
    assert receipt.data == pdf


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "Wybrany plik jest pusty."),
        (b"<script>alert(1)</script>", "Dodaj zdjęcie (JPG, PNG, WebP) albo PDF."),
        (image_bytes(image_format="GIF"), "Dodaj zdjęcie (JPG, PNG, WebP) albo PDF."),
        (image_bytes()[:200], "Dodaj zdjęcie (JPG, PNG, WebP) albo PDF."),  # truncated
        (b"%PDF-" + b"x" * MAX_RECEIPT_BYTES, "Plik może mieć najwyżej 10 MB."),
    ],
    ids=["empty", "html", "gif", "truncated-jpeg", "too-large"],
)
def test_unacceptable_files_are_rejected(data: bytes, message: str) -> None:
    with pytest.raises(ReceiptError, match=re.escape(message)):
        prepare_receipt(data)


def test_decompression_bomb_is_rejected() -> None:
    # A 1-bit PNG of 8000 × 8000 is tiny on disk but 64 million pixels once decoded.
    bomb = image_bytes(size=(8000, 8000), image_format="PNG", mode="1", color=0)
    assert len(bomb) < MAX_RECEIPT_BYTES

    with pytest.raises(ReceiptError):
        prepare_receipt(bomb)
