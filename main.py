"""hoyoTTS：擷取原神畫面，OCR 出劇情對話，用本機 GPT-SoVITS 角色語音念出來。

    python main.py           開啟圖形介面
    python main.py --nogui   不開介面，直接在終端機執行（Ctrl+C 結束）
"""

import argparse
import sys
import time


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
    args = ap.parse_args()
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.nogui:
        run_headless()
    else:
        from hoyotts.ui import run

        run()


if __name__ == "__main__":
    main()
