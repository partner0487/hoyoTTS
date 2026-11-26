"""檢查已下載的角色模型：每個都載入並合成一句短句，列出不能用的。

    python tools/check_models.py            檢查全部
    python tools/check_models.py 派蒙 空     只檢查指定角色（簡體名）

TTS 伺服器沒在跑會自動啟動，檢查完關掉。不會播放聲音。
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hoyotts.config import load_config  # noqa: E402
from hoyotts.tts import TTSClient, TTSServer  # noqa: E402
from hoyotts.voices import VoiceLibrary, lang_dir  # noqa: E402

TEXT = "你好，旅行者。"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg = load_config()
    lib = VoiceLibrary(cfg["models_dir"], cfg["game"], cfg["lang"])
    names = sys.argv[1:] or lib.names()

    # 資料夾在但載不起來（缺權重或參考音）的
    folder = lang_dir(cfg["models_dir"], cfg["game"], cfg["lang"])
    broken = []
    if not sys.argv[1:] and os.path.isdir(folder):
        for d in sorted(os.listdir(folder)):
            n = d[:-3] if d.endswith("_ZH") else d
            if not d.startswith(".") and os.path.isdir(os.path.join(folder, d)) and n not in lib.voices:
                broken.append(n)

    server = TTSServer(cfg["server"]["host"], cfg["server"]["port"])
    if not server.start():
        sys.exit("TTS 伺服器啟動失敗")
    client = TTSClient(server.base)
    failed = []
    try:
        for i, name in enumerate(names, 1):
            v = lib.get(name)
            if v is None:
                failed.append((name, "沒有這個模型"))
                continue
            t = time.time()
            try:
                data, sr = client.synth(TEXT, v)
                secs = len(data) / sr
                peak = float(abs(data).max()) if len(data) else 0.0
                if secs < 0.3 or peak < 0.01:
                    failed.append((name, f"輸出幾乎沒有聲音（{secs:.1f} 秒，峰值 {peak:.3f}）"))
                    status = "✗"
                else:
                    status = "✓"
                print(f"[{i}/{len(names)}] {status} {name}  {time.time() - t:.1f}s  音長 {secs:.1f}s", flush=True)
            except Exception as e:
                failed.append((name, str(e)[:120]))
                print(f"[{i}/{len(names)}] ✗ {name}  {e}", flush=True)
    finally:
        server.stop()

    print()
    print(f"可用 {len(names) - len(failed)} / {len(names)}")
    for n in broken:
        print(f"  缺檔、無法載入：{n}")
    for n, why in failed:
        print(f"  失敗：{n}：{why}")


if __name__ == "__main__":
    main()
