"""產生 hoyoTTS 的圖示：assets/icon.ico（視窗、工作列）、assets/icon.png、assets/icon_preview.png（各尺寸預覽）。

    python tools/make_icon.py

設計：取原神頭冠的意象。中間白色四芒星，兩邊的翅膀變成聲波（往中間越來越高），
下方是劇情對話框的粉色分隔線和一行台詞。以 1024px 繪製再縮小，邊緣才平滑。
"""

import math
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets")
S = 1024

BLUE = (59, 111, 216)
BLUE_DARK = (36, 65, 138)
PINK = (240, 139, 176)
LINE = (196, 212, 244)  # 台詞那條線用實色淡藍白（半透明會直接蓋掉底色、透出背景）
WHITE = (255, 255, 255)


def _gradient(top, bottom):
    g = Image.new("RGB", (1, S))
    for y in range(S):
        t = y / (S - 1)
        g.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    return g.resize((S, S))


def _rounded_base(top=BLUE, bottom=BLUE_DARK, radius=230, margin=40):
    """圓角方形底，帶一點陰影。"""
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((margin, margin, S - margin, S - margin), radius, fill=255)
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((margin, margin + 18, S - margin, S - margin + 18), radius,
                                             fill=(0, 20, 60, 110))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
    body = _gradient(top, bottom).convert("RGBA")
    body.putalpha(mask)
    img.alpha_composite(body)
    return img


def _star(d, cx, cy, r, color, p=0.55):
    """四芒星（四邊往內凹）：超橢圓 |x|^p + |y|^p = 1，p < 1 時四邊內凹。"""
    pts = []
    for i in range(128):
        t = i / 128 * 2 * math.pi
        c, s = math.cos(t), math.sin(t)
        k = (abs(c) ** p + abs(s) ** p) ** (-1 / p)
        pts.append((cx + r * c * k, cy + r * s * k))
    d.polygon(pts, fill=color)


def _wing_bars(d, cx, cy, start, step, heights, w, color):
    """左右對稱的聲波條：離中心 start + i*step，heights 由內往外。"""
    for i, h in enumerate(heights):
        off = start + i * step
        for x in (cx - off, cx + off):
            d.rounded_rectangle((x - w / 2, cy - h / 2, x + w / 2, cy + h / 2), w / 2, fill=color)


def _divider(d, y=690):
    """劇情對話框的分隔線：兩段粉線、中間菱形，下面一條台詞線。"""
    d.rounded_rectangle((170, y - 12, 440, y + 12), 12, fill=PINK)
    d.rounded_rectangle((584, y - 12, 854, y + 12), 12, fill=PINK)
    d.polygon([(512, y - 46), (558, y), (512, y + 46), (466, y)], fill=PINK)
    d.rounded_rectangle((270, y + 80, 754, y + 110), 15, fill=LINE)


def icon():
    img = _rounded_base()
    d = ImageDraw.Draw(img)
    cy = 420
    _wing_bars(d, 512, cy, 175, 58, [250, 195, 145, 100], 40, WHITE)
    _star(d, 512, cy, 115, WHITE)
    _divider(d)
    return img


def icon_small(size):
    """16～40px 用的簡化版：大版的細聲波、陰影和台詞線縮到這麼小會糊成一團。
    以 24 格為單位設計（Win11 工作列 100% 縮放是 24px），聲波和分隔線都對齊像素格；
    底色填滿整格、每邊兩條粗聲波、星星和分隔線加粗。先畫 16 倍大再縮小，邊緣才平滑。"""
    k = 16
    N = size * k
    u = N / 24  # 一格

    def U(*v):
        return [x * u for x in v]

    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    mask = Image.new("L", (N, N), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, N - 1, N - 1), 5 * u, fill=255)
    g = Image.new("RGB", (1, N))
    for y in range(N):
        t = y / (N - 1)
        g.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(BLUE, BLUE_DARK)))
    body = g.resize((N, N)).convert("RGBA")
    body.putalpha(mask)
    img.alpha_composite(body)
    d = ImageDraw.Draw(img)
    cy = 10
    for x0, h in ((5, 8), (2, 4)):  # 由內往外：越外越矮
        for x in (x0, 24 - x0 - 2):
            d.rounded_rectangle(U(x, cy - h / 2, x + 2, cy + h / 2), u, fill=WHITE)
    _star(d, 12 * u, cy * u, 4 * u, WHITE)
    d.rounded_rectangle(U(3, 17, 9.5, 19), u, fill=PINK)
    d.rounded_rectangle(U(14.5, 17, 21, 19), u, fill=PINK)
    d.polygon([tuple(U(12, 15.5)), tuple(U(14, 18)), tuple(U(12, 20.5)), tuple(U(10, 18))], fill=PINK)
    return img.resize((size, size), Image.LANCZOS)


# 工作列：100% 縮放 24px、125% 30px、150% 36px；標題列 16 / 20 / 24px
SMALL = (16, 20, 24, 30, 32, 36, 40)
ICO_SIZES = (16, 20, 24, 30, 32, 36, 40, 48, 64, 96, 128, 256)


def frames(img):
    """每個尺寸各自的圖：小尺寸用簡化版，48px 以上用大版縮小。"""
    return [icon_small(s) if s in SMALL else img.resize((s, s), Image.LANCZOS) for s in ICO_SIZES]


def preview(img):
    """256px 大圖，以及淺色、深色（工作列）底上的 64 / 32 / 24 / 16px。"""
    font = None
    for f in ("msjh.ttc", "msjhbd.ttc"):
        try:
            font = ImageFont.truetype(f, 22)
            break
        except OSError:
            pass
    out = Image.new("RGB", (640, 300), (238, 243, 251))
    d = ImageDraw.Draw(out)
    d.rectangle((300, 150, 640, 300), fill=(32, 36, 34))
    big = img.resize((256, 256), Image.LANCZOS)
    out.paste(big, (22, 22), big)
    for row_y, fg in ((40, (36, 65, 138)), (190, (200, 210, 204))):
        x = 320
        for sz in (64, 32, 24, 16):
            small = icon_small(sz) if sz in SMALL else img.resize((sz, sz), Image.LANCZOS)
            out.paste(small, (x, row_y + (64 - sz) // 2), small)
            x += sz + 24
        d.text((320, row_y + 78), "64 / 32 / 24 / 16px", fill=fg, font=font)
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    img = icon()
    img.resize((512, 512), Image.LANCZOS).save(os.path.join(OUT, "icon.png"))
    fr = frames(img)
    fr[-1].save(os.path.join(OUT, "icon.ico"), sizes=[(s, s) for s in ICO_SIZES], append_images=fr[:-1])
    preview(img).save(os.path.join(OUT, "icon_preview.png"))
    print("已產生 assets/icon.ico、icon.png、icon_preview.png")


if __name__ == "__main__":
    main()
