"""從遊戲畫面判斷是否在對話中，並 OCR 出角色名、台詞、對話選項。

版面以 1920×1080 實際截圖量測（其他解析度等比換算）：
- 角色名：金色字 (248,189,0)，y≈855–890，置中
- 分隔線：半透明金線，y≈898–900、x≈315–1605。對話時一定在，拿來判斷是否在對話中
- 台詞：白字，y≈905–990，最多兩行
- 選項：右側 x≈1270–1800，由 y≈830 往上堆，每個約 74px，左邊有白色泡泡圖示
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

BASE_W, BASE_H = 1920, 1080

# OCR 常見誤判
_FIXES = str.maketrans({"亅": "」", "『": "「", "』": "」", "囗": "口", "|": ""})
_ASCII_WORD = re.compile(r"[A-Za-z0-9]")


@dataclass
class DialogueState:
    in_dialogue: bool
    name: str = ""
    text: str = ""
    options: list[str] = field(default_factory=list)


def _join_words(words: list[str]) -> str:
    """WinRT 對中文逐字切詞；只有英數字之間保留空白。"""
    out = ""
    for w in words:
        if out and _ASCII_WORD.match(out[-1]) and _ASCII_WORD.match(w[0]):
            out += " "
        out += w
    return out


def clean_text(s: str) -> str:
    s = s.translate(_FIXES).strip()
    # 句尾的「…」常被認成引號；「——」常被認成「一乛」
    s = re.sub(r"[“”\"]+$", "…", s)
    s = s.replace("乛", "")
    # 夾在中文字之間的 r / L 是「 / 」被認錯
    s = re.sub(r"(?<=[一-鿿，。、！？,])[rT](?=[一-鿿])", "「", s)
    s = re.sub(r"(?<=[一-鿿])[LJ](?=[一-鿿，。、！？,!?…]|$)", "」", s)
    return s


def clean_option(s: str) -> str:
    # 泡泡圖示偶爾被認成 ) 或 ］ 之類
    return clean_text(re.sub(r"^[\)\]）】｝}>〉»·•\s]+", "", s))


def merge_insertions(base: str, other: str) -> str:
    """以 base 為主，只補上 other 多出來的字（不採用 other 的替換）。
    WinRT OCR 放大 2 倍時字認得準但在亮背景上會漏字，原尺寸時不漏字但較常認錯，兩者互補。"""
    from difflib import SequenceMatcher

    out = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, base, other, autojunk=False).get_opcodes():
        if op == "insert":
            out.append(other[j1:j2])
        else:  # equal / replace / delete 都保留 base
            out.append(base[i1:i2])
    return "".join(out)


class DialogueReader:
    def __init__(self, regions: dict, ocr_reader=None, ocr_reader_1x=None):
        self.regions = regions
        import screen_ocr

        self.ocr = ocr_reader or screen_ocr.Reader.create_quality_reader(resize_factor=2)
        self.ocr_1x = ocr_reader_1x or screen_ocr.Reader.create_quality_reader(resize_factor=1)

    # ---- 座標 ----
    @staticmethod
    def _scale(box, w, h):
        sx, sy = w / BASE_W, h / BASE_H
        l, t, r, b = box
        return int(l * sx), int(t * sy), int(r * sx), int(b * sy)

    def _crop(self, frame: np.ndarray, box) -> np.ndarray:
        h, w = frame.shape[:2]
        l, t, r, b = self._scale(box, w, h)
        return np.ascontiguousarray(frame[t:b, l:r, :3])

    # ---- 判斷 ----
    def in_dialogue(self, frame: np.ndarray) -> bool:
        """找金色分隔線：某一列比上下 5px 明顯偏暖（R−B 高），且橫跨大部分寬度。"""
        h, w = frame.shape[:2]
        sy, sx = h / BASE_H, w / BASE_W
        x0, x1 = int(400 * sx), int(1520 * sx)
        cols = slice(x0, x1, 4)
        d = max(2, int(round(5 * sy)))
        for y in range(int(893 * sy), int(906 * sy) + 1):
            if y - d < 0 or y + d >= h:
                continue
            row = frame[y, cols, :3].astype(np.int16)
            ab = frame[y - d, cols, :3].astype(np.int16)
            be = frame[y + d, cols, :3].astype(np.int16)
            warm = (row[:, 0] - row[:, 2]) - ((ab[:, 0] - ab[:, 2]) + (be[:, 0] - be[:, 2])) / 2
            if (warm > 40).mean() > 0.85:
                return True
        return False

    def _ocr_lines(self, img: np.ndarray, reader=None) -> list[str]:
        res = (reader or self.ocr).read_image(Image.fromarray(img))
        return [_join_words([w.text for w in line.words]) for line in res.result.lines]

    def read_name(self, frame: np.ndarray) -> str:
        crop = self._crop(frame, self.regions["name"]).astype(np.int16)
        gold = (crop[..., 0] > 180) & (crop[..., 1] > 120) & (crop[..., 2] < 120)
        if gold.sum() < 30:
            return ""  # 沒有金色字 = 旁白（沒有角色名）
        # 只留金色字轉成白底黑字，四周留白，否則第一個字常被吃掉
        mask = np.pad(np.where(gold, 0, 255).astype(np.uint8), 30, constant_values=255)
        return clean_text("".join(self._ocr_lines(np.stack([mask] * 3, -1))))

    def read_text(self, frame: np.ndarray) -> str:
        crop = self._crop(frame, self.regions["text"])
        base = "".join(self._ocr_lines(crop))
        if not base:
            return ""
        return clean_text(merge_insertions(base, "".join(self._ocr_lines(crop, self.ocr_1x))))

    def read_options(self, frame: np.ndarray) -> list[str]:
        lines = [clean_option(s) for s in self._ocr_lines(self._crop(frame, self.regions["options"]))]
        return [s for s in lines if len(s) >= 2]

    def read(self, frame: np.ndarray, with_options: bool = True) -> DialogueState:
        if not self.in_dialogue(frame):
            return DialogueState(False)
        return DialogueState(True, self.read_name(frame), self.read_text(frame),
                             self.read_options(frame) if with_options else [])

    def debug_image(self, frame: np.ndarray) -> Image.Image:
        """把各區域框起來，給 UI 的「擷取預覽」用。"""
        from PIL import ImageDraw

        img = Image.fromarray(np.ascontiguousarray(frame[..., :3]))
        d = ImageDraw.Draw(img)
        h, w = frame.shape[:2]
        colors = {"name": (255, 200, 0), "text": (0, 200, 255), "options": (0, 255, 120)}
        for k, box in self.regions.items():
            d.rectangle(self._scale(box, w, h), outline=colors.get(k, (255, 0, 0)), width=3)
        y = int(899 * h / BASE_H)
        d.line([(int(400 * w / BASE_W), y), (int(1520 * w / BASE_W), y)],
               fill=(0, 255, 0) if self.in_dialogue(frame) else (255, 0, 0), width=2)
        return img
