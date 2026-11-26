"""啟動本機 GPT-SoVITS API（api_v2.py），並關掉 cudnn.benchmark。

GPT-SoVITS 的 GPT_SoVITS/Accel/PyTorch 在 import 時設定 cudnn.benchmark = True，
每遇到新的輸入長度就重新搜尋卷積演算法。遊戲台詞每句長度都不同，
實測 4090 上每句會多花 4–5 秒，所以先 import 那個模組再把它關掉，
之後 api_v2 再 import 時會拿到快取的模組，不會被設回 True。

另外加一個 /stop：中止正在合成的句子（玩家已經點到下一句時用）。

用法（參數直接轉給 api_v2.py）：
    python tts_server.py [-a 127.0.0.1] [-p 9880]
"""

import os
import runpy
import sys

GSV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "GPT-SoVITS")

os.chdir(GSV_DIR)  # api_v2 與設定檔都用相對於 GPT-SoVITS 根目錄的路徑
sys.path.insert(0, GSV_DIR)

import torch  # noqa: E402
import GPT_SoVITS.Accel.PyTorch  # noqa: E402,F401  在 import 時把 benchmark 設成 True

torch.backends.cudnn.benchmark = False

# 角色模型都是 v4，啟動時直接載 v4 底模（GPT-SoVITS 預設會先載 v2）。
# 設定檔放在專案根目錄、不放進 git。api_v2 切換角色時會把路徑改寫成該角色的權重，
# 所以每次啟動都重寫，免得那個角色的模型被刪掉後伺服器起不來。
CONFIG = os.path.join(os.path.dirname(GSV_DIR), "tts_infer.yaml")
with open(CONFIG, "w", encoding="utf-8") as f:
    f.write(
        "custom:\n"
        "  bert_base_path: GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large\n"
        "  cnhuhbert_base_path: GPT_SoVITS/pretrained_models/chinese-hubert-base\n"
        f"  device: {'cuda' if torch.cuda.is_available() else 'cpu'}\n"
        f"  is_half: {'true' if torch.cuda.is_available() else 'false'}\n"
        "  t2s_weights_path: GPT_SoVITS/pretrained_models/s1v3.ckpt\n"
        "  version: v4\n"
        "  vits_weights_path: GPT_SoVITS/pretrained_models/gsv-v4-pretrained/s2Gv4.pth\n"
    )
args = sys.argv[1:]
if "-c" not in args and "--tts_config" not in args:
    args = ["-c", CONFIG] + args

sys.argv = [os.path.join(GSV_DIR, "api_v2.py")] + args
# 不用 run_name="__main__"，這樣 api_v2 只會建好 APP 與模型、不會自己啟動 uvicorn，
# 讓我們先加上 /stop 再啟動。
g = runpy.run_path(sys.argv[0], run_name="hoyotts_api_v2")
APP, tts_pipeline = g["APP"], g["tts_pipeline"]


@APP.get("/stop")
async def stop_current():
    """中止正在合成的句子（在句子切段之間生效）。玩家點到下一句時用。"""
    tts_pipeline.stop()
    return {"message": "stopping"}


if __name__ == "__main__":
    import uvicorn

    host = g["host"]
    uvicorn.run(app=APP, host=None if host == "None" else host, port=g["port"], workers=1)
