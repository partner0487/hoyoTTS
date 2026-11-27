"""從遊戲畫面判斷是否在對話中，並 OCR 出角色名、台詞、對話選項。

版面以 1920×1080 實際截圖量測（其他解析度等比換算）：
- 角色名：金色字 (248,189,0)，y≈855–890，置中
- 分隔線：金線，對話時一定在，拿來判斷是否在對話中。兩種版面：
  - 一般：一整條，y≈898–900，長度跟著台詞變（長句 x≈315–1605，短句只有 x≈782–1137）
  - NPC 有稱號（例如「「老庭院餐廳」侍者」）：y≈908–909，稱號壓在線的中間，
    線被切成左右兩段（x≈688–847、1072–1231），長度隨稱號而變
  兩種都以畫面中心左右對稱
- 台詞：白字，一般在 y≈905–990；有稱號時整段往下約 25px（稱號不念）
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
_CJK = re.compile("[㐀-鿿]")


@dataclass
class Divider:
    y: int          # 1920×1080 座標
    titled: bool    # 中間有 NPC 稱號（線被切成兩段）


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


def _fix_dashes(words) -> list[str]:
    """破折號「──」會被 OCR 認成「一」，但框的寬度約一個半字寬，真的「一」只有一個字寬。
    拿同一行一般字（不扁的）的寬度當基準，比它寬 1.3 倍以上的「一」換回「——」。"""
    texts = [w.text for w in words]
    normal = sorted(w.width for w in words if len(w.text) == 1 and w.height >= 0.6 * w.width)
    if not normal:
        return texts
    cw = normal[len(normal) // 2]
    return ["——" if set(w.text) <= {"一", "－", "-", "—", "ー"} and w.width >= 1.3 * cw else t
            for w, t in zip(words, texts)]


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
        # is_known(name) → 是不是已知角色（有模型或別名），用來從多個 OCR 結果裡挑名字
        self.is_known = None
        self._name_cache: tuple[bytes, str] | None = None

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
    @staticmethod
    def _runs(mask: np.ndarray, gap: int) -> list[tuple[int, int]]:
        """mask 裡連續為 True 的區段（容許 gap 以內的缺口）。"""
        xs = np.flatnonzero(mask)
        if not len(xs):
            return []
        breaks = np.flatnonzero(np.diff(xs) > gap)
        starts = np.r_[xs[0], xs[breaks + 1]]
        ends = np.r_[xs[breaks], xs[-1]]
        return list(zip(starts.tolist(), ends.tolist()))

    def find_divider(self, frame: np.ndarray) -> Divider | None:
        """找金色分隔線：某一列比上下 5px 明顯偏暖（R−B 高）的線段，以畫面中心左右對稱。
        一整條線（一般；長度跟著台詞變，短句只有約 350px），或中間被稱號切開的左右兩段（有稱號的 NPC）。"""
        h, w = frame.shape[:2]
        sy, sx = h / BASE_H, w / BASE_W
        x0, x1 = int(250 * sx), int(1670 * sx)
        cx = w / 2
        d = max(2, int(round(5 * sy)))
        seg_min = 100 * sx      # 每一段至少這麼長
        sym_tol = 20 * sx       # 左右端點相對中心的對稱誤差
        for y in range(int(892 * sy), int(918 * sy) + 1):
            if y - d < 0 or y + d >= h:
                continue
            row = frame[y, x0:x1, :3].astype(np.int16)
            ab = frame[y - d, x0:x1, :3].astype(np.int16)
            be = frame[y + d, x0:x1, :3].astype(np.int16)
            warm = (row[:, 0] - row[:, 2]) - ((ab[:, 0] - ab[:, 2]) + (be[:, 0] - be[:, 2])) / 2
            runs = [(a + x0, b + x0) for a, b in self._runs(warm > 40, int(6 * sx)) if b - a >= seg_min]
            if not runs:
                continue
            # 一整條：跨過中心、至少 250px、對稱
            for a, b in runs:
                if a < cx < b and b - a >= 250 * sx and abs((a + b) / 2 - cx) <= sym_tol:
                    return Divider(int(round(y / sy)), False)
            # 左右兩段：左段在中心左邊、右段在右邊，外側端點對稱
            left = [r for r in runs if r[1] < cx]
            right = [r for r in runs if r[0] > cx]
            for la, lb in left:
                for ra, rb in right:
                    if abs((la + rb) / 2 - cx) <= sym_tol and abs((lb + ra) / 2 - cx) <= 60 * sx:
                        return Divider(int(round(y / sy)), True)
        return None

    def in_dialogue(self, frame: np.ndarray) -> bool:
        return self.find_divider(frame) is not None

    def _ocr_lines(self, img: np.ndarray, reader=None) -> list[str]:
        """OCR 出來的每一行，由上往下排（Windows OCR 回傳的行序不一定是畫面上的順序）。"""
        res = (reader or self.ocr).read_image(Image.fromarray(img))
        lines = sorted((l for l in res.result.lines if l.words), key=lambda l: min(w.top for w in l.words))
        return [_join_words(_fix_dashes(line.words)) for line in lines]

    def read_name(self, frame: np.ndarray) -> str:
        crop = self._crop(frame, self.regions["name"]).astype(np.int16)
        gold = (crop[..., 0] > 180) & (crop[..., 1] > 120) & (crop[..., 2] < 120)
        if gold.sum() < 30:
            return ""  # 沒有金色字 = 旁白（沒有角色名）
        key = np.packbits(gold).tobytes()
        if self._name_cache and self._name_cache[0] == key:
            return self._name_cache[1]  # 同一句台詞名字不變，不用每幀重認
        name = self._ocr_name(gold, crop)
        self._name_cache = (key, name)
        return name

    def _ocr_name(self, gold: np.ndarray, crop: np.ndarray) -> str:
        """Windows OCR 認短名字很不穩（「派蒙」常只認出「蒙」），換幾種前處理各認一次：
        有已知角色就用它，否則取出現最多次的，同票取較長的。"""
        from collections import Counter

        from PIL import ImageFilter

        # 只留金色字轉成白底黑字，四周留白，否則第一個字常被吃掉
        mask = Image.fromarray(np.where(gold, 0, 255).astype(np.uint8))

        def padded(im: Image.Image, fill) -> np.ndarray:
            out = Image.new(im.mode, (im.width + 120, im.height + 120), fill)
            out.paste(im, (60, 60))
            return np.array(out.convert("RGB"))

        blur = mask.filter(ImageFilter.GaussianBlur(0.8))
        x3 = mask.resize((mask.width * 3, mask.height * 3), Image.LANCZOS)
        orig = Image.fromarray(crop.clip(0, 255).astype(np.uint8))
        tries = [(padded(mask, 255), None), (padded(blur, 255), self.ocr_1x), (padded(x3, 255), None),
                 (padded(orig, (0, 0, 0)), self.ocr_1x)]
        cands = []
        for img, rd in tries:
            s = clean_text("".join(self._ocr_lines(img, rd)))
            if s:
                cands.append(s)
                if self.is_known and self.is_known(s):
                    return s
        if not cands:
            return ""
        count = Counter(cands)
        return max(count, key=lambda s: (count[s], len(s)))

    def text_box(self, div: Divider | None) -> list[int]:
        """台詞區域：一般版面用設定值；有稱號時往下移，避開稱號。"""
        l, t, r, b = self.regions["text"]
        if div is not None and div.titled:
            shift = (div.y + 16) - t  # 稱號約佔分隔線上下 12px
            return [l, t + shift, r, b + shift]
        return [l, t, r, b]

    def read_text(self, frame: np.ndarray, div: Divider | None = None) -> str:
        crop = self._crop(frame, self.text_box(div))
        gray = crop[..., :3].min(axis=2)
        bg = float(np.median(gray))
        if bg > 140:
            # 白字壓在淺色背景（白衣服、雪地）上對比太低，會漏字：只留白字轉成白底黑字再認。
            # 背景很亮時門檻跟著提高（至少比背景亮 10）
            thr = min(250, max(225, bg + 10))
            crop = np.stack([np.pad(np.where(gray >= thr, 0, 255).astype(np.uint8), 30, constant_values=255)] * 3, -1)
            base = "".join(self._ocr_lines(crop))
            if not base:
                return self._read_short_mask(crop[..., 0] == 0, gray.shape[0])
            return clean_text(merge_insertions(base, "".join(self._ocr_lines(crop, self.ocr_1x))))
        base = "".join(self._ocr_lines(crop))
        if not base:
            # 台詞只有「……」時 OCR 什麼都讀不到；不補上的話這句不會念、也不會自動過，就卡住了
            if self._only_dots(crop):
                return "……"
            # 很短的台詞（「唉…」）、或白字壓在淺色背景上，OCR 也常整個放棄
            return self._read_short(crop)
        if not _CJK.search(base):
            # 淺色背景上偶爾讀出「00 0」這種沒有中文字的亂碼：備援讀得到中文就用備援的
            short = self._read_short(crop)
            if _CJK.search(short):
                return short
        return clean_text(merge_insertions(base, "".join(self._ocr_lines(crop, self.ocr_1x))))

    _PREFIX = "台詞內容是"

    def _read_short(self, crop: np.ndarray) -> str:
        """OCR 讀不到時的備援：只留白字轉成白底黑字，前面接一段粗體的已知文字（Windows OCR 對只有一兩個字的
        圖片常常整個不認，接成一整句就認得），認完再把前綴拿掉。"""
        return self._read_short_mask(crop[..., :3].min(axis=2) >= 225, crop.shape[0])

    def _read_short_mask(self, white: np.ndarray, crop_h: int | None = None) -> str:
        """white：白字的遮罩。crop_h：台詞區的原始高度（用來換算字高；遮罩有加白邊時要另外給）。"""
        from PIL import ImageDraw, ImageFont

        ys, xs = np.nonzero(white)
        if len(xs) < 30:
            return ""
        s = (crop_h or white.shape[0]) / 97
        h = ys.max() - ys.min() + 1
        if h > 40 * s:  # 兩行以上：前綴照一行的高度
            h = int(27 * s)
        try:
            font = ImageFont.truetype("msjhbd.ttc", max(12, int(h)))
        except OSError:
            return ""
        text = Image.fromarray(np.where(white[ys.min():ys.max() + 1, xs.min():xs.max() + 1], 0, 255).astype(np.uint8))
        w = int(ImageDraw.Draw(text).textlength(self._PREFIX, font=font))
        img = Image.new("L", (w + text.width + 100, text.height + 80), 255)
        ImageDraw.Draw(img).text((40, 40), self._PREFIX, font=font, fill=0, anchor="lt")
        img.paste(text, (40 + w + 4, 40))
        arr = np.stack([np.array(img)] * 3, -1)
        cands = []
        for rd in (self.ocr_1x, self.ocr):
            res = "".join(self._ocr_lines(arr, rd))
            if res.startswith(self._PREFIX) and len(res) > len(self._PREFIX):
                cands.append(res[len(self._PREFIX):])
        return clean_text(max(cands, key=len)) if cands else ""

    @staticmethod
    def _only_dots(crop: np.ndarray) -> bool:
        """台詞區是不是只有一排小白點（「……」：1080p 下每點約 4×4px、間隔約 10px）。"""
        h = crop.shape[0]
        s = h / 97  # 台詞區在 1080p 約 97px 高
        white = crop[..., :3].min(axis=2) > 200
        ys, xs = np.nonzero(white)
        if len(xs) < 20 or len(xs) > 2000 * s * s:
            return False
        if ys.max() - ys.min() > 10 * s:
            return False  # 不在同一橫排（有一般的字或亮色背景）
        cols = np.zeros(crop.shape[1], bool)
        cols[xs] = True
        dots = DialogueReader._runs(cols, 1)
        return len(dots) >= 2 and all(b - a <= 10 * s for a, b in dots)

    def read_options(self, frame: np.ndarray) -> list[str]:
        lines = [clean_option(s) for s in self._ocr_lines(self._crop(frame, self.regions["options"]))]
        return [s for s in lines if len(s) >= 2]

    def read(self, frame: np.ndarray, with_options: bool = True) -> DialogueState:
        div = self.find_divider(frame)
        if div is None:
            return DialogueState(False)
        return DialogueState(True, self.read_name(frame), self.read_text(frame, div),
                             self.read_options(frame) if with_options else [])

    def debug_image(self, frame: np.ndarray) -> Image.Image:
        """把各區域框起來，給 UI 的「擷取預覽」用。"""
        from PIL import ImageDraw

        img = Image.fromarray(np.ascontiguousarray(frame[..., :3]))
        d = ImageDraw.Draw(img)
        h, w = frame.shape[:2]
        colors = {"name": (255, 200, 0), "text": (0, 200, 255), "options": (0, 255, 120)}
        div = self.find_divider(frame)
        for k, box in self.regions.items():
            if k == "text":
                box = self.text_box(div)
            d.rectangle(self._scale(box, w, h), outline=colors.get(k, (255, 0, 0)), width=3)
        y = int((div.y if div else 899) * h / BASE_H)
        d.line([(int(400 * w / BASE_W), y), (int(1520 * w / BASE_W), y)],
               fill=(0, 255, 0) if div else (255, 0, 0), width=2)
        return img
