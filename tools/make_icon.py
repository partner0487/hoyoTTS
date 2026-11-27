"""產生 hoyoTTS 的圖示（assets/icon_*.png、assets/icon.ico）。

    python tools/make_icon.py            產生全部設計和預覽圖 assets/icon_preview.png
    python tools/make_icon.py e          把設計 e 設為程式圖示（assets/icon.ico、assets/icon.png）

以 1024px 繪製再縮小，邊緣才平滑。
"""

import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets")
S = 1024

GREEN = (59, 111, 216)      # 主色（藍）
GREEN_DARK = (36, 65, 138)  # 深藍
GREEN_LIGHT = (247, 168, 196)  # 點綴（粉）
GOLD = (240, 139, 176)  # 分隔線改粉色
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
    d.rounded_rectangle((481, 315, 543, 615), 31, fill=(232, 115, 158))  # 中間那條改粉色
    return img


def design_b():
    """對話分隔線（粉色）＋上方聲波：取自劇情對話框的意象。"""
    img = _rounded_base()
    d = ImageDraw.Draw(img)
    _bars(d, 512, 420, [120, 230, 330, 400, 330, 230, 120], 54, 34, WHITE)
    _divider(d)
    return img


def _divider(d, y=690):
    """劇情對話框的分隔線：兩段粉線、中間菱形，下面一條白線（代表台詞）。"""
    d.rounded_rectangle((170, y - 12, 440, y + 12), 12, fill=GOLD)
    d.rounded_rectangle((584, y - 12, 854, y + 12), 12, fill=GOLD)
    d.polygon([(512, y - 46), (558, y), (512, y + 46), (466, y)], fill=GOLD)
    d.rounded_rectangle((270, y + 80, 754, y + 110), 15, fill=(196, 212, 244))  # 實色淡藍白（半透明會直接蓋掉底色、透出背景）


def design_c():
    """文字行變成聲波：Text → Speech。"""
    img = _rounded_base(top=(79, 130, 230), bottom=GREEN_DARK)
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


PINK = (232, 115, 158)


def _star(d, cx, cy, r, color, p=0.55):
    """四芒星（四邊往內凹）：超橢圓 |x|^p + |y|^p = 1，p < 1 時四邊內凹。"""
    pts = []
    for i in range(128):
        t = i / 128 * 2 * math.pi
        c, s = math.cos(t), math.sin(t)
        k = (abs(c) ** p + abs(s) ** p) ** (-1 / p)
        pts.append((cx + r * c * k, cy + r * s * k))
    d.polygon(pts, fill=color)


def _wing_bars(d, cx, start, step, heights, centers, w, color):
    """左右對稱的翅膀聲波：離中心 start + i*step，靠內粗高、往外變短並往下彎（像頭冠的翅膀）。"""
    for i, (h, cy) in enumerate(zip(heights, centers)):
        off = start + i * step
        for x in (cx - off, cx + off):
            d.rounded_rectangle((x - w / 2, cy - h / 2, x + w / 2, cy + h / 2), w / 2, fill=color)


# 原神 LOGO 頭冠的意象：中間一顆四芒星，兩邊各一道翅膀，翅膀靠星星那頭粗、往外變細並往下彎。
def design_d():
    """頭冠整個變成聲波：中間最高那條（粉色）是星星，兩邊往外漸短往下彎的是翅膀。"""
    img = _rounded_base()
    d = ImageDraw.Draw(img)
    _wing_bars(d, 512, 68, 62, [250, 205, 170, 135, 100, 68], [505, 530, 552, 576, 604, 636], 40, WHITE)
    d.rounded_rectangle((512 - 23, 270, 512 + 23, 690), 23, fill=PINK)
    return img


def design_e():
    """中間白色四芒星，兩邊翅膀變成聲波（往中間越來越高），下方是 B 的粉色分隔線和白線。"""
    img = _rounded_base()
    d = ImageDraw.Draw(img)
    cy = 420
    _wing_bars(d, 512, 210, 58, [250, 195, 145, 100], [cy] * 4, 40, WHITE)
    _star(d, 512, cy, 150, WHITE)
    _divider(d)
    return img


DESIGNS = {"a": ("對話泡泡＋聲波", design_a), "b": ("粉色分隔線＋聲波", design_b), "c": ("文字→聲波", design_c),
           "d": ("頭冠聲波", design_d), "e": ("星星＋翅膀聲波", design_e)}


def preview(imgs):
    """各設計在 256 / 64 / 32 / 16px 下的樣子，淺色和深色底各一排。"""
    cell = 300
    font = None
    for f in ("msjhbd.ttc", "msjh.ttc"):
        try:
            font = ImageFont.truetype(f, 28)
            break
        except OSError:
            pass
    W, H = cell * len(imgs) + 40, 760
    out = Image.new("RGB", (W, H), (238, 243, 251))
    d = ImageDraw.Draw(out)
    d.rectangle((0, 430, W, H), fill=(32, 36, 34))
    for i, (key, (label, img)) in enumerate(imgs.items()):
        x0 = 20 + i * cell
        out.paste(img.resize((256, 256), Image.LANCZOS), (x0 + 22, 30), img.resize((256, 256), Image.LANCZOS))
        d.text((x0 + cell / 2, 320), f"{key.upper()}　{label}", fill=(36, 65, 138), font=font, anchor="mm")
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
