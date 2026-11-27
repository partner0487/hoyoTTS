"""自動過劇情用的輸入：對遊戲視窗按鍵、點擊。

只在遊戲視窗是前景時才送出，避免點到其他程式。
原神以系統管理員身分執行，Windows 的 UIPI 會擋掉一般權限程式送給它的輸入（而且不會回報錯誤），
所以 hoyoTTS 也要以系統管理員身分執行，這個功能才有作用。
"""

from __future__ import annotations

import ctypes
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


def is_foreground(hwnd: int | None) -> bool:
    return bool(hwnd) and user32.GetForegroundWindow() == hwnd


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
