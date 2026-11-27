"""設定：預設值寫在這裡，使用者改過的存到專案根目錄的 config.json。"""

from __future__ import annotations

import copy
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")

# 區域座標以 1920×1080 為基準，實際會依遊戲畫面大小等比換算。
DEFAULTS: dict = {
    "models_dir": r"D:\hoyoTTS_models",
    "game": "原神",
    "lang": "中文",
    "process_name": "GenshinImpact.exe",
    "server": {"host": "127.0.0.1", "port": 9880, "autostart": True},
    "voices": {
        "fallback": "空",   # 找不到對應模型的 NPC
        "options": "空",    # 旅行者的對話選項
        "narrator": "旁白",  # 沒有角色名的旁白
    },
    "aliases": {},  # OCR 角色名（簡體）→ 模型名，例如 {"旅行者": "空"}
    "read_options": True,
    # 文字辨識："rapid"＝RapidOCR（PaddleOCR 模型，較準，讀不到時才用 Windows OCR）；"windows"＝只用 Windows OCR
    "ocr_engine": "rapid",
    "volume": 1.0,
    "speed": 1.0,
    "sample_steps": 32,
    "poll_interval": 0.15,  # 秒
    "stable_frames": 2,     # 文字連續幾次不變才開始念（等打字動畫結束）
    # 念到剩不到這麼多秒時點下一段：先念完這句，下一句在背景合成好接著念。
    # 剩更多才點就當作要跳過，立刻打斷。0＝一律打斷。
    "finish_tail": 3.0,
    # 自動過劇情：台詞念完按空白鍵（line_action="click" 改成點對話框），選項念完按 F 選第一個。
    # method="window" 直接送給原神視窗（不動滑鼠、遊戲在背景也可以）；"screen" 模擬真的鍵盤滑鼠（遊戲要在前景）。
    # 都要以系統管理員身分執行（原神是系統管理員身分）。
    "auto_play": {"enabled": False, "delay": 0.6, "method": "window", "line_action": "space",
                  "click": [960, 950], "option_key": "F"},
    "hotkeys": {"stop": "Ctrl+F7", "pause": "Ctrl+F8", "replay": "Ctrl+F9"},  # 單獨 F7–F9 常被其他程式占用，F1–F5 是遊戲的
    "regions": {
        "name": [560, 845, 1360, 895],
        "text": [260, 903, 1660, 1000],
        "options": [1318, 380, 1830, 845],
    },
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str = CONFIG_PATH) -> dict:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return _merge(DEFAULTS, json.load(f))
    return copy.deepcopy(DEFAULTS)


def save_config(cfg: dict, path: str = CONFIG_PATH) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
