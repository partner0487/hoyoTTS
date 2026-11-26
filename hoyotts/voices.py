"""角色語音模型：列出、下載、比對角色名。

模型來源：ModelScope aihobbyist/GPT-SoVITS_Model_Collection（CC-BY-NC，禁止商用與二次散布）。
每個角色一個 zip，解壓後結構：
    <models_dir>/<遊戲>/<語言>/<角色>_ZH/
        *.ckpt                                  GPT 權重
        *.pth                                   SoVITS 權重
        reference_audios/中文/emotions/【情緒】台詞.wav
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import threading
import urllib.parse
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Iterable

import requests

REPO = "aihobbyist/GPT-SoVITS_Model_Collection"
FILE_LIST_URL = f"https://www.modelscope.cn/api/v1/models/{REPO}/repo/files?Revision=master&Recursive=true"
FILE_URL = f"https://www.modelscope.cn/models/{REPO}/resolve/master/"

DEFAULT_GAME = "原神"
DEFAULT_LANG = "中文"

_SUFFIX_RE = re.compile(r"_(ZH|JA|EN|KO)$")
_EMOTION_RE = re.compile(r"^【(.+?)】(.*)$")


@dataclass
class RemoteModel:
    name: str  # 角色名（不含 _ZH）
    path: str  # 在 repo 裡的路徑
    size: int
    sha256: str


@dataclass
class Voice:
    name: str
    dir: str
    gpt_path: str
    sovits_path: str
    ref_audio: str
    ref_text: str
    emotion: str


def strip_suffix(name: str) -> str:
    return _SUFFIX_RE.sub("", name)


def normalize(name: str) -> str:
    """比對用：去掉引號、空白、標點。輸入應已是簡體。"""
    return re.sub(r"[「」『』\"'“”·・\s\.,，。:：!！?？]", "", name)


def list_remote(game: str = DEFAULT_GAME, lang: str = DEFAULT_LANG, timeout: float = 60) -> list[RemoteModel]:
    r = requests.get(FILE_LIST_URL, timeout=timeout)
    r.raise_for_status()
    prefix = f"{game}/{lang}/"
    out = []
    for f in r.json()["Data"]["Files"]:
        if f["Type"] != "blob" or not f["Path"].startswith(prefix) or not f["Name"].endswith(".zip"):
            continue
        out.append(RemoteModel(strip_suffix(f["Name"][:-4]), f["Path"], f["Size"], f.get("Sha256", "")))
    return out


def lang_dir(models_dir: str, game: str = DEFAULT_GAME, lang: str = DEFAULT_LANG) -> str:
    return os.path.join(models_dir, game, lang)


def _extract(zip_path: str, dest: str) -> None:
    """zip 內檔名是 GBK，但沒有設 UTF-8 旗標，zipfile 會用 cp437 解。這裡轉回來，
    並把最上層的版本資料夾（如 v4/）攤平。"""
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename
            if not info.flag_bits & 0x800:
                try:
                    name = name.encode("cp437").decode("gbk")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
            parts = [p for p in name.replace("\\", "/").split("/") if p]
            if parts and re.fullmatch(r"v\d+\w*", parts[0]):
                parts = parts[1:]
            if not parts or ".." in parts:
                continue
            target = os.path.join(dest, *parts)
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)


def download(model: RemoteModel, models_dir: str, game: str = DEFAULT_GAME, lang: str = DEFAULT_LANG,
             progress: Callable[[str, int, int], None] | None = None, stop: threading.Event | None = None) -> bool:
    """下載並解壓一個角色。已存在就跳過。中斷後可續傳。回傳是否成功。"""
    dest = lang_dir(models_dir, game, lang)
    if find_local(dest, model.name):
        return True
    os.makedirs(dest, exist_ok=True)
    part = os.path.join(dest, f".{model.name}.zip.part")
    url = FILE_URL + urllib.parse.quote(model.path)
    have = os.path.getsize(part) if os.path.exists(part) else 0
    if have < model.size:
        headers = {"Range": f"bytes={have}-"} if have else {}
        with requests.get(url, headers=headers, stream=True, timeout=60) as r:
            if r.status_code == 200:
                have = 0  # 伺服器不支援續傳，從頭來
            elif r.status_code != 206:
                r.raise_for_status()
            with open(part, "ab" if have else "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    if stop is not None and stop.is_set():
                        return False
                    f.write(chunk)
                    have += len(chunk)
                    if progress:
                        progress(model.name, have, model.size)
    if model.sha256:
        h = hashlib.sha256()
        with open(part, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 22), b""):
                h.update(chunk)
        if h.hexdigest() != model.sha256:
            os.remove(part)
            raise IOError(f"{model.name}: sha256 不符，已刪除重下")
    tmp = os.path.join(dest, f".{model.name}.extracting")
    shutil.rmtree(tmp, ignore_errors=True)
    _extract(part, tmp)
    # 解壓後應該只有一個 <角色>_ZH 資料夾
    inner = [os.path.join(tmp, d) for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d))]
    src = inner[0] if len(inner) == 1 else tmp
    final = os.path.join(dest, os.path.basename(src) if src != tmp else model.name)
    shutil.rmtree(final, ignore_errors=True)
    shutil.move(src, final)
    shutil.rmtree(tmp, ignore_errors=True)
    os.remove(part)
    return True


def download_many(models: Iterable[RemoteModel], models_dir: str, workers: int = 3,
                  log: Callable[[str], None] = print, stop: threading.Event | None = None, **kw) -> list[str]:
    """平行下載，回傳失敗的角色名。"""
    failed = []

    def one(m: RemoteModel):
        for attempt in range(3):
            if stop is not None and stop.is_set():
                return
            try:
                if download(m, models_dir, stop=stop, **kw):
                    log(f"完成 {m.name}")
                return
            except Exception as e:  # 網路錯誤就重試
                log(f"{m.name} 第 {attempt + 1} 次失敗：{e}")
        failed.append(m.name)

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, list(models)))
    return failed


def find_local(dir_: str, name: str) -> str | None:
    for cand in (f"{name}_ZH", name):
        p = os.path.join(dir_, cand)
        if os.path.isdir(p) and any(f.endswith(".pth") for f in os.listdir(p)):
            return p
    return None


def load_voice(dir_: str) -> Voice | None:
    """讀一個角色資料夾。參考音優先用【默认】，否則用第一個。"""
    files = os.listdir(dir_)
    gpt = [f for f in files if f.endswith(".ckpt")]
    sov = [f for f in files if f.endswith(".pth")]
    if not gpt or not sov:
        return None
    refs = []
    for root, _, fs in os.walk(os.path.join(dir_, "reference_audios")):
        refs += [os.path.join(root, f) for f in fs if f.lower().endswith(".wav")]
    if not refs:
        return None

    def key(p):
        m = _EMOTION_RE.match(os.path.splitext(os.path.basename(p))[0])
        emo = m.group(1) if m else ""
        return (0 if emo == "默认" else 1, p)

    ref = sorted(refs, key=key)[0]
    stem = os.path.splitext(os.path.basename(ref))[0]
    m = _EMOTION_RE.match(stem)
    emotion, text = (m.group(1), m.group(2)) if m else ("", stem)
    return Voice(strip_suffix(os.path.basename(dir_)), dir_, os.path.join(dir_, sorted(gpt)[0]),
                 os.path.join(dir_, sorted(sov)[0]), ref, text, emotion)


class VoiceLibrary:
    """本機已下載的角色，提供用 OCR 角色名找聲音。"""

    def __init__(self, models_dir: str, game: str = DEFAULT_GAME, lang: str = DEFAULT_LANG,
                 aliases: dict[str, str] | None = None):
        self.dir = lang_dir(models_dir, game, lang)
        self.aliases = {normalize(k): v for k, v in (aliases or {}).items()}
        self.voices: dict[str, Voice] = {}
        self.reload()

    def reload(self) -> None:
        self.voices.clear()
        if not os.path.isdir(self.dir):
            return
        for d in sorted(os.listdir(self.dir)):
            p = os.path.join(self.dir, d)
            if d.startswith(".") or not os.path.isdir(p):
                continue
            v = load_voice(p)
            if v:
                self.voices[v.name] = v
        self._norm = {normalize(n): n for n in self.voices}

    def names(self) -> list[str]:
        return list(self.voices)

    def get(self, name: str) -> Voice | None:
        return self.voices.get(name)

    def match(self, speaker: str, min_score: float = 85) -> Voice | None:
        """speaker 需為簡體。先查別名、再精確比對、最後模糊比對（容忍 OCR 錯一兩個字）。"""
        key = normalize(speaker)
        if not key:
            return None
        if key in self.aliases:
            return self.voices.get(self.aliases[key])
        if key in self._norm:
            return self.voices[self._norm[key]]
        if len(key) < 2:
            return None
        from rapidfuzz import fuzz, process

        best = process.extractOne(key, list(self._norm), scorer=fuzz.ratio)
        if best and best[1] >= min_score:
            return self.voices[self._norm[best[0]]]
        return None


def _main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="下載 GPT-SoVITS 角色模型")
    ap.add_argument("--dir", default=None, help="模型資料夾（預設讀 config.json）")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("names", nargs="*", help="角色名（簡體，不含 _ZH）；不給就全部下載")
    a = ap.parse_args()
    if a.dir is None:
        from .config import load_config

        a.dir = load_config()["models_dir"]
    remote = list_remote()
    if a.names:
        remote = [m for m in remote if m.name in a.names]
    todo = [m for m in remote if not find_local(lang_dir(a.dir), m.name)]
    print(f"共 {len(remote)} 個，要下載 {len(todo)} 個，約 {sum(m.size for m in todo) / 1e9:.1f} GB → {a.dir}", flush=True)
    failed = download_many(todo, a.dir, a.workers, log=lambda s: print(s, flush=True))
    print("失敗：" + "、".join(failed) if failed else "全部完成", flush=True)


if __name__ == "__main__":
    _main()
