"""主流程：擷取畫面 → 判斷對話 → OCR → 找角色聲音 → 合成 → 播放。

兩條背景執行緒：
- watcher：每隔 poll_interval 拍一張、OCR。台詞連續 stable_frames 次相同（打字動畫結束）
  且跟上一句不同才送出。
- synth：從佇列拿句子去合成。合成期間如果又有新台詞，舊的結果直接丟掉。
- player：播放。

玩家點到下一段時：正在念的這句剩不到 finish_tail 秒就讓它念完，下一句同時在背景合成，
念完馬上接；剩更多就當作要跳過，立刻打斷。
"""

from __future__ import annotations

import queue
import re
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

_SPEAKABLE = re.compile(r"[0-9A-Za-z㐀-鿿]")  # 有沒有能念的字

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


def same_options(a: list[str] | None, b: list[str], strict: bool = False) -> bool:
    """是不是同一組對話選項。選項背後是亮色場景時 OCR 偶爾會整個漏掉一項，
    所以不比整串字：較少的那組每一項都要在另一組找到相似的（≥80）。
    strict（判斷畫面穩定用）要求數量相同；比對已念過的時候容許差一項。"""
    if a is None:
        return False
    if not a or not b:
        return not a and not b
    if abs(len(a) - len(b)) > (0 if strict else 1):
        return False
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    return all(max(_similar(s, x) for x in big) >= 80 for s in small)


def options_changed(spoken: list[str] | None, cur: list[str]) -> bool:
    """穩定下來的這組選項要不要（重）念。
    - 還沒念過：要。
    - 讀到的都念過了（少讀一兩項）：不用。
    - 念過的都還在、而且多出新的（淡入動畫時先只讀到一部分）：整組重念。
    - 只有一項的字不一樣（OCR 把同一項認成別的字，或背景雜訊每次認成不同字）：不用。"""
    if not spoken:
        return True

    def found(x: str, group: list[str]) -> bool:
        return any(_similar(x, y) >= 80 for y in group)

    new = sum(not found(x, spoken) for x in cur)
    missing = sum(not found(x, cur) for x in spoken)
    if new == 0:
        return False
    if missing == 0:
        return True
    return not (new == 1 and missing == 1 and len(cur) == len(spoken) >= 2)


@dataclass
class Utterance:
    kind: str  # "line" / "options" / "test"
    speaker: str  # 畫面上的角色名（繁體）
    text: str  # 畫面上的台詞（繁體）
    voice: Voice
    gen: int
    note: str = ""
    items: list[str] = field(default_factory=list)  # 選項（kind="options"）
    # 選項和台詞同時合成時，選項要等這句（台詞）排進播放佇列後才能排，念的順序才不會反過來
    after: "Utterance | None" = field(default=None, repr=False, compare=False)
    queued: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)  # 已排進播放或已放棄


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
    black: bool = False  # 黑幕旁白
    speaking: str = ""
    synthesizing: bool = False

    @property
    def phase(self) -> str:
        if not self.running:
            return "未啟動"
        if self.speaking:
            return "朗讀中"
        if self.synthesizing:
            return "合成中"
        if self.paused:
            return "已暫停"
        return "對話中" if self.in_dialogue else "待機中"


