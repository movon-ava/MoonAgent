import io
import sys

sys.path.insert(0, ".")

from PIL import Image

from backend.tools.core import _normalise_image

# a BMP is a format the vision API rejects
buf = io.BytesIO()
Image.new("RGB", (32, 32), (10, 120, 200)).save(buf, format="BMP")
bmp = buf.getvalue()

out = _normalise_image(bmp, "image/bmp")
assert not isinstance(out, str), out
data, mime = out
print("bmp ->", mime, len(data), "bytes, png magic:", data[:8] == b"\x89PNG\r\n\x1a\n")

# a corrupted PNG must be reported, not sent
bad = b"\x89PNG\r\n\x1a\n" + b"garbage" * 20
res = _normalise_image(bad, "image/png")
print("corrupt ->", res if isinstance(res, str) else "converted")

# a good PNG passes through untouched
buf2 = io.BytesIO()
Image.new("RGB", (8, 8), (1, 2, 3)).save(buf2, format="PNG")
png = buf2.getvalue()
out2 = _normalise_image(png, "image/png")
print("png passthrough:", not isinstance(out2, str) and out2[0] == png and out2[1] == "image/png")
