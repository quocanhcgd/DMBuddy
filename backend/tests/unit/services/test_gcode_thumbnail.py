import base64

from backend.app.services.gcode_thumbnail import extract_gcode_thumbnail


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
