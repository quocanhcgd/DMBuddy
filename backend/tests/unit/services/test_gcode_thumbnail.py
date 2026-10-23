import base64
import io
import zipfile

from backend.app.services.gcode_thumbnail import extract_3mf_thumbnail, extract_gcode_thumbnail


def test_extracts_png_thumbnail_from_klipper_comments():
    png = b"\x89PNG\r\n\x1a\nunit-test"
    encoded = base64.b64encode(png).decode()
    source = f"; generated\n; thumbnail begin 64x48 {len(png)}\n; {encoded[:8]}\n; {encoded[8:]}\n; thumbnail end\nG1 X1\n".encode()

    thumbnail = extract_gcode_thumbnail(source)

    assert thumbnail is not None
    assert thumbnail.data == png
    assert (thumbnail.width, thumbnail.height, thumbnail.media_type) == (64, 48, "image/png")


def test_ignores_invalid_or_unsupported_thumbnail_blocks():
    source = b"; thumbnail begin 32x32 3\n; bmF0\n; thumbnail end\n"

    assert extract_gcode_thumbnail(source) is None


def test_extracts_requested_plate_thumbnail_from_3mf():
    plate_one = b"\x89PNG\r\n\x1a\nplate-one"
    plate_four = b"\x89PNG\r\n\x1a\nplate-four"
    archive_data = io.BytesIO()
    with zipfile.ZipFile(archive_data, "w") as archive:
        archive.writestr("Metadata/plate_1.png", plate_one)
        archive.writestr("Metadata/plate_4.png", plate_four)

    thumbnail = extract_3mf_thumbnail(archive_data.getvalue(), plate_index=4)

    assert thumbnail is not None
    assert thumbnail.data == plate_four
    assert thumbnail.media_type == "image/png"


def test_extracts_auxiliary_thumbnail_when_3mf_has_no_plate_preview():
    preview = b"\x89PNG\r\n\x1a\nthreemf-preview"
    archive_data = io.BytesIO()
    with zipfile.ZipFile(archive_data, "w") as archive:
        archive.writestr("Auxiliaries/.thumbnails/thumbnail_middle.png", preview)

    thumbnail = extract_3mf_thumbnail(archive_data.getvalue())

    assert thumbnail is not None
    assert thumbnail.data == preview


def test_invalid_3mf_has_no_thumbnail():
    assert extract_3mf_thumbnail(b"not a zip archive") is None
