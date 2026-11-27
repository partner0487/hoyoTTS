"""自動過劇情用的輸入：對遊戲視窗按鍵、點擊。

只在遊戲視窗是前景時才送出，避免點到其他程式。
原神以系統管理員身分執行，Windows 的 UIPI 會擋掉一般權限程式送給它的輸入（而且不會回報錯誤），
所以 hoyoTTS 也要以系統管理員身分執行，這個功能才有作用。
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

from .capture import client_rect_on_screen

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x0002, 0x0008
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MAPVK_VK_TO_VSC = 0

VK = {"F": 0x46, "SPACE": 0x20, "ENTER": 0x0D}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(*inputs: INPUT) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


_instance_mutex = None


def already_running() -> bool:
    """同時開兩個 hoyoTTS 會讀同一個畫面、把同一句送去合成兩次，還在同一個 TTS 伺服器上
    輪流切換角色權重，每句都慢很多。用具名 mutex 確認只有一個在跑（程序結束時自動釋放）。"""
    global _instance_mutex
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    _instance_mutex = k32.CreateMutexW(None, False, r"Local\hoyoTTS_single_instance")
    err = ctypes.get_last_error()
    # 183：已經有了；5：另一個是系統管理員身分開的，一般權限的程序打不開它
    return err in (183, 5) or not _instance_mutex


def release_instance() -> None:
    """以系統管理員身分重開前先放掉，新開的才不會以為已經有一個在跑。"""
    global _instance_mutex
    if _instance_mutex:
        ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(_instance_mutex))
        _instance_mutex = None


def relaunch_as_admin(args: list[str] | None = None, console: bool = False) -> bool:
    """以系統管理員身分重新開啟 hoyoTTS（會跳出 UAC 詢問）。回傳是否成功啟動（使用者按「否」就是 False）。
    介面版用 pythonw.exe 啟動，不會多開一個主控台視窗；console=True（--nogui）用 python.exe。"""
    exe = sys.executable
    w = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if not console and os.path.exists(w):
        exe = w
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    params = subprocess.list2cmdline([os.path.join(root, "main.py"), *(sys.argv[1:] if args is None else args)])
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, root, 1) > 32


def is_foreground(hwnd: int | None) -> bool:
    return bool(hwnd) and user32.GetForegroundWindow() == hwnd


# ---- 直接送到遊戲視窗（PostMessage）：不動到滑鼠游標和其他程式，遊戲不在前景也送得到 ----
WM_ACTIVATE, WA_ACTIVE = 0x0006, 1
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON = 0x0200, 0x0201, 0x0202, 0x0001
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL


def _post(hwnd: int, msg: int, wparam: int, lparam: int) -> None:
    if not user32.PostMessageW(hwnd, msg, wparam, lparam):
        err = ctypes.get_last_error()
        # 5 = ERROR_ACCESS_DENIED：UIPI 擋掉（hoyoTTS 權限比原神低）
        raise PermissionError(err, "權限不足，原神擋掉了輸入" if err == 5 else f"PostMessage 失敗（{err}）")


def post_key(hwnd: int, name: str) -> None:
    """對遊戲視窗按一下鍵。"""
    vk = VK[name.upper()]
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    _post(hwnd, WM_ACTIVATE, WA_ACTIVE, 0)  # 遊戲在背景時不先「啟用」會忽略輸入
    _post(hwnd, WM_KEYDOWN, vk, 1 | (scan << 16))
    time.sleep(0.05)
    _post(hwnd, WM_KEYUP, vk, 1 | (scan << 16) | (1 << 30) | (1 << 31))


def post_click(hwnd: int, x: int, y: int, base=(1920, 1080)) -> None:
    """對遊戲視窗的 (x, y)（以 1920×1080 為基準）點一下左鍵，不移動真的滑鼠。"""
    l, t, r, b = client_rect_on_screen(hwnd)
    cx, cy = int(x * (r - l) / base[0]), int(y * (b - t) / base[1])
    pos = (cy << 16) | (cx & 0xFFFF)
    _post(hwnd, WM_ACTIVATE, WA_ACTIVE, 0)
    _post(hwnd, WM_MOUSEMOVE, 0, pos)
    _post(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, pos)
    time.sleep(0.05)
    _post(hwnd, WM_LBUTTONUP, 0, pos)


def press_key(name: str) -> None:
    """用掃描碼按一下（遊戲多半讀掃描碼）。"""
    vk = VK[name.upper()]
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    down = INPUT(INPUT_KEYBOARD, _U(ki=KEYBDINPUT(0, scan, KEYEVENTF_SCANCODE, 0, 0)))
    up = INPUT(INPUT_KEYBOARD, _U(ki=KEYBDINPUT(0, scan, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0, 0)))
    _send(down)
    time.sleep(0.05)
    _send(up)


def click_at(hwnd: int, x: int, y: int, base=(1920, 1080)) -> None:
    """在遊戲畫面的 (x, y)（以 1920×1080 為基準）點一下左鍵，再把滑鼠移回原位。"""
    l, t, r, b = client_rect_on_screen(hwnd)
    sx, sy = l + int(x * (r - l) / base[0]), t + int(y * (b - t) / base[1])
    old = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(old))
    user32.SetCursorPos(sx, sy)
    time.sleep(0.03)
    _send(INPUT(INPUT_MOUSE, _U(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0))))
    time.sleep(0.05)
    _send(INPUT(INPUT_MOUSE, _U(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0))))
    time.sleep(0.03)
    user32.SetCursorPos(old.x, old.y)
