"""全域快捷鍵（RegisterHotKey），遊戲在前景時也能用。

原神以系統管理員身分執行。如果在遊戲裡按快捷鍵沒反應，請用系統管理員身分執行 hoyoTTS。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as W
import threading
from typing import Callable

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_NOREPEAT = 0x4000


_MODS = {"ALT": 0x1, "CTRL": 0x2, "SHIFT": 0x4, "WIN": 0x8}


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """"Ctrl+F8" → (modifiers, vk)。"""
    *mods, key = [p.strip().upper() for p in text.split("+")]
    m = 0
    for p in mods:
        if p not in _MODS:
            return None
        m |= _MODS[p]
    if len(key) >= 2 and key[0] == "F" and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return m, 0x6F + int(key[1:])
    if len(key) == 1 and key.isalnum():
        return m, ord(key)
    return None


class GlobalHotkeys:
    def __init__(self, log: Callable[[str], None] = print):
        self.log = log
        self._bindings: dict[int, tuple[str, Callable[[], None]]] = {}
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._ready = threading.Event()

    def start(self, bindings: dict[str, Callable[[], None]]) -> None:
        """bindings：{"F8": callback}。在自己的執行緒註冊與收訊息（RegisterHotKey 綁定呼叫的執行緒）。"""
        self.stop()
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, args=(bindings,), name="hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(2)

    def stop(self) -> None:
        if self._thread and self._thread.is_alive() and self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(2)
        self._thread = None

    def _run(self, bindings: dict[str, Callable[[], None]]) -> None:
        self._tid = kernel32.GetCurrentThreadId()
        ids = []
        for i, (key, cb) in enumerate(bindings.items(), start=1):
            parsed = parse_hotkey(key)
            if parsed is None:
                self.log(f"快捷鍵 {key} 無法辨識")
                continue
            if user32.RegisterHotKey(None, i, MOD_NOREPEAT | parsed[0], parsed[1]):
                self._bindings[i] = (key, cb)
                ids.append(i)
            else:
                self.log(f"快捷鍵 {key} 註冊失敗（可能被其他程式占用）")
        self._ready.set()
        msg = W.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in self._bindings:
                try:
                    self._bindings[msg.wParam][1]()
                except Exception as e:
                    self.log(f"快捷鍵處理錯誤：{e}")
        for i in ids:
            user32.UnregisterHotKey(None, i)
        self._bindings.clear()
