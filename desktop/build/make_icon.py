"""Draws Grid's app icon (macOS squircle with a geometric G) -> icon.png + icon.icns."""

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
S = 1024


def draw(size: int = S) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = int(size * 0.09)                      # macOS icon grid margin
    r = int(size * 0.2)
    # Code-native geometric G, shared with server/static/grid-mark.svg.
    d.rounded_rectangle([pad, pad, size-pad, size-pad], radius=r, fill="#25342b")
    def point(x, y):
        return (pad + x / 64 * (size - 2 * pad), pad + y / 64 * (size - 2 * pad))
    d.polygon([point(x,y) for x,y in [(16,16),(40,16),(40,24),(24,24),(24,40),(40,40),(40,32),(48,32),(48,48),(16,48)]], fill="#d5e7b9")
    d.rectangle([point(40,16),point(48,24)],fill="#efad92")
    d.rectangle([point(32,28),point(48,36)],fill="#d5e7b9")
    return img


if __name__ == "__main__":
    icon = draw()
    icon.save(HERE / "icon.png")
    icon.save(HERE / "icon.icns", sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)])
    print("wrote", HERE / "icon.png", HERE / "icon.icns")
