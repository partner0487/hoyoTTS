"""下載 GPT-SoVITS 推理需要的底模與資料（等同官方 install.ps1 的下載部分）。

官方 install.ps1 需要在 conda activate 過的互動式 PowerShell 裡跑，
這個腳本只負責下載，套件請照 README 用 pip 安裝。

    python tools/setup_gsv.py [--source HF|HF-Mirror|ModelScope]
"""

import argparse
import os
import shutil
import sys
import tarfile
import tempfile
import zipfile

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GSV = os.path.join(ROOT, "GPT-SoVITS")
SOURCES = {
    "HF": "https://huggingface.co/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/",
    "HF-Mirror": "https://hf-mirror.com/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/",
    "ModelScope": "https://www.modelscope.cn/models/XXXXRT/GPT-SoVITS-Pretrained/resolve/master/",
}


def fetch(url: str, dest: str) -> None:
    print(f"下載 {url}", flush=True)
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        got = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                got += len(chunk)
                if total:
                    print(f"\r  {got / 1e6:.0f}/{total / 1e6:.0f} MB", end="", flush=True)
    print(flush=True)


def unzip(path: str, dest: str) -> None:
    with zipfile.ZipFile(path) as z:
        for m in z.namelist():
            target = os.path.realpath(os.path.join(dest, m))
            if not target.startswith(os.path.realpath(dest)):
                raise ValueError(f"zip 內有不安全的路徑：{m}")
        z.extractall(dest)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=SOURCES, default="HF")
    base = SOURCES[ap.parse_args().source]
    if not os.path.isdir(os.path.join(GSV, "GPT_SoVITS")):
        sys.exit("找不到 GPT-SoVITS 資料夾，請先執行 git submodule update --init")

    tmp = tempfile.mkdtemp()
    try:
        steps = [
            ("pretrained_models.zip", os.path.join(GSV, "GPT_SoVITS"), os.path.join(GSV, "GPT_SoVITS", "pretrained_models", "sv")),
            ("G2PWModel.zip", os.path.join(GSV, "GPT_SoVITS", "text"), os.path.join(GSV, "GPT_SoVITS", "text", "G2PWModel")),
            ("nltk_data.zip", sys.prefix, os.path.join(sys.prefix, "nltk_data")),
        ]
        for name, dest, done_marker in steps:
            if os.path.exists(done_marker):
                print(f"{name} 已存在，略過")
                continue
            p = os.path.join(tmp, name)
            fetch(base + name, p)
            unzip(p, dest)

        import pyopenjtalk

        dic_dir = os.path.dirname(pyopenjtalk.__file__)
        if not os.path.isdir(os.path.join(dic_dir, "open_jtalk_dic_utf_8-1.11")):
            p = os.path.join(tmp, "open_jtalk_dic.tar.gz")
            fetch(base + "open_jtalk_dic_utf_8-1.11.tar.gz", p)
            with tarfile.open(p) as t:
                t.extractall(dic_dir, filter="data")
        else:
            print("Open JTalk 字典已存在，略過")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("完成")


if __name__ == "__main__":
    main()
