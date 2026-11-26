"""主流程：擷取畫面 → 判斷對話 → OCR → 找角色聲音 → 合成 → 播放。

兩條背景執行緒：
- watcher：每隔 poll_interval 拍一張、OCR。台詞連續 stable_frames 次相同（打字動畫結束）
  且跟上一句不同才送出。新台詞會打斷正在念的句子（玩家點過去了）。
- speaker：從佇列拿句子去合成、播放。合成期間如果又有新台詞，舊的結果直接丟掉。
"""

from __future__ import annotations

import queue
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable

from opencc import OpenCC

from .capture import GameCapture
from .dialogue import DialogueReader
from .tts import Player, TTSClient, TTSServer
from .voices import Voice, VoiceLibrary

_t2s = OpenCC("t2s")


def t2s(s: str) -> str:
    return _t2s.convert(s)


def _similar(a: str, b: str) -> float:
    from rapidfuzz import fuzz

    return fuzz.ratio(a, b)


def is_stable(prev: tuple | None, cur: tuple) -> bool:
    """連續兩幀是不是同一句完整台詞。背景動畫（雪花、角色走動）會讓 OCR 每幀差一兩個符號，
    所以用相似度；打字動畫期間每幀會多好幾個字，用長度差排除。"""
    if prev is None or prev[0] != cur[0]:
        return False
    return abs(len(prev[1]) - len(cur[1])) <= 2 and _similar(prev[1], cur[1]) >= 90


def same_line(a: tuple | None, b: tuple) -> bool:
    """是不是已經念過的那句（容忍 OCR 雜訊）。"""
    return a is not None and a[0] == b[0] and _similar(a[1], b[1]) >= 85


@dataclass
class Utterance:
    kind: str  # "line" / "options" / "test"
    speaker: str  # 畫面上的角色名（繁體）
    text: str  # 畫面上的台詞（繁體）
    voice: Voice
    gen: int
    note: str = ""


@dataclass
class EngineState:
    capture: str = "未啟動"
    server: str = "未啟動"
    running: bool = False
    paused: bool = False
    in_dialogue: bool = False
    name: str = ""
    text: str = ""
    options: list[str] = field(default_factory=list)
    speaking: str = ""