class Engine:
    def __init__(self, cfg: dict, log: Callable[[str], None] = print):
        self.cfg = cfg
        self.log = log
        self.state = EngineState()
        self.library = VoiceLibrary(cfg["models_dir"], cfg["game"], cfg["lang"], cfg.get("aliases"))
        self.server = TTSServer(cfg["server"]["host"], cfg["server"]["port"], log=log)
        self.client = TTSClient(self.server.base)
        # 第二個伺服器只念選項：一直載著選項的聲音，選項可以跟台詞同時合成，也不用每次在角色和選項聲音之間切換權重
        self.opt_server = TTSServer(cfg["server"]["host"], cfg["server"].get("options_port", cfg["server"]["port"] + 1),
                                    log=log, log_name="tts_server_options.log", label="選項 TTS 伺服器")
        self.opt_client = TTSClient(self.opt_server.base)
        self._q_opt: queue.Queue[Utterance] = queue.Queue()
        self._opt_synthesizing = False
        self._opt_stop_done = threading.Event()
        self._opt_stop_done.set()
        self._opt_ready = threading.Event()
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
        self._playing: Utterance | None = None
        self._play_lock = threading.Lock()
        self._server_ready = threading.Event()
        self._auto_warned = False
        self._opts_seen: tuple[float, list[str]] = (0.0, [])  # 最後一次讀到選項的時間和內容

    # ---------- 控制 ----------
    def start(self) -> None:
        if self.state.running:
            return
        self._stop.clear()
        self.state.running = True
        self.capture.start()
        if self.reader is None:
            self.reader = DialogueReader(self.cfg["regions"], engine=self.cfg.get("ocr_engine", "rapid"))
            self.reader.is_known = lambda n: self.library.match(t2s(n)) is not None
        self._threads = [
            threading.Thread(target=self._server_thread, name="server", daemon=True),
            threading.Thread(target=self._watch_loop, name="watcher", daemon=True),
            threading.Thread(target=self._speak_loop, name="synth", daemon=True),
            threading.Thread(target=self._play_loop, name="player", daemon=True),
        ]
        if self.cfg["server"].get("parallel_options", True):
            self._threads += [threading.Thread(target=self._opt_server_thread, name="opt-server", daemon=True),
                              threading.Thread(target=self._opt_speak_loop, name="opt-synth", daemon=True)]
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
        self.opt_server.stop()
        self._opt_ready.clear()

    def set_paused(self, paused: bool) -> None:
        self.state.paused = paused
        if paused:
            self.interrupt()
        self.log("暫停朗讀" if paused else "繼續朗讀")

    def interrupt(self, keep_playing: bool = False) -> None:
        """停止正在念的和還沒念的。keep_playing：正在念的那句念完，只取消後面排隊的。"""
        with self._play_lock:
            new = self._gen + 1
            kept = self._playing if keep_playing and self.player.busy() else None
            if kept:
                kept.gen = new  # 先改它的 gen 再改全域的，播放執行緒才不會在中間把它當成已取消
            self._gen = new
            for q in (self._q, self._q_opt, self._play_q):
                while True:
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        break
            if not kept:
                self.player.stop()
                self.state.speaking = ""
        # 伺服器還在合成被打斷的句子，請它停下來，新句子才不用排隊。
        # 合成迴圈會等這個請求送完才開始合成下一句，避免 /stop 打到新句子。
        for busy, done, client in ((self._synthesizing, self._stop_done, self.client),
                                   (self._opt_synthesizing, self._opt_stop_done, self.opt_client)):
            if busy and done.is_set():
                done.clear()

                def send(done=done, client=client):
                    try:
                        client.stop()
                    finally:
                        done.set()

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

    def reload_voices(self, quiet: bool = False) -> None:
        self.library = VoiceLibrary(self.cfg["models_dir"], self.cfg["game"], self.cfg["lang"], self.cfg.get("aliases"))
        if not quiet:
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
        # 暖機：剛開的伺服器第一次合成要多花好幾秒，先用後備聲音跑一次。
        # 已經有台詞在排隊就不用了，直接合成那句（同時暖機會互搶 GPU，反而更慢）。
        # 伺服器本來就在跑（不是這次開的）已經暖過了；再暖機只會多載一次後備聲音（模型在 HDD 上要十幾秒），
        # 第一句台詞還得排在它後面。
        v = self.library.get(self.cfg["voices"]["fallback"])
        if v and self._q.empty() and self.server.proc is not None:
            try:
                t = time.time()
                self.client.synth("你好。", v)
                self.log(f"TTS 暖機完成（{time.time() - t:.1f} 秒）")
            except Exception as e:
                self.log(f"TTS 暖機失敗：{e}")

    def _opt_server_thread(self) -> None:
        """主伺服器好了以後再開選項專用的伺服器（同時啟動會互搶 GPU 和記憶體），先載好選項的聲音。
        沒開成功就沿用主伺服器（選項排在台詞後面合成）。"""
        while not self._server_ready.wait(1):
            if self._stop.is_set():
                return
        v = self.library.get(self.cfg["voices"]["options"])
        if v is None or self._stop.is_set():
            return
        if not self.opt_server.start():
            self.log("選項 TTS 伺服器沒有啟動，選項改用主伺服器合成")
            return
        self.opt_client.loaded = None
        try:
            t = time.time()
            self.opt_client.synth("你好。", v)
            self.log(f"選項 TTS 伺服器就緒，選項會跟台詞同時合成（暖機 {time.time() - t:.1f} 秒）")
            self._opt_ready.set()
        except Exception as e:
            self.log(f"選項 TTS 伺服器暖機失敗，選項改用主伺服器合成：{e}")

    def _watch_loop(self) -> None:
        last_key, count = None, 0
        spoken_key = None
        last_opts, opt_count, spoken_opts = None, 0, None
        out_since = opts_gone_since = None
        opt_since = 0.0
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
                        self.state.black = st.black
                        key = (st.name, st.text)
                        count = count + 1 if is_stable(last_key, key) else 1
                        last_key = key
                        if st.text and count >= self.cfg["stable_frames"] and not same_line(spoken_key, key):
                            spoken_key = key
                            spoken_opts = None  # 新台詞之後的選項要重新念
                            self._on_line(st.name, st.text)
                        okey = list(st.options)
                        now = time.time()
                        if okey:
                            opts_gone_since = None
                            self._opts_seen = (now, okey)
                            # 穩定：同一組選項（容許偶爾漏讀一項）連續幾幀、而且維持 0.5 秒才念
                            # （選項有淡入動畫，太早讀會漏掉還沒出現的）；念這段時間讀到最完整的那組
                            if same_options(last_opts, okey):
                                opt_count += 1
                                if (len(okey), sum(map(len, okey))) > (len(last_opts), sum(map(len, last_opts))):
                                    last_opts = okey
                            else:
                                opt_count, opt_since, last_opts = 1, now, okey
                            best = last_opts
                            stable = opt_count >= self.cfg["stable_frames"] and now - opt_since >= 0.5
                            # 念過的那組少了幾項（例如動畫還沒跑完），現在讀到更多：整組重念
                            if stable and options_changed(spoken_opts, best):
                                spoken_opts = best
                                self._on_options(best)
                        else:
                            # 選項泡泡有呼吸動畫，OCR 每隔幾幀就會整個讀不到：這種幀不算進穩定判斷；
                            # 連續消失 1.5 秒才算選項真的不見了，否則同一組選項會一直重念
                            opts_gone_since = opts_gone_since or now
                            if now - opts_gone_since > 1.5:
                                spoken_opts = last_opts = None
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
        # 玩家點到下一段了。快念完的那句讓它念完（下一句同時合成），剩很多就打斷。
        tail = float(self.cfg.get("finish_tail", 0) or 0)
        self.interrupt(keep_playing=tail > 0 and self.player.remaining() <= tail)
        u = Utterance("line", name, text, v, self._gen, note)
        self._last_line = u
        self._enqueue(u)

    def _on_options(self, options: list[str]) -> None:
        self.log("選項：" + " ／ ".join(options))
        v = self.library.get(self.cfg["voices"]["options"])
        if v is None or self.state.paused:
            return
        text = "".join(o if o[-1] in "。！？!?…" else o + "。" for o in options)
        last = self._last_line if self._last_line and self._last_line.gen == self._gen else None
        u = Utterance("options", "選項", text, v, self._gen, items=list(options), after=last)  # 不打斷，排在台詞後面
        if self._opt_ready.is_set():
            self._q_opt.put(u)  # 選項專用伺服器：跟台詞同時合成
        else:
            self._enqueue(u)

    def _enqueue(self, u: Utterance) -> None:
        self._q.put(u)

    def _speak_loop(self) -> None:
        """合成台詞：從 _q 拿句子合成好丟到 _play_q。播放上一句時就先合成下一句。"""
        self._synth_loop(main=True)

    def _opt_speak_loop(self) -> None:
        """合成選項（選項專用伺服器）：跟台詞同時合成，等台詞排進播放佇列後再排，念的順序不變。"""
        self._synth_loop(main=False)

    def _set_synth(self, main: bool, busy: bool) -> None:
        if main:
            self._synthesizing = busy
        else:
            self._opt_synthesizing = busy
        self.state.synthesizing = self._synthesizing or self._opt_synthesizing

    def _synth_loop(self, main: bool) -> None:
        q = self._q if main else self._q_opt
        ready = self._server_ready if main else self._opt_ready
        stop_done = self._stop_done if main else self._opt_stop_done
        while not self._stop.is_set():
            try:
                u = q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._synth_one(u, main, ready, stop_done)
            finally:
                u.queued.set()  # 排進播放了、或放棄了：等它的選項可以排了

    def _synth_one(self, u: Utterance, main: bool, ready: threading.Event, stop_done: threading.Event) -> None:
        if u.gen != self._gen:
            return
        if not ready.is_set():
            self.log("TTS 伺服器還沒好，等待中…")
            while not ready.wait(1):
                if self._stop.is_set() or u.gen != self._gen:
                    return
        stop_done.wait(3)
        if u.gen != self._gen:
            return
        if not _SPEAKABLE.search(u.text):
            # 「……」這種沒有字可念的台詞：不合成，停頓 1 秒（之後照樣自動過劇情）
            import numpy as np

            self.log("  ▶ 沒有字可念，停頓 1 秒")
            data, sr = np.zeros(16000, np.float32), 16000
        else:
            client = self.client if main else self.opt_client
            try:
                t = time.time()
                self._set_synth(main, True)
                data, sr = client.synth(t2s(u.text), u.voice, self.cfg["speed"], self.cfg["sample_steps"])
            except Exception as e:
                if not main and not self.opt_server.alive():
                    # 選項伺服器掛了（或被別的程式關掉）：之後的選項都改用主伺服器，這組也丟回主佇列
                    self._opt_ready.clear()
                    self.log("選項 TTS 伺服器斷線，選項改用主伺服器合成")
                    if u.gen == self._gen:
                        self._q.put(u)
                    return
                if u.gen == self._gen:
                    self.log(f"語音合成失敗：{e}")
                    self._stop.wait(1)
                return
            finally:
                self._set_synth(main, False)
            if u.gen != self._gen:
                return  # 合成期間玩家已經點到下一句
            self.log(f"  ▶ {u.voice.name} 合成 {time.time() - t:.1f} 秒，長度 {len(data) / sr:.1f} 秒")
        # 選項先合成好了：等台詞排進播放佇列再排，才會先念台詞
        while u.after is not None and not u.after.queued.wait(0.1):
            if self._stop.is_set() or u.gen != self._gen:
                return
        if u.gen == self._gen:
            self._play_q.put((u, data, sr))

    def _play_loop(self) -> None:
        while not self._stop.is_set():
            try:
                u, data, sr = self._play_q.get(timeout=0.2)
            except queue.Empty:
                continue
            with self._play_lock:
                if u.gen != self._gen:
                    continue
                self._playing = u
                self.state.speaking = f"{u.voice.name}：{u.text}"
                self.player.play(data, sr, self.cfg["volume"])
            # u.gen 可能被 interrupt(keep_playing) 改成新的，所以用 >= 判斷還要不要繼續念
            while self.player.busy() and u.gen >= self._gen and not self._stop.is_set():
                time.sleep(0.05)
            if u.gen == self._gen and not self._stop.is_set() and u.kind in ("line", "options"):
                self._schedule_advance(u)  # 自然念完（沒被打斷）
            with self._play_lock:
                if self._playing is u:
                    self._playing = None
                    if u.gen == self._gen:
                        self.state.speaking = ""

    # ---------- 自動過劇情 ----------
    def _schedule_advance(self, u: Utterance) -> None:
        ap = self.cfg.get("auto_play", {})
        if ap.get("enabled"):
            threading.Thread(target=self._advance, args=(u, self._gen), daemon=True).start()

    def _advance(self, u: Utterance, gen: int) -> None:
        """念完後確認畫面還停在剛念的那句（或那組選項），而且沒有別的在排隊，才點下一段。
        玩家自己先點過去了、或還有選項要念，就什麼都不做。"""
        from . import gameinput as gi

        ap = self.cfg.get("auto_play", {})
        if self._stop.wait(float(ap.get("delay", 0.6))):
            return
        s = self.state
        if (gen != self._gen or not ap.get("enabled") or s.paused or not s.in_dialogue
                or not self._q.empty() or not self._q_opt.empty() or not self._play_q.empty()
                or self._synthesizing or self._opt_synthesizing or self.player.busy()):
            return
        # 選項泡泡有呼吸動畫，OCR 每隔幾幀會整個讀不到：看最近 1 秒內讀到的選項，不只看這一幀
        t_seen, recent = self._opts_seen
        options = s.options or (recent if time.time() - t_seen <= 1.0 else [])
        if u.kind == "line":
            if not s.text or _similar(s.text, u.text) < 85:
                return  # 畫面已經換句了
            action = "options" if options else "click"
            if action == "options" and self.cfg.get("read_options", True):
                return  # 選項還沒念，等念完選項再按
        else:
            if not same_options(u.items, options):
                return
            action = "options"
        hwnd = self.capture.hwnd
        if not hwnd:
            self.log("自動過劇情：找不到原神視窗，沒有動作")
            return
        # method="window"（預設）：直接送給原神視窗，不動滑鼠、遊戲在背景也可以
        # method="screen"：模擬真的鍵盤滑鼠（送到前景視窗），所以只在原神是前景時才送
        to_window = ap.get("method", "window") != "screen"
        if not to_window and not gi.is_foreground(hwnd):
            self.log("自動過劇情：原神不在前景，沒有動作（設定裡改成「送到原神視窗」就不用在前景）")
            return
        before = s.text
        if action == "click":
            # 黑幕旁白畫面寫的是「點擊後繼續」：一律點擊（點畫面中間偏下，「點擊後繼續」附近）
            line_action = "click" if s.black else ap.get("line_action", "space")
            what = "點擊畫面" if s.black else ("點擊對話框" if line_action == "click" else "按空白鍵")
        else:
            line_action = None
            what = f"按 {ap.get('option_key', 'F')} 選擇選項"
        try:
            if line_action == "click":
                x, y = ap.get("click", [960, 950])
                gi.post_click(hwnd, x, y) if to_window else gi.click_at(hwnd, x, y)
            else:
                key = "SPACE" if line_action == "space" else ap.get("option_key", "F")
                gi.post_key(hwnd, key) if to_window else gi.press_key(key)
        except PermissionError as e:
            self.log(f"自動過劇情：{e.args[1]}，請用系統管理員身分開啟 hoyoTTS")
            return
        self.log(f"自動過劇情：{what}")
        # 送出 2 秒畫面都沒變：權限不夠（模擬輸入被 UIPI 默默擋掉），或遊戲不吃送到視窗的輸入
        if self._stop.wait(2.0) or self._auto_warned:
            return
        if gen == self._gen and self.state.in_dialogue and self.state.text == before:
            self._auto_warned = True
            if not gi.is_admin():
                self.log("自動過劇情好像沒有作用：原神以系統管理員身分執行，請用系統管理員身分開啟 hoyoTTS")
            elif to_window:
                self.log("自動過劇情好像沒有作用：可以到「設定 → 自動過劇情」把送出方式改成「模擬鍵盤滑鼠」試試")
