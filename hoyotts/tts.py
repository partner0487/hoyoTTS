"""本機 GPT-SoVITS API（api_v2.py）：啟動伺服器、切換角色權重、合成語音、播放。"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import threading
import time
from typing import Callable

import numpy as np
import requests

from .config import ROOT
from .voices import Voice


class TTSServer:
    """用 tts_server.py 在背景啟動 api_v2；如果已經有伺服器在跑就直接用。"""

    def __init__(self, host: str = "127.0.0.1", port: int = 9880, log: Callable[[str], None] = print,
                 log_name: str = "tts_server.log", label: str = "TTS 伺服器"):
        self.host, self.port = host, port
        self.base = f"http://{host}:{port}"
        self.log = log
        self.label = label
        self.proc: subprocess.Popen | None = None
        self.log_path = os.path.join(ROOT, log_name)

    def alive(self) -> bool:
        try:
            return requests.get(f"{self.base}/docs", timeout=2).status_code == 200
        except requests.RequestException:
            return False

    def start(self, timeout: float = 300) -> bool:
        if self.alive():
            self.log(f"{self.label}已在執行")
            return True
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        # conda 環境的 ffmpeg 在 Library\bin，沒用 conda activate 啟動時要自己加
        lib_bin = os.path.join(os.path.dirname(sys.executable), "Library", "bin")
        env["PATH"] = lib_bin + os.pathsep + env.get("PATH", "")
        logf = open(self.log_path, "w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "tts_server.py"), "-a", self.host, "-p", str(self.port)],
            cwd=ROOT, env=env, stdout=logf, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.log(f"啟動{self.label}中（第一次約 30 秒）…")
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.proc.poll() is not None:
                self.log(f"{self.label}啟動失敗，請看 {self.log_path}")
                return False
            if self.alive():
                self.log(f"{self.label}已就緒（{time.time() - t0:.0f} 秒）")
                return True
            time.sleep(1)
        self.log(f"{self.label}啟動逾時")
        return False

    def stop(self) -> None:
        """只關掉自己啟動的伺服器。"""
        if self.proc and self.proc.poll() is None:
            try:
                requests.get(f"{self.base}/control", params={"command": "exit"}, timeout=2)
            except requests.RequestException:
                pass
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


class TTSClient:
    def __init__(self, base: str):
        self.base = base
        self.loaded: str | None = None  # 目前載入的角色資料夾
        self._lock = threading.Lock()

    def stop(self) -> None:
        """請伺服器中止目前的合成（tts_server.py 加的 /stop；直接跑 api_v2 時沒有，忽略即可）。"""
        try:
            requests.get(f"{self.base}/stop", timeout=2)
        except requests.RequestException:
            pass

    def _set(self, endpoint: str, path: str) -> None:
        r = requests.get(f"{self.base}/{endpoint}", params={"weights_path": path}, timeout=120)
        if r.status_code != 200:
            raise RuntimeError(f"{endpoint} 失敗：{r.text[:200]}")

    def synth(self, text: str, voice: Voice, speed: float = 1.0, sample_steps: int = 32) -> tuple[np.ndarray, int]:
        """回傳 (float32 音訊, 取樣率)。同一角色連續說話不會重載權重（換角色約 3 秒）。"""
        import soundfile as sf

        with self._lock:
            if self.loaded != voice.dir:
                self._set("set_gpt_weights", voice.gpt_path)
                self._set("set_sovits_weights", voice.sovits_path)
                self.loaded = voice.dir
            r = requests.post(f"{self.base}/tts", json={
                "text": text, "text_lang": "zh",
                "ref_audio_path": voice.ref_audio, "prompt_text": voice.ref_text, "prompt_lang": "zh",
                "text_split_method": "cut5", "batch_size": 1, "media_type": "wav",
                "speed_factor": speed, "sample_steps": sample_steps,
            }, timeout=300)
        if r.status_code != 200:
            raise RuntimeError(f"合成失敗：{r.text[:300]}")
        data, sr = sf.read(io.BytesIO(r.content), dtype="float32")
        return data, sr


class Player:
    """非阻塞播放，可以中途停止。"""

    def __init__(self):
        import sounddevice as sd

        self.sd = sd
        self._end = 0.0

    def play(self, data: np.ndarray, sr: int, volume: float = 1.0) -> None:
        self.sd.stop()
        self.sd.play(np.clip(data * volume, -1, 1), sr)
        self._end = time.time() + len(data) / sr

    def stop(self) -> None:
        self.sd.stop()
        self._end = 0.0

    def busy(self) -> bool:
        return time.time() < self._end

    def remaining(self) -> float:
        """這句還剩幾秒。"""
        return max(0.0, self._end - time.time())

