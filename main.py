"""hoyoTTS：擷取原神畫面，OCR 出劇情對話，用本機 GPT-SoVITS 角色語音念出來。

    python main.py             開啟圖形介面
    python main.py --nogui     不開介面，直接在終端機執行（Ctrl+C 結束）
    python main.py --no-admin  不要求系統管理員權限

預設會以系統管理員身分執行（跳出 UAC）：原神是系統管理員身分，一般權限程式送給它的
快捷鍵和自動過劇情的點擊都會被 Windows 擋掉。UAC 按「否」就用一般權限繼續。
"""

import argparse
import os
import sys
import time


def ensure_admin(args: argparse.Namespace) -> bool:
    """不是系統管理員就以系統管理員身分重開自己。回傳 True 表示已經重開，這個程序要結束。"""
    if args.no_admin or os.environ.get("HOYOTTS_ADMIN_DECLINED"):
        return False
    from hoyotts.gameinput import is_admin, relaunch_as_admin

    if is_admin():
        return False
    if relaunch_as_admin(console=args.nogui):
        return True
    # UAC 按了「否」：繼續用一般權限，介面裡也不要再問
    os.environ["HOYOTTS_ADMIN_DECLINED"] = "1"
    print("沒有取得系統管理員權限，用一般權限執行（遊戲裡的快捷鍵和自動過劇情可能沒有作用）")
    return False


def tell_already_running(nogui: bool) -> None:
    msg = "hoyoTTS 已經在執行了（可能縮在工作列或其他視窗後面）。\n同時開兩個會互搶語音伺服器，每句都會變很慢。"
    if nogui:
        print(msg)
        return
    import ctypes

    ctypes.windll.user32.MessageBoxW(None, msg, "hoyoTTS", 0x40)


def run_headless() -> None:
    from hoyotts.config import load_config
    from hoyotts.engine import Engine
    from hoyotts.hotkeys import GlobalHotkeys

    cfg = load_config()
    engine = Engine(cfg)
    hk = cfg["hotkeys"]
    hotkeys = GlobalHotkeys()
    hotkeys.start({hk["stop"]: engine.interrupt, hk["pause"]: lambda: engine.set_paused(not engine.state.paused),
                   hk["replay"]: engine.replay})
    print(f"已載入 {len(engine.library.names())} 個角色模型；快捷鍵：停止 {hk['stop']}、暫停 {hk['pause']}、重念 {hk['replay']}")
    engine.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        hotkeys.stop()
        engine.shutdown()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nogui", action="store_true", help="不開介面")
    ap.add_argument("--no-admin", action="store_true", help="不要求系統管理員權限")
    args = ap.parse_args()
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if ensure_admin(args):
        return
    from hoyotts.gameinput import already_running

    if already_running():
        tell_already_running(args.nogui)
        return
    if args.nogui:
        run_headless()
    else:
        from hoyotts.ui import run

        run()


if __name__ == "__main__":
    main()