class Engine:
    def __init__(self, cfg: dict, log: Callable[[str], None] = print):
        self.cfg = cfg
        self.log = log
        self.state = EngineState()
        self.library = VoiceLibrary(cfg["models_dir"], cfg["game"], cfg["lang"], cfg.get("aliases"))
        self.server = TTSServer(cfg["server"]["host"], cfg["server"]["port"], log=log)
        self.client = TTSClient(self.server.base)
        self.player = Player()
        self.capture = GameCapture((cfg["process_name"], "GenshinImpact.exe", "YuanShen.exe"))
        self.reader: DialogueReader | None = None
        self.unmatched: dict[str, int] = {}  # 找不到模型的角色名 → 出現次數，給 UI 顯示
        self._q: queue.Queue[Utterance] = queue.Queue()
        self._play_q: queue.Queue = queue.Queue()
        self._synthesizing = False
        self._stop_done = threading.Event()  # 沒有待送的 /stop 時為 set
        self._stop_done.set()
        self._gen = 0
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._last_line: Utterance | None = None
        self._server_ready = threading.Event()

    # ---------- 控制 ----------
    def start(self) -> None:
        if self.state.running:
            return
        self._stop.clear()
        self.state.running = True
        self.capture.start()
        if self.reader is None:
            self.reader = DialogueReader(self.cfg["regions"])
        self._threads = [
            threading.Thread(target=self._server_thread, name="server", daemon=True),
            threading.Thread(target=self._watch_loop, name="watcher", daemon=True),
            threading.Thread(target=self._speak_loop, name="synth", daemon=True),
            threading.Thread(target=self._play_loop, name="player", daemon=True),
        ]
        for t in self._threads:
            t.start()
        self.log("開始監聽遊戲畫面")

    def stop(self) -> None:
        self._stop.set()
        self.interrupt()
        self.capture.stop()
        for t in self._threads:
            t.join(timeout=3)
        self._threads = []
        self.state.running = False
        self.state.capture = "已停止"
        self.log("已停止監聽")

    def shutdown(self) -> None:
        if self.state.running:
            self.stop()
        self.server.stop()

    def set_paused(self, paused: bool) -> None:
        self.state.paused = paused
        if paused:
            self.interrupt()
        self.log("暫停朗讀" if paused else "繼續朗讀")

    def interrupt(self) -> None:
        """停止正在念的和還沒念的。"""
        self._gen += 1
        for q in (self._q, self._play_q):
            while True:
                try:
                    q.get_nowait()
                except queue.Empty:
                    break
        self.player.stop()
        self.state.speaking = ""
        if self._synthesizing and self._stop_done.is_set():
            # 伺服器還在合成被打斷的句子，請它停下來，新句子才不用排隊。
            # _speak_loop 會等這個請求送完才開始合成下一句，避免 /stop 打到新句子。
            self._stop_done.clear()

            def send():
                try:
                    self.client.stop()
                finally:
                    self._stop_done.set()

            threading.Thread(target=send, daemon=True).start()

    def replay(self) -> None:
        u = self._last_line
        if u:
            self.interrupt()
            self._enqueue(Utterance(u.kind, u.speaker, u.text, u.voice, self._gen, u.note))

    def speak_test(self, text: str, voice_name: str) -> None:
        v = self.library.get(voice_name)
        if v is None:
            self.log(f"沒有 {voice_name} 的模型")
            return
        self.interrupt()
        self._enqueue(Utterance("test", voice_name, text, v, self._gen))

    def reload_voices(self) -> None:
        self.library = VoiceLibrary(self.cfg["models_dir"], self.cfg["game"], self.cfg["lang"], self.cfg.get("aliases"))
        self.log(f"已載入 {len(self.library.names())} 個角色模型")

    # ---------- 角色 → 聲音 ----------
    def resolve_voice(self, name: str, record: bool = False) -> tuple[Voice | None, str]:
        """record=True 時把找不到的角色記進 unmatched（只有真的要念的時候才記）。"""
        voices = self.cfg["voices"]
        if not name:
            v = self.library.get(voices["narrator"]) or self.library.get(voices["fallback"])
            return v, "旁白"
        v = self.library.match(t2s(name))
        if v:
            return v, ""
        if record:
            self.unmatched[name] = self.unmatched.get(name, 0) + 1
        return self.library.get(voices["fallback"]), "後備"

    # ---------- 執行緒 ----------
    def _server_thread(self) -> None:
        if not self.cfg["server"].get("autostart", True) and not self.server.alive():
            self.state.server = "未啟動（請手動執行 tts_server.py）"
            while not self._stop.is_set() and not self.server.alive():
                self._stop.wait(2)
        else:
            self.state.server = "啟動中…"
            if not self.server.start():
                self.state.server = "啟動失敗"
                return
        self.client.loaded = None  # 伺服器可能是新的，強制重載權重
        self.state.server = "就緒"
        self._server_ready.set()
        # 暖機：第一次合成要多花好幾秒，先用後備聲音跑一次
        v = self.library.get(self.cfg["voices"]["fallback"])
        if v:
            try:
                t = time.time()
                self.client.synth("你好。", v)
                self.log(f"TTS 暖機完成（{time.time() - t:.1f} 秒）")
            except Exception as e:
                self.log(f"TTS 暖機失敗：{e}")

    def _watch_loop(self) -> None:
        last_key, count = None, 0
        spoken_key = None
        last_opts, opt_count, spoken_opts = None, 0, None
        out_since = None
        while not self._stop.is_set():
            t0 = time.time()
            try:
                self.state.capture = self.capture.status
                frame = self.capture.latest()
                if frame is None:
                    self.state.in_dialogue = False
                else:
                    st = self.reader.read(frame, with_options=self.cfg.get("read_options", True))
                    self.state.in_dialogue = st.in_dialogue
                    if not st.in_dialogue:
                        # 離開對話超過 1.5 秒才清掉紀錄（切換台詞時分隔線會閃一下）
                        out_since = out_since or time.time()
                        if time.time() - out_since > 1.5:
                            spoken_key = spoken_opts = last_key = last_opts = None
                    else:
                        out_since = None
                        self.state.name, self.state.text, self.state.options = st.name, st.text, st.options
                        key = (st.name, st.text)
                        count = count + 1 if is_stable(last_key, key) else 1
                        last_key = key
                        if st.text and count >= self.cfg["stable_frames"] and not same_line(spoken_key, key):
                            spoken_key = key
                            spoken_opts = None  # 新台詞之後的選項要重新念
                            self._on_line(st.name, st.text)
                        okey = ("", "／".join(st.options))
                        opt_count = opt_count + 1 if is_stable(last_opts, okey) else 1
                        last_opts = okey
                        if opt_count >= self.cfg["stable_frames"]:
                            if st.options and not same_line(spoken_opts, okey):
                                spoken_opts = okey
                                self._on_options(st.options)
                            elif not st.options:
                                spoken_opts = None
            except Exception:
                self.log("畫面辨識錯誤：\n" + traceback.format_exc(limit=3))
                self._stop.wait(1)
            self._stop.wait(max(0.0, self.cfg["poll_interval"] - (time.time() - t0)))

    def _on_line(self, name: str, text: str) -> None:
        v, note = self.resolve_voice(name, record=True)
        who = name or "（旁白）"
        if v is None:
            self.log(f"{who}：{text}  ← 沒有可用的聲音模型（請下載或在設定裡選後備聲音）")
            return
        self.log(f"{who}：{text}  [{v.name}{'，' + note if note else ''}]")
        if self.state.paused:
            return
        self.interrupt()  # 新台詞打斷舊的
        u = Utterance("line", name, text, v, self._gen, note)
        self._last_line = u
        self._enqueue(u)

    def _on_options(self, options: list[str]) -> None:
        self.log("選項：" + " ／ ".join(options))
        v = self.library.get(self.cfg["voices"]["options"])
        if v is None or self.state.paused:
            return
        text = "".join(o if o[-1] in "。！？!?…" else o + "。" for o in options)
        self._enqueue(Utterance("options", "選項", text, v, self._gen))  # 不打斷，排在台詞後面

    def _enqueue(self, u: Utterance) -> None:
        self._q.put(u)

    def _speak_loop(self) -> None:
        """合成：從 _q 拿句子合成好丟到 _play_q。播放上一句時就先合成下一句（例如選項）。"""
        while not self._stop.is_set():
            try:
                u = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            if u.gen != self._gen:
                continue
            if not self._server_ready.is_set():
                self.log("TTS 伺服器還沒好，等待中…")
                while not self._server_ready.wait(1):
                    if self._stop.is_set() or u.gen != self._gen:
                        break
                if u.gen != self._gen or self._stop.is_set():
                    continue
            self._stop_done.wait(3)
            if u.gen != self._gen:
                continue
            try:
                t = time.time()
                self._synthesizing = True
                data, sr = self.client.synth(t2s(u.text), u.voice, self.cfg["speed"], self.cfg["sample_steps"])
            except Exception as e:
                if u.gen == self._gen:
                    self.log(f"語音合成失敗：{e}")
                    self._stop.wait(1)
                continue
            finally:
                self._synthesizing = False
            if u.gen != self._gen:
                continue  # 合成期間玩家已經點到下一句
            self.log(f"  ▶ {u.voice.name} 合成 {time.time() - t:.1f} 秒，長度 {len(data) / sr:.1f} 秒")
            self._play_q.put((u, data, sr))

    def _play_loop(self) -> None:
        while not self._stop.is_set():
            try:
                u, data, sr = self._play_q.get(timeout=0.2)
            except queue.Empty:
                continue
            if u.gen != self._gen:
                continue
            self.state.speaking = f"{u.voice.name}：{u.text}"
            self.player.play(data, sr, self.cfg["volume"])
            while self.player.busy() and u.gen == self._gen and not self._stop.is_set():
                time.sleep(0.05)
            if u.gen == self._gen:
                self.state.speaking = ""
