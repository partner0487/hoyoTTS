"""擷取遊戲視窗畫面。

主要用 Windows Graphics Capture（WGC）直接擷取原神視窗，被其他視窗蓋住也拍得到；
WGC 不能用時改用 GDI 擷取遊戲視窗所在的螢幕範圍。
原神以系統管理員身分執行，這兩種方式都不需要提權。最小化的視窗拍不到。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as W
import os
import threading
import time

import numpy as np

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DEFAULT_PROCESSES = ("GenshinImpact.exe", "YuanShen.exe")


def _process_name(hwnd: int) -> str:
    pid = W.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = W.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        kernel32.CloseHandle(h)


def find_game_window(process_names=DEFAULT_PROCESSES) -> int | None:
    """依執行檔名稱找遊戲主視窗（不用標題比對，避免抓到標題剛好有「原神」的瀏覽器）。"""
    names = {n.lower() for n in process_names}
    found: list[int] = []

    @ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and user32.GetWindow(hwnd, 4) == 0:  # GW_OWNER
            if _process_name(hwnd).lower() in names:
                found.append(hwnd)
                return False
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def client_rect_on_screen(hwnd: int) -> tuple[int, int, int, int]:
    r = W.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    pt = W.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, pt.x + r.right, pt.y + r.bottom


def is_minimized(hwnd: int) -> bool:
    return bool(user32.IsIconic(hwnd))


class GameCapture:
    """在背景持續擷取，latest() 取最新一張 RGB 畫面（numpy, H×W×3）。"""

    def __init__(self, process_names=DEFAULT_PROCESSES, backend: str = "auto", interval_ms: int = 100):
        self.process_names = process_names
        self.backend = backend
        self.interval_ms = interval_ms
        self.hwnd: int | None = None
        self.status = "未啟動"
        self.active_backend = ""
        self._frame: np.ndarray | None = None  # BGRA 或 RGB，見 _frame_is_bgra
        self._frame_is_bgra = False
        self._frame_time = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._wgc_ctl = None
        self._wgc_closed = threading.Event()

    # ---- 公開介面 ----
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="GameCapture", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._stop_wgc()
        if self._thread:
            self._thread.join(timeout=3)
        self.status = "已停止"

    def latest(self, max_age: float = 2.0) -> np.ndarray | None:
        """最新畫面（RGB）。WGC 只在畫面有變化時送新幀，所以靜止畫面的舊幀仍然有效；
        視窗最小化或找不到時回傳 None。"""
        if self.active_backend == "gdi":
            return self._grab_gdi()
        with self._lock:
            f, bgra = self._frame, self._frame_is_bgra
        if f is None or self.hwnd is None or is_minimized(self.hwnd):
            return None
        return f[..., 2::-1] if bgra else f

    # ---- 內部 ----
    def _run(self) -> None:
        while not self._stop.is_set():
            hwnd = find_game_window(self.process_names)
            if hwnd is None:
                self.hwnd = None
                self.status = "找不到遊戲視窗"
                self._stop.wait(2)
                continue
            if is_minimized(hwnd):
                self.hwnd = hwnd
                self.status = "遊戲已最小化"
                self._stop.wait(1)
                continue
            if hwnd != self.hwnd:
                self._stop_wgc()
                with self._lock:
                    self._frame = None
            self.hwnd = hwnd
            if self.backend in ("auto", "wgc") and self._run_wgc(hwnd):
                continue
            if self.backend in ("auto", "gdi"):
                self._run_gdi(hwnd)

    def _run_wgc(self, hwnd: int) -> bool:
        """跑 WGC 直到視窗關閉／最小化／換視窗。回傳 False 代表 WGC 不能用。"""
        try:
            from windows_capture import WindowsCapture
        except ImportError:
            return False
        self._wgc_closed.clear()
        try:
            cap = WindowsCapture(cursor_capture=False, draw_border=False, window_hwnd=hwnd,
                                 minimum_update_interval=self.interval_ms)
        except Exception as e:
            self.status = f"WGC 無法使用：{e}"
            return False

        @cap.event
        def on_frame_arrived(frame, ctl):
            buf = frame.frame_buffer
            with self._lock:
                self._frame = buf.copy()
                self._frame_is_bgra = True
                self._frame_time = time.time()

        @cap.event
        def on_closed():
            self._wgc_closed.set()

        try:
            self._wgc_ctl = cap.start_free_threaded()
        except Exception as e:
            self.status = f"WGC 無法使用：{e}"
            return False
        self.active_backend = "wgc"
        self.status = "擷取中（WGC）"
        while not self._stop.is_set() and not self._wgc_closed.is_set():
            if not user32.IsWindow(hwnd) or is_minimized(hwnd):
                break
            self._stop.wait(0.5)
        self._stop_wgc()
        return True

    def _stop_wgc(self) -> None:
        ctl, self._wgc_ctl = self._wgc_ctl, None
        if ctl is not None:
            try:
                ctl.stop()
            except Exception:
                pass

    def _run_gdi(self, hwnd: int) -> None:
        self.active_backend = "gdi"
        self.status = "擷取中（GDI 螢幕擷取）"
        while not self._stop.is_set() and user32.IsWindow(hwnd) and not is_minimized(hwnd):
            self._stop.wait(0.5)

    def _grab_gdi(self) -> np.ndarray | None:
        """備用：擷取遊戲視窗所在的螢幕範圍（被其他視窗蓋住時會拍到那個視窗）。
        不用 dxcam，因為 screen_ocr 會自己建立 dxcam 實例，同一張顯卡只能有一個。"""
        from PIL import ImageGrab

        hwnd = self.hwnd
        if hwnd is None or is_minimized(hwnd):
            return None
        l, t, r, b = client_rect_on_screen(hwnd)
        if r <= l or b <= t:
            return None
        return np.asarray(ImageGrab.grab(bbox=(l, t, r, b), all_screens=True).convert("RGB"))
