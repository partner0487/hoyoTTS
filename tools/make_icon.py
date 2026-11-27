"""產生 hoyoTTS 的圖示（assets/icon_*.png、assets/icon.ico）。

    python tools/make_icon.py            產生全部設計和預覽圖 assets/icon_preview.png
    python tools/make_icon.py a          把設計 a 設為程式圖示（assets/icon.ico、assets/icon.png）

以 1024px 繪製再縮小，邊緣才平滑。
"""

import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets")
S = 1024

GREEN = (47, 143, 87)
GREEN_DARK = (29, 94, 56)
GREEN_LIGHT = (110, 230, 154)
GOLD = (236, 190, 72)
WHITE = (255, 255, 255)


def _gradient(top, bottom):
    g = Image.new("RGB", (1, S))
    for y in range(S):
        t = y / (S - 1)
        g.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    return g.resize((S, S))


def _rounded_base(top=GREEN, bottom=GREEN_DARK, radius=230, margin=40):
    """圓角方形底，帶一點陰影。"""
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((margin, margin, S - margin, S - margin), radius, fill=255)
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((margin, margin + 18, S - margin, S - margin + 18), radius,
                                             fill=(0, 40, 20, 110))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
    body = _gradient(top, bottom).convert("RGBA")
    body.putalpha(mask)
    img.alpha_composite(body)
    return img


def _bars(d, cx, cy, heights, w, gap, color):
    """置中的一排圓頭音量條。"""
    total = len(heights) * w + (len(heights) - 1) * gap
    x = cx - total / 2
    for h in heights:
        d.rounded_rectangle((x, cy - h / 2, x + w, cy + h / 2), w / 2, fill=color)
        x += w + gap


def design_a():
    """對話泡泡＋聲波：念出劇情對話。"""
    img = _rounded_base()
    d = ImageDraw.Draw(img)
    # 泡泡（左下有尾巴）
    d.rounded_rectangle((190, 230, 834, 700), 150, fill=WHITE)
    d.polygon([(300, 640), (250, 830), (450, 690)], fill=WHITE)
    _bars(d, 512, 465, [110, 220, 300, 200, 130], 62, 40, GREEN)
    return img


def design_b():
    """金色對話分隔線＋上方聲波：取自劇情對話框的意象。"""
    img = _rounded_base()
    d = ImageDraw.Draw(img)
    _bars(d, 512, 420, [120, 230, 330, 400, 330, 230, 120], 54, 34, WHITE)
    # 分隔線：兩段金線，中間菱形
    y = 690
    d.rounded_rectangle((170, y - 12, 440, y + 12), 12, fill=GOLD)
    d.rounded_rectangle((584, y - 12, 854, y + 12), 12, fill=GOLD)
    d.polygon([(512, y - 46), (558, y), (512, y + 46), (466, y)], fill=GOLD)
    # 下方兩行字（淡）
    d.rounded_rectangle((270, 770, 754, 800), 15, fill=(255, 255, 255, 150))
    return img


def design_c():
    """文字行變成聲波：Text → Speech。"""
    img = _rounded_base(top=(56, 160, 100), bottom=GREEN_DARK)
    d = ImageDraw.Draw(img)
    # 左邊三行字
    for i, (w, y) in enumerate([(300, 330), (250, 470), (200, 610)]):
        d.rounded_rectangle((180, y, 180 + w, y + 70), 35, fill=WHITE)
    # 右邊三道聲波弧線
    cx, cy = 520, 505
    for i, r in enumerate([140, 230, 320]):
        box = (cx - r, cy - r, cx + r, cy + r)
        d.arc(box, -48, 48, fill=GREEN_LIGHT if i < 2 else WHITE, width=58)
    return img


DESIGNS = {"a": ("對話泡泡＋聲波", design_a), "b": ("金色分隔線＋聲波", design_b), "c": ("文字→聲波", design_c)}


def preview(imgs):
    """三個設計在 256 / 64 / 32 / 16px 下的樣子，淺色和深色底各一排。"""
    cell = 300
    font = None
    for f in ("msjhbd.ttc", "msjh.ttc"):
        try:
            font = ImageFont.truetype(f, 28)
            break
        except OSError:
            pass
    W, H = cell * len(imgs) + 40, 760
    out = Image.new("RGB", (W, H), (238, 246, 240))
    d = ImageDraw.Draw(out)
    d.rectangle((0, 430, W, H), fill=(32, 36, 34))
    for i, (key, (label, img)) in enumerate(imgs.items()):
        x0 = 20 + i * cell
        out.paste(img.resize((256, 256), Image.LANCZOS), (x0 + 22, 30), img.resize((256, 256), Image.LANCZOS))
        d.text((x0 + cell / 2, 320), f"{key.upper()}　{label}", fill=(29, 94, 56), font=font, anchor="mm")
        for row_y in (370, 495):
            x = x0 + 40
            for sz in (64, 32, 16):
                small = img.resize((sz, sz), Image.LANCZOS)
                y = row_y + (64 - sz) // 2
                if row_y == 370:
                    continue
                out.paste(small, (x, y), small)
                x += sz + 30
        # 模擬工作列（深色）上的大小
        big = img.resize((96, 96), Image.LANCZOS)
        out.paste(big, (x0 + 100, 620), big)
    d.text((20, 440), "深色背景（工作列）上的 64 / 32 / 16px", fill=(200, 210, 204), font=font)
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    imgs = {k: (label, fn()) for k, (label, fn) in DESIGNS.items()}
    choose = sys.argv[1].lower() if len(sys.argv) > 1 else None
    if choose:
        img = imgs[choose][1]
        img.resize((512, 512), Image.LANCZOS).save(os.path.join(OUT, "icon.png"))
        img.save(os.path.join(OUT, "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        print(f"已把設計 {choose} 設為程式圖示")
        return
    for k, (_, img) in imgs.items():
        img.resize((512, 512), Image.LANCZOS).save(os.path.join(OUT, f"icon_{k}.png"))
    preview(imgs).save(os.path.join(OUT, "icon_preview.png"))
    print(os.path.join(OUT, "icon_preview.png"))


if __name__ == "__main__":
    main()
