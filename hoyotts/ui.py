"""hoyoTTS 圖形介面（tkinter）。"""

from __future__ import annotations

import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import voices as V
from .config import load_config, save_config
from .engine import Engine, t2s
from .hotkeys import GlobalHotkeys

FONT = ("Microsoft JhengHei UI", 10)
FONT_BIG = ("Microsoft JhengHei UI", 13)
FONT_NAME = ("Microsoft JhengHei UI", 12, "bold")

OK, WARN, BAD, OFF = "#2e9d4f", "#d9a400", "#cc3d3d", "#9a9a9a"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = load_config()
        self.logq: queue.Queue[str] = queue.Queue()
        self.engine = Engine(self.cfg, log=self.log)
        self.hotkeys = GlobalHotkeys(log=self.log)
        self.dl_stop = threading.Event()
        self.dl_thread: threading.Thread | None = None
        self.dl_progress: dict[str, tuple[int, int]] = {}
        self.remote_count = 0
        self._preview_win: tk.Toplevel | None = None

        root.title("hoyoTTS")
        root.geometry("980x760")
        root.minsize(820, 620)
        root.option_add("*Font", FONT)
        style = ttk.Style(root)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("Big.TButton", font=FONT_BIG, padding=(14, 6))
        style.configure("TLabelframe.Label", font=("Microsoft JhengHei UI", 10, "bold"))

        self._build_status()
        self._build_controls()
        self._build_current()
        self._build_tabs()

        self._bind_hotkeys()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(200, self._tick)
        self.log(f"模型資料夾：{self.cfg['models_dir']}（已下載 {len(self.engine.library.names())} 個角色）")
        if self.cfg.get("auto_start", True):
            root.after(300, self.toggle_run)

    # ---------- 版面 ----------
    def _light(self, parent, text):
        f = ttk.Frame(parent)
        c = tk.Canvas(f, width=14, height=14, highlightthickness=0)
        dot = c.create_oval(2, 2, 12, 12, fill=OFF, outline="")
        c.pack(side="left", padx=(0, 4))
        ttk.Label(f, text=text).pack(side="left")
        val = ttk.Label(f, text="—", foreground="#555")
        val.pack(side="left", padx=(4, 0))
        f.pack(side="left", padx=(0, 22))
        return c, dot, val

    def _build_status(self):
        bar = ttk.Frame(self.root, padding=(12, 10, 12, 4))
        bar.pack(fill="x")
        self.l_cap = self._light(bar, "遊戲擷取：")
        self.l_srv = self._light(bar, "TTS 伺服器：")
        self.l_mod = self._light(bar, "角色模型：")

    def _build_controls(self):
        bar = ttk.Frame(self.root, padding=(12, 4))
        bar.pack(fill="x")
        hk = self.cfg["hotkeys"]
        self.b_run = ttk.Button(bar, text="▶ 開始", style="Big.TButton", command=self.toggle_run)
        self.b_run.pack(side="left")
        self.b_pause = ttk.Button(bar, text=f"⏸ 暫停朗讀（{hk['pause']}）", command=self.toggle_pause)
        self.b_pause.pack(side="left", padx=(10, 0))
        ttk.Button(bar, text=f"⏹ 停止這句（{hk['stop']}）", command=self.engine.interrupt).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text=f"↻ 重念（{hk['replay']}）", command=self.engine.replay).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="擷取預覽", command=self.show_preview).pack(side="right")

    def _build_current(self):
        box = ttk.Labelframe(self.root, text="目前對話", padding=(12, 6))
        box.pack(fill="x", padx=12, pady=(6, 4))
        top = ttk.Frame(box)
        top.pack(fill="x")
        self.v_name = ttk.Label(top, text="—", font=FONT_NAME, foreground="#b8860b")
        self.v_name.pack(side="left")
        self.v_voice = ttk.Label(top, text="", foreground="#555")
        self.v_voice.pack(side="left", padx=(10, 0))
        self.v_speaking = ttk.Label(top, text="", foreground=OK)
        self.v_speaking.pack(side="right")
        self.v_text = ttk.Label(box, text="", font=FONT_BIG, wraplength=900, justify="left")
        self.v_text.pack(fill="x", pady=(4, 0))
        self.v_opts = ttk.Label(box, text="", foreground="#2b6cb0", wraplength=900, justify="left")
        self.v_opts.pack(fill="x", pady=(2, 0))

    def _build_tabs(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        self.nb = nb
        self._tab_log(nb)
        self._tab_settings(nb)
        self._tab_alias(nb)
        self._tab_download(nb)
        self._tab_test(nb)

    def _tab_log(self, nb):
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="紀錄")
        self.t_log = ScrolledText(f, height=12, font=("Microsoft JhengHei UI", 10), state="disabled", wrap="word")
        self.t_log.pack(fill="both", expand=True)

    def _voice_combo(self, parent, value):
        cb = ttk.Combobox(parent, values=self.engine.library.names(), width=18)
        cb.set(value)
        return cb

    def _tab_settings(self, nb):
        f = ttk.Frame(nb, padding=12)
        nb.add(f, text="設定")
        v = self.cfg["voices"]
        g = ttk.Labelframe(f, text="聲音", padding=10)
        g.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        rows = [("找不到模型的角色", "fallback"), ("旅行者的對話選項", "options"), ("旁白（沒有角色名）", "narrator")]
        self.voice_combos = {}
        for i, (label, key) in enumerate(rows):
            ttk.Label(g, text=label).grid(row=i, column=0, sticky="w", pady=3)
            cb = self._voice_combo(g, v[key])
            cb.grid(row=i, column=1, sticky="w", padx=(8, 0))
            self.voice_combos[key] = cb
        self.var_opts = tk.BooleanVar(value=self.cfg.get("read_options", True))
        ttk.Checkbutton(g, text="念對話選項", variable=self.var_opts).grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.var_auto = tk.BooleanVar(value=self.cfg.get("auto_start", True))
        ttk.Checkbutton(g, text="開啟程式時自動開始", variable=self.var_auto).grid(row=4, column=0, columnspan=2, sticky="w")

        p = ttk.Labelframe(f, text="播放", padding=10)
        p.grid(row=0, column=1, sticky="nsew")
        self.var_vol = tk.DoubleVar(value=self.cfg["volume"])
        self.var_speed = tk.DoubleVar(value=self.cfg["speed"])
        for i, (label, var, lo, hi) in enumerate([("音量", self.var_vol, 0, 1.5), ("語速", self.var_speed, 0.6, 1.6)]):
            ttk.Label(p, text=label).grid(row=i, column=0, sticky="w", pady=3)
            ttk.Scale(p, from_=lo, to=hi, variable=var, length=200,
                      command=lambda _=None: self._apply_live()).grid(row=i, column=1, padx=8)
            lab = ttk.Label(p, width=5)
            lab.grid(row=i, column=2)
            var.trace_add("write", lambda *_, l=lab, vv=var: l.config(text=f"{vv.get():.2f}"))
            var.set(var.get())
        hk = self.cfg["hotkeys"]
        self.hk_entries = {}
        for i, (label, key) in enumerate([("停止這句", "stop"), ("暫停／繼續", "pause"), ("重念", "replay")], start=2):
            ttk.Label(p, text=f"快捷鍵：{label}").grid(row=i, column=0, sticky="w", pady=3)
            e = ttk.Entry(p, width=12)
            e.insert(0, hk[key])
            e.grid(row=i, column=1, sticky="w", padx=8)
            self.hk_entries[key] = e

        m = ttk.Labelframe(f, text="模型資料夾", padding=10)
        m.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.e_dir = ttk.Entry(m, width=60)
        self.e_dir.insert(0, self.cfg["models_dir"])
        self.e_dir.pack(side="left", fill="x", expand=True)
        ttk.Button(m, text="瀏覽…", command=self._browse_dir).pack(side="left", padx=6)
        ttk.Button(m, text="重新載入模型", command=lambda: self._reload_voices(True)).pack(side="left")

        ttk.Button(f, text="儲存設定", style="Big.TButton", command=self.save_settings).grid(
            row=2, column=0, columnspan=2, sticky="e", pady=(12, 0))
        f.columnconfigure(0, weight=1)
        f.columnconfigure(1, weight=1)

    def _tab_alias(self, nb):
        f = ttk.Frame(nb, padding=12)
        nb.add(f, text="角色對應")
        ttk.Label(f, text="找不到模型的角色會用後備聲音。在這裡把角色名指定給某個模型，例如把你的旅行者名字對到「空」。",
                  foreground="#555", wraplength=880).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        left = ttk.Labelframe(f, text="最近沒對應到的角色（雙擊帶入）", padding=6)
        left.grid(row=1, column=0, sticky="nsew")
        self.lb_unmatched = tk.Listbox(left, height=12, activestyle="none")
        self.lb_unmatched.pack(fill="both", expand=True)
        self.lb_unmatched.bind("<Double-1>", self._pick_unmatched)

        mid = ttk.Frame(f, padding=(12, 0))
        mid.grid(row=1, column=1, sticky="n")
        ttk.Label(mid, text="遊戲裡的角色名").pack(anchor="w")
        self.e_alias = ttk.Entry(mid, width=18)
        self.e_alias.pack(anchor="w", pady=(0, 8))
        ttk.Label(mid, text="使用模型").pack(anchor="w")
        self.cb_alias = self._voice_combo(mid, "")
        self.cb_alias.pack(anchor="w", pady=(0, 8))
        ttk.Button(mid, text="新增／更新 →", command=self._add_alias).pack(anchor="w", fill="x")
        ttk.Button(mid, text="← 刪除選取", command=self._del_alias).pack(anchor="w", fill="x", pady=(6, 0))

        right = ttk.Labelframe(f, text="已設定的對應", padding=6)
        right.grid(row=1, column=2, sticky="nsew")
        self.lb_alias = tk.Listbox(right, height=12, activestyle="none")
        self.lb_alias.pack(fill="both", expand=True)
        f.columnconfigure(0, weight=1)
        f.columnconfigure(2, weight=1)
        f.rowconfigure(1, weight=1)
        self._refresh_alias()

    def _tab_download(self, nb):
        f = ttk.Frame(nb, padding=12)
        nb.add(f, text="模型下載")
        ttk.Label(f, text="來源：ModelScope aihobbyist/GPT-SoVITS_Model_Collection（原神／中文，CC-BY-NC，禁止商用與二次散布）。"
                          "每個角色約 200MB，全部約 52GB。已下載的會跳過，中斷後可以續傳。",
                  foreground="#555", wraplength=880).pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=8)
        self.b_dl_all = ttk.Button(row, text="下載全部", command=self.download_all)
        self.b_dl_all.pack(side="left")
        ttk.Button(row, text="停止下載", command=self.dl_stop.set).pack(side="left", padx=6)
        ttk.Label(row, text="或只下載：").pack(side="left", padx=(20, 4))
        self.e_dl_one = ttk.Entry(row, width=14)
        self.e_dl_one.pack(side="left")
        ttk.Button(row, text="下載", command=self.download_one).pack(side="left", padx=4)
        self.pb = ttk.Progressbar(f, mode="determinate")
        self.pb.pack(fill="x")
        self.l_dl = ttk.Label(f, text="", foreground="#555")
        self.l_dl.pack(anchor="w", pady=(4, 0))

    def _tab_test(self, nb):
        f = ttk.Frame(nb, padding=12)
        nb.add(f, text="試聽")
        ttk.Label(f, text="輸入文字（繁簡都可以），選一個角色念念看：").pack(anchor="w")
        self.t_test = tk.Text(f, height=4, wrap="word", font=FONT_BIG)
        self.t_test.insert("1.0", "旅行者，我們快走吧！前面好像有寶箱哦。")
        self.t_test.pack(fill="x", pady=6)
        row = ttk.Frame(f)
        row.pack(fill="x")
        self.cb_test = self._voice_combo(row, "派蒙" if self.engine.library.get("派蒙") else self.cfg["voices"]["fallback"])
        self.cb_test.pack(side="left")
        ttk.Button(row, text="念出來", command=self._test_speak).pack(side="left", padx=8)
        ttk.Label(f, text="需要先按「開始」讓 TTS 伺服器啟動。", foreground="#555").pack(anchor="w", pady=(8, 0))

    # ---------- 動作 ----------
    def log(self, msg: str) -> None:  # 任何執行緒都能呼叫
        self.logq.put(f"{time.strftime('%H:%M:%S')}  {msg}")

    def toggle_run(self):
        if self.engine.state.running:
            threading.Thread(target=self.engine.stop, daemon=True).start()
            self.b_run.config(text="▶ 開始")
        else:
            self.engine.start()
            self.b_run.config(text="■ 停止")

    def toggle_pause(self):
        self.engine.set_paused(not self.engine.state.paused)

    def _bind_hotkeys(self):
        hk = self.cfg["hotkeys"]
        ui = lambda fn: (lambda: self.root.after(0, fn))  # noqa: E731  回到 UI 執行緒
        self.hotkeys.start({hk["stop"]: ui(self.engine.interrupt), hk["pause"]: ui(self.toggle_pause),
                            hk["replay"]: ui(self.engine.replay)})

    def _apply_live(self):
        self.cfg["volume"] = round(self.var_vol.get(), 2)
        self.cfg["speed"] = round(self.var_speed.get(), 2)

    def save_settings(self):
        for key, cb in self.voice_combos.items():
            name = cb.get().strip()
            if name and not self.engine.library.get(name):
                if not messagebox.askyesno("hoyoTTS", f"「{name}」的模型還沒下載，仍要儲存嗎？"):
                    return
            self.cfg["voices"][key] = name
        self.cfg["read_options"] = self.var_opts.get()
        self.cfg["auto_start"] = self.var_auto.get()
        self._apply_live()
        old_hk = dict(self.cfg["hotkeys"])
        for key, e in self.hk_entries.items():
            self.cfg["hotkeys"][key] = e.get().strip()
        new_dir = self.e_dir.get().strip()
        dir_changed = new_dir != self.cfg["models_dir"]
        self.cfg["models_dir"] = new_dir
        save_config(self.cfg)
        if dir_changed:
            self._reload_voices()
        if old_hk != self.cfg["hotkeys"]:
            self._bind_hotkeys()
            self.log("快捷鍵已更新（按鈕上的文字要重開程式才會更新）")
        self.log("設定已儲存")

    def _browse_dir(self):
        d = filedialog.askdirectory(initialdir=self.e_dir.get() or "D:\\")
        if d:
            self.e_dir.delete(0, "end")
            self.e_dir.insert(0, os.path.normpath(d))

    def _reload_voices(self, from_entry: bool = False):
        if from_entry:  # 「重新載入模型」按鈕：套用輸入框裡的資料夾
            self.cfg["models_dir"] = self.e_dir.get().strip()
        self.engine.reload_voices()
        names = self.engine.library.names()
        for cb in [*self.voice_combos.values(), self.cb_alias, self.cb_test]:
            cb.config(values=names)

    def _refresh_alias(self):
        self.lb_alias.delete(0, "end")
        for k, v in sorted(self.cfg["aliases"].items()):
            self.lb_alias.insert("end", f"{k} → {v}")

    def _pick_unmatched(self, _):
        sel = self.lb_unmatched.curselection()
        if sel:
            name = self.lb_unmatched.get(sel[0]).split("（")[0]
            self.e_alias.delete(0, "end")
            self.e_alias.insert(0, name)

    def _add_alias(self):
        name, model = self.e_alias.get().strip(), self.cb_alias.get().strip()
        if not name or not model:
            return
        if not self.engine.library.get(model):
            messagebox.showwarning("hoyoTTS", f"沒有「{model}」這個模型")
            return
        self.cfg["aliases"][t2s(name)] = model  # 比對時角色名會先轉簡體
        self.engine.library.aliases = {V.normalize(k): v for k, v in self.cfg["aliases"].items()}
        self.engine.unmatched.pop(name, None)
        save_config(self.cfg)
        self._refresh_alias()
        self.log(f"角色對應：{name} → {model}")

    def _del_alias(self):
        sel = self.lb_alias.curselection()
        if not sel:
            return
        key = self.lb_alias.get(sel[0]).split(" → ")[0]
        self.cfg["aliases"].pop(key, None)
        self.engine.library.aliases = {V.normalize(k): v for k, v in self.cfg["aliases"].items()}
        save_config(self.cfg)
        self._refresh_alias()

    def _test_speak(self):
        text = self.t_test.get("1.0", "end").strip()
        if text:
            self.engine.speak_test(text, self.cb_test.get().strip())

    def download_all(self, names: list[str] | None = None):
        if self.dl_thread and self.dl_thread.is_alive():
            self.log("已經在下載中")
            return
        self.dl_stop.clear()
        models_dir = self.cfg["models_dir"]

        def run():
            try:
                remote = V.list_remote(self.cfg["game"], self.cfg["lang"])
            except Exception as e:
                self.log(f"取得模型清單失敗：{e}")
                return
            self.remote_count = len(remote)
            if names:
                remote = [m for m in remote if m.name in names]
                if not remote:
                    self.log(f"找不到模型：{'、'.join(names)}")
                    return
            dest = V.lang_dir(models_dir, self.cfg["game"], self.cfg["lang"])
            todo = [m for m in remote if not V.find_local(dest, m.name)]
            self.log(f"要下載 {len(todo)} 個角色（{sum(m.size for m in todo) / 1e9:.1f} GB）")
            self.dl_total = len(todo)
            self.dl_done = 0

            def logdone(s):
                if s.startswith("完成"):
                    self.dl_done += 1
                    self.dl_progress.pop(s[3:], None)
                self.log("下載" + s)

            failed = V.download_many(todo, models_dir, workers=3, log=logdone, stop=self.dl_stop,
                                     progress=lambda n, a, b: self.dl_progress.__setitem__(n, (a, b)))
            self.dl_progress.clear()
            self.log("下載停止" if self.dl_stop.is_set() else ("下載失敗：" + "、".join(failed) if failed else "下載完成"))
            self.root.after(0, self._reload_voices)

        self.dl_total, self.dl_done = 0, 0
        self.dl_thread = threading.Thread(target=run, daemon=True)
        self.dl_thread.start()

    def download_one(self):
        name = t2s(self.e_dl_one.get().strip())
        if name:
            self.download_all([name])

    def show_preview(self):
        frame = self.engine.capture.latest() if self.engine.state.running else None
        if frame is None:
            from .capture import GameCapture

            cap = GameCapture()
            cap.start()
            for _ in range(20):
                frame = cap.latest()
                if frame is not None:
                    break
                time.sleep(0.15)
            cap.stop()
        if frame is None:
            messagebox.showinfo("hoyoTTS", f"拍不到遊戲畫面（{self.engine.capture.status}）。遊戲最小化時拍不到。")
            return
        from PIL import ImageTk

        from .dialogue import DialogueReader

        reader = self.engine.reader or DialogueReader(self.cfg["regions"])
        self.engine.reader = reader
        st = reader.read(frame)
        img = reader.debug_image(frame)
        img.thumbnail((960, 540))
        if self._preview_win and self._preview_win.winfo_exists():
            self._preview_win.destroy()
        w = tk.Toplevel(self.root)
        w.title("擷取預覽")
        self._preview_win = w
        photo = ImageTk.PhotoImage(img)
        lab = ttk.Label(w, image=photo)
        lab.image = photo
        lab.pack()
        info = (f"在對話中：{'是' if st.in_dialogue else '否'}（綠線＝偵測到對話分隔線）\n"
                f"角色：{st.name or '—'}\n台詞：{st.text or '—'}\n選項：{' ／ '.join(st.options) or '—'}")
        ttk.Label(w, text=info, padding=8, wraplength=940, justify="left").pack(anchor="w")

    def on_close(self):
        self.dl_stop.set()
        self.hotkeys.stop()
        self.root.withdraw()
        try:
            self.engine.shutdown()
        finally:
            self.root.destroy()

    # ---------- 定時更新 ----------
    def _set_light(self, light, color, text):
        c, dot, val = light
        c.itemconfig(dot, fill=color)
        val.config(text=text)

    def _tick(self):
        try:
            lines = []
            while True:
                lines.append(self.logq.get_nowait())
        except queue.Empty:
            pass
        if lines:
            self.t_log.config(state="normal")
            self.t_log.insert("end", "\n".join(lines) + "\n")
            n = int(self.t_log.index("end-1c").split(".")[0])
            if n > 2000:
                self.t_log.delete("1.0", f"{n - 2000}.0")
            self.t_log.see("end")
            self.t_log.config(state="disabled")

        s = self.engine.state
        cap = s.capture if s.running else "未啟動"
        self._set_light(self.l_cap, OK if "擷取中" in cap else (WARN if s.running else OFF), cap)
        srv = s.server
        self._set_light(self.l_srv, OK if srv == "就緒" else (BAD if "失敗" in srv else (WARN if s.running else OFF)), srv)
        n = len(self.engine.library.names())
        total = self.remote_count or 263
        dl = ""
        if self.dl_thread and self.dl_thread.is_alive():
            dl = f"（下載中 {self.dl_done}/{self.dl_total}）"
        self._set_light(self.l_mod, OK if n else BAD, f"{n}/{total} {dl}")
        self.b_pause.config(text=("▶ 繼續朗讀" if s.paused else "⏸ 暫停朗讀") + f"（{self.cfg['hotkeys']['pause']}）")

        if s.running and s.in_dialogue:
            self.v_name.config(text=s.name or "（旁白）")
            v, note = self.engine.resolve_voice(s.name) if s.text else (None, "")
            self.v_voice.config(text=f"→ {v.name}{'（' + note + '）' if note else ''}" if v else "")
            self.v_text.config(text=s.text)
            self.v_opts.config(text=("選項：" + " ／ ".join(s.options)) if s.options else "")
        elif s.running:
            self.v_name.config(text="—")
            self.v_voice.config(text="（沒有在對話中）")
            self.v_text.config(text="")
            self.v_opts.config(text="")
        self.v_speaking.config(text=("🔊 " + s.speaking[:40]) if s.speaking else "")

        if self.dl_progress:
            got = sum(a for a, _ in self.dl_progress.values())
            tot = sum(b for _, b in self.dl_progress.values())
            self.pb.config(maximum=max(tot, 1), value=got)
            self.l_dl.config(text=f"已完成 {self.dl_done}/{self.dl_total}，進行中：" + "、".join(self.dl_progress))
        elif not (self.dl_thread and self.dl_thread.is_alive()):
            self.l_dl.config(text=f"本機已有 {n} 個角色模型")
        # 每 10 秒看一下模型資料夾，有新下載完的就重新載入（例如另外用指令列下載）
        self._scan_tick = getattr(self, "_scan_tick", 0) + 1
        if self._scan_tick % 50 == 0:
            try:
                d = self.engine.library.dir
                on_disk = sum(1 for x in os.listdir(d) if not x.startswith(".")) if os.path.isdir(d) else 0
            except OSError:
                on_disk = n
            if on_disk != n:
                self._reload_voices()
        unmatched = [f"{k}（{c} 次）" for k, c in sorted(self.engine.unmatched.items(), key=lambda x: -x[1])]
        if list(self.lb_unmatched.get(0, "end")) != unmatched:
            self.lb_unmatched.delete(0, "end")
            for u in unmatched:
                self.lb_unmatched.insert("end", u)
        self.root.after(200, self._tick)


def run() -> None:
    try:
        ctypes_dpi()
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


def ctypes_dpi() -> None:
    """高 DPI 螢幕下字不要糊掉。"""
    import ctypes

    ctypes.windll.shcore.SetProcessDpiAwareness(1)
