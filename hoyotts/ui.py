"""hoyoTTS 圖形介面（tkinter，藍粉主題）。"""

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

UI_FONT = "Microsoft JhengHei UI"
FONT = (UI_FONT, 10)
FONT_BOLD = (UI_FONT, 10, "bold")
FONT_BIG = (UI_FONT, 13)
FONT_NAME = (UI_FONT, 13, "bold")
FONT_TITLE = (UI_FONT, 16, "bold")

# 藍粉主題：藍色為主，粉色點綴（開始按鈕、對話色帶、選項、朗讀中、勾選框）
BG = "#eef3fb"          # 視窗底色
CARD = "#ffffff"        # 卡片、分頁內容
FG = "#1c2a40"          # 主要文字
MUTED = "#5f6f88"       # 次要文字
BORDER = "#cdd9ee"
BLUE = "#3b6fd8"        # 主色
BLUE_DARK = "#24418a"   # 標題列、按下
BLUE_HOVER = "#4f82e6"
BLUE_SOFT = "#dce6f8"   # 一般按鈕、分頁標籤
BLUE_SOFT_HOVER = "#c8d8f4"
HEADER_MUTED = "#b8c9ee"
PINK = "#e8739e"        # 點綴色
PINK_DARK = "#c4507b"
PINK_HOVER = "#f08bb0"
PINK_SOFT = "#fbe1ea"

# 自動過劇情的選項：顯示文字 → 設定值
LINE_ACTIONS = {"空白鍵": "space", "滑鼠點擊": "click"}
INPUT_METHODS = {"送到原神視窗（不動滑鼠，遊戲可在背景）": "window", "模擬鍵盤滑鼠（遊戲要在前景）": "screen"}

# 標題列上的狀態燈（深藍底）
OK, WARN, BAD, OFF = "#7ee0b0", "#ffd45c", "#ff7b7b", "#8a9cc0"

# 狀態膠囊：狀態 → (底色, 字色, 說明)
PHASES = {
    "未啟動": ("#5f6f88", "#ffffff", "按「開始」監聽遊戲"),
    "待機中": ("#3557a8", "#e4ecfb", "等待下一段劇情對話"),
    "對話中": (BLUE_SOFT, BLUE_DARK, "辨識台詞中"),
    "合成中": ("#b9cdf3", BLUE_DARK, "語音合成中…"),
    "朗讀中": ("#f7a8c4", "#5a1530", "快念完時就可以點下一段"),
    "已暫停": ("#ffd45c", "#4a3a00", "朗讀已暫停"),
}


def _setup_style(root: tk.Tk) -> None:
    root.configure(bg=BG)
    # 不用 "*Font"：它會蓋掉 ttk 樣式裡設的字型（標題、大字）。ttk 的字型在下面的 "." 樣式設。
    for cls in ("Listbox", "Text", "Entry", "Label", "Button"):
        root.option_add(f"*{cls}.Font", FONT)
    root.option_add("*TCombobox*Listbox.Font", FONT)
    root.option_add("*TCombobox*Listbox.selectBackground", BLUE)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    st = ttk.Style(root)
    st.theme_use("clam")  # clam 才能自訂顏色
    st.configure(".", background=BG, foreground=FG, font=FONT, bordercolor=BORDER, lightcolor=BG,
                 darkcolor=BG, troughcolor=BLUE_SOFT, focuscolor=BLUE, fieldbackground=CARD,
                 selectbackground=BLUE, selectforeground="#ffffff")
    st.configure("TFrame", background=BG)
    st.configure("Card.TFrame", background=CARD)
    st.configure("Header.TFrame", background=BLUE_DARK)
    st.configure("TLabel", background=CARD, foreground=FG)
    st.configure("Muted.TLabel", background=CARD, foreground=MUTED)
    st.configure("Header.TLabel", background=BLUE_DARK, foreground="#ffffff")
    st.configure("HeaderMuted.TLabel", background=BLUE_DARK, foreground=HEADER_MUTED)
    st.configure("Title.TLabel", background=BLUE_DARK, foreground="#ffffff", font=FONT_TITLE)

    st.configure("TButton", background=BLUE_SOFT, foreground=BLUE_DARK, bordercolor=BORDER,
                 lightcolor=BLUE_SOFT, darkcolor=BLUE_SOFT, padding=(12, 6), relief="flat")
    st.map("TButton", background=[("pressed", BORDER), ("active", BLUE_SOFT_HOVER)],
           lightcolor=[("active", BLUE_SOFT_HOVER)], darkcolor=[("active", BLUE_SOFT_HOVER)])
    st.configure("Accent.TButton", background=PINK, foreground="#ffffff", bordercolor=PINK_DARK,
                 lightcolor=PINK, darkcolor=PINK, font=(UI_FONT, 11, "bold"), padding=(18, 7))
    st.map("Accent.TButton", background=[("pressed", PINK_DARK), ("active", PINK_HOVER)],
           lightcolor=[("active", PINK_HOVER)], darkcolor=[("active", PINK_HOVER)])

    st.configure("TNotebook", background=BG, borderwidth=0, bordercolor=BORDER)
    st.configure("TNotebook.Tab", background=BLUE_SOFT, foreground=BLUE_DARK, padding=(16, 6),
                 bordercolor=BORDER, lightcolor=BLUE_SOFT)
    st.map("TNotebook.Tab", background=[("selected", CARD), ("active", BLUE_SOFT_HOVER)],
           foreground=[("selected", BLUE)], lightcolor=[("selected", CARD)])
    st.configure("TLabelframe", background=CARD, bordercolor=BORDER, lightcolor=CARD, darkcolor=CARD)
    st.configure("TLabelframe.Label", background=CARD, foreground=BLUE_DARK, font=FONT_BOLD)
    st.configure("TCheckbutton", background=CARD, foreground=FG, indicatorbackground=CARD,
                 indicatorforeground="#ffffff")
    st.map("TCheckbutton", background=[("active", CARD)],
           indicatorbackground=[("selected", PINK), ("active", PINK_SOFT)])
    st.configure("Bar.TCheckbutton", background=BG, foreground=BLUE_DARK, font=FONT_BOLD)
    st.map("Bar.TCheckbutton", background=[("active", BG)])
    st.configure("TEntry", fieldbackground=CARD, bordercolor=BORDER, lightcolor=CARD, padding=4)
    st.map("TEntry", bordercolor=[("focus", BLUE)], lightcolor=[("focus", BLUE)])
    for w in ("TCombobox", "TSpinbox"):
        st.configure(w, fieldbackground=CARD, background=BLUE_SOFT, arrowcolor=BLUE_DARK,
                     bordercolor=BORDER, lightcolor=CARD, padding=3)
        st.map(w, bordercolor=[("focus", BLUE)], lightcolor=[("focus", BLUE)],
               fieldbackground=[("readonly", CARD)], selectbackground=[("readonly", CARD)],
               selectforeground=[("readonly", FG)])
    st.configure("Horizontal.TProgressbar", background=BLUE, troughcolor=BLUE_SOFT, bordercolor=BORDER,
                 lightcolor=BLUE, darkcolor=BLUE)
    st.configure("Horizontal.TScale", background=BLUE, troughcolor=BLUE_SOFT, bordercolor=BORDER,
                 lightcolor=BLUE, darkcolor=BLUE)
    st.map("Horizontal.TScale", background=[("active", BLUE_HOVER)])
    st.configure("Vertical.TScrollbar", background=BLUE_SOFT, troughcolor=CARD, bordercolor=CARD,
                 arrowcolor=BLUE_DARK, lightcolor=BLUE_SOFT, darkcolor=BLUE_SOFT)


def _style_tk(w: tk.Widget) -> None:
    """tk 原生元件（Listbox、Text）配色。"""
    w.configure(bg=CARD, fg=FG, relief="flat", borderwidth=0, highlightthickness=1,
                highlightbackground=BORDER, highlightcolor=BLUE, selectbackground=BLUE,
                selectforeground="#ffffff")


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
        self.dl_total = self.dl_done = 0
        self.remote_count = 0
        self._preview_win: tk.Toplevel | None = None
        self._phase: str | None = None

        root.title("hoyoTTS")
        ico = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon.ico")
        if os.path.exists(ico):
            try:
                root.iconbitmap(default=ico)
            except tk.TclError:
                pass
            set_window_icon(root, ico)
        root.geometry("1000x780")
        root.minsize(840, 640)
        _setup_style(root)

        self._build_header()
        self._build_controls()
        self._build_current()
        self._build_tabs()

        self._bind_hotkeys()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(200, self._tick)
        self.log(f"模型資料夾：{self.cfg['models_dir']}（已下載 {len(self.engine.library.names())} 個角色）")
        from .gameinput import is_admin

        if not is_admin():
            # main.py 開啟時已經要求過系統管理員（UAC 按了「否」才會到這裡），不再問一次
            self.log("⚠ 不是以系統管理員身分執行：遊戲裡的快捷鍵和自動過劇情的點擊會被原神擋掉")
        if self.cfg.get("auto_start", True):
            root.after(300, self.toggle_run)

    # ---------- 版面 ----------
    def _light(self, parent, text):
        f = ttk.Frame(parent, style="Header.TFrame")
        c = tk.Canvas(f, width=12, height=12, highlightthickness=0, bg=BLUE_DARK)
        dot = c.create_oval(1, 1, 11, 11, fill=OFF, outline="")
        c.pack(side="left", padx=(0, 6))
        ttk.Label(f, text=text, style="HeaderMuted.TLabel").pack(side="left")
        val = ttk.Label(f, text="—", style="Header.TLabel")
        val.pack(side="left", padx=(6, 0))
        f.pack(side="left", padx=(0, 28))
        return c, dot, val

    def _build_header(self):
        """深藍標題列：名稱、目前狀態、三個狀態燈。"""
        head = ttk.Frame(self.root, style="Header.TFrame", padding=(18, 12, 18, 10))
        head.pack(fill="x")
        top = ttk.Frame(head, style="Header.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="hoyoTTS", style="Title.TLabel").pack(side="left")
        ttk.Label(top, text="原神劇情語音朗讀", style="HeaderMuted.TLabel").pack(side="left", padx=(10, 0), pady=(5, 0))
        self.l_phase = tk.Label(top, text="", font=FONT_BOLD, padx=14, pady=3, bd=0)
        self.l_phase.pack(side="right")
        self.l_phase_hint = ttk.Label(top, text="", style="HeaderMuted.TLabel")
        self.l_phase_hint.pack(side="right", padx=(0, 10))
        lights = ttk.Frame(head, style="Header.TFrame")
        lights.pack(fill="x", pady=(10, 0))
        self.l_cap = self._light(lights, "遊戲擷取")
        self.l_srv = self._light(lights, "TTS 伺服器")
        self.l_mod = self._light(lights, "角色模型")

    def _build_controls(self):
        bar = ttk.Frame(self.root, padding=(16, 12, 16, 4))
        bar.pack(fill="x")
        hk = self.cfg["hotkeys"]
        self.b_run = ttk.Button(bar, text="▶  開始", style="Accent.TButton", width=8, command=self.toggle_run)
        self.b_run.pack(side="left")
        self.b_pause = ttk.Button(bar, text=f"⏸ 暫停朗讀  {hk['pause']}", command=self.toggle_pause)
        self.b_pause.pack(side="left", padx=(12, 0))
        ttk.Button(bar, text=f"⏹ 停止這句  {hk['stop']}", command=self.engine.interrupt).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text=f"↻ 重念  {hk['replay']}", command=self.engine.replay).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="擷取預覽", command=self.show_preview).pack(side="right")
        self.var_auto_play = tk.BooleanVar(value=self.cfg["auto_play"].get("enabled", False))
        ttk.Checkbutton(bar, text="自動過劇情", style="Bar.TCheckbutton", variable=self.var_auto_play,
                        command=self._toggle_auto_play).pack(side="right", padx=(0, 14))

    def _build_current(self):
        """目前對話卡片，左邊一條粉色色帶。"""
        outer = tk.Frame(self.root, bg=BORDER)
        outer.pack(fill="x", padx=16, pady=(8, 4))
        tk.Frame(outer, bg=PINK, width=5).pack(side="left", fill="y")
        box = ttk.Frame(outer, style="Card.TFrame", padding=(14, 10, 14, 12))
        box.pack(side="left", fill="both", expand=True, padx=(0, 1), pady=1)
        top = ttk.Frame(box, style="Card.TFrame")
        top.pack(fill="x")
        self.v_name = ttk.Label(top, text="—", font=FONT_NAME, foreground=BLUE_DARK)
        self.v_name.pack(side="left")
        self.v_voice = ttk.Label(top, text="", style="Muted.TLabel")
        self.v_voice.pack(side="left", padx=(10, 0))
        self.v_text = ttk.Label(box, text="", font=FONT_BIG, wraplength=900, justify="left")
        self.v_text.pack(fill="x", pady=(6, 0))
        self.v_opts = ttk.Label(box, text="", foreground=PINK_DARK, wraplength=900, justify="left")
        self.v_opts.pack(fill="x", pady=(4, 0))
        self.v_speaking = ttk.Label(box, text="", style="Muted.TLabel")
        self.v_speaking.pack(fill="x", pady=(6, 0))

        def rewrap(e):
            for w in (self.v_text, self.v_opts, self.v_speaking):
                w.config(wraplength=max(300, e.width - 40))

        box.bind("<Configure>", rewrap)

    def _build_tabs(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=16, pady=(8, 16))
        self.nb = nb
        self._tab_log(nb)
        self._tab_settings(nb)
        self._tab_alias(nb)
        self._tab_download(nb)
        self._tab_test(nb)

    def _tab(self, nb, text, padding=14):
        f = ttk.Frame(nb, padding=padding, style="Card.TFrame")
        nb.add(f, text=text)
        return f

    def _tab_log(self, nb):
        f = self._tab(nb, "紀錄", 8)
        self.t_log = ScrolledText(f, height=12, font=FONT, state="disabled", wrap="word", padx=8, pady=6)
        _style_tk(self.t_log)
        self.t_log.tag_configure("time", foreground="#8a97ad")
        self.t_log.tag_configure("synth", foreground="#7d8aa3")
        self.t_log.tag_configure("opt", foreground=PINK_DARK)
        self.t_log.pack(fill="both", expand=True)

    def _voice_combo(self, parent, value):
        cb = ttk.Combobox(parent, values=self.engine.library.names(), width=18)
        cb.set(value)
        return cb

    def _tab_settings(self, nb):
        f = self._tab(nb, "設定")
        v = self.cfg["voices"]
        g = ttk.Labelframe(f, text="聲音", padding=12)
        g.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        rows = [("找不到模型的角色", "fallback"), ("旅行者的對話選項", "options"), ("旁白（沒有角色名）", "narrator")]
        self.voice_combos = {}
        for i, (label, key) in enumerate(rows):
            ttk.Label(g, text=label).grid(row=i, column=0, sticky="w", pady=4)
            cb = self._voice_combo(g, v[key])
            cb.grid(row=i, column=1, sticky="w", padx=(10, 0))
            self.voice_combos[key] = cb
        self.var_opts = tk.BooleanVar(value=self.cfg.get("read_options", True))
        ttk.Checkbutton(g, text="念對話選項", variable=self.var_opts).grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.var_auto = tk.BooleanVar(value=self.cfg.get("auto_start", True))
        ttk.Checkbutton(g, text="開啟程式時自動開始", variable=self.var_auto).grid(row=4, column=0, columnspan=2, sticky="w", pady=(2, 0))

        p = ttk.Labelframe(f, text="播放", padding=12)
        p.grid(row=0, column=1, sticky="nsew")
        self.var_vol = tk.DoubleVar(value=self.cfg["volume"])
        self.var_speed = tk.DoubleVar(value=self.cfg["speed"])
        for i, (label, var, lo, hi) in enumerate([("音量", self.var_vol, 0, 1.5), ("語速", self.var_speed, 0.6, 1.6)]):
            ttk.Label(p, text=label).grid(row=i, column=0, sticky="w", pady=4)
            ttk.Scale(p, from_=lo, to=hi, variable=var, length=200,
                      command=lambda _=None: self._apply_live()).grid(row=i, column=1, padx=10)
            lab = ttk.Label(p, width=5, style="Muted.TLabel")
            lab.grid(row=i, column=2)
            var.trace_add("write", lambda *_, l=lab, vv=var: l.config(text=f"{vv.get():.2f}"))
            var.set(var.get())
        ttk.Label(p, text="點下一段時").grid(row=2, column=0, sticky="w", pady=4)
        tail = ttk.Frame(p, style="Card.TFrame")
        tail.grid(row=2, column=1, columnspan=2, sticky="w", padx=10)
        ttk.Label(tail, text="剩不到").pack(side="left")
        self.var_tail = tk.StringVar(value=f"{self.cfg.get('finish_tail', 3.0):g}")
        ttk.Spinbox(tail, from_=0, to=10, increment=0.5, width=5, textvariable=self.var_tail,
                    command=self._apply_live).pack(side="left", padx=4)
        ttk.Label(tail, text="秒就先念完這句").pack(side="left")
        ttk.Label(p, text="（0＝一律立刻打斷；剩比較多才點會當作跳過）", style="Muted.TLabel").grid(
            row=3, column=1, columnspan=2, sticky="w", padx=10)
        ttk.Label(p, text="自動過劇情").grid(row=4, column=0, sticky="w", pady=4)
        auto = ttk.Frame(p, style="Card.TFrame")
        auto.grid(row=4, column=1, columnspan=2, sticky="w", padx=10)
        ttk.Label(auto, text="念完後等").pack(side="left")
        self.var_auto_delay = tk.StringVar(value=f"{self.cfg['auto_play'].get('delay', 0.6):g}")
        ttk.Spinbox(auto, from_=0, to=5, increment=0.1, width=5, textvariable=self.var_auto_delay,
                    command=self._apply_live).pack(side="left", padx=4)
        ttk.Label(auto, text="秒，台詞按").pack(side="left")
        ap = self.cfg["auto_play"]
        self.cb_line_action = ttk.Combobox(auto, values=list(LINE_ACTIONS), state="readonly", width=8)
        self.cb_line_action.set(next((k for k, v in LINE_ACTIONS.items() if v == ap.get("line_action", "space")),
                                     "空白鍵"))
        self.cb_line_action.pack(side="left", padx=4)
        ttk.Label(auto, text="、選項按 F").pack(side="left")
        ttk.Label(p, text="送出方式").grid(row=5, column=0, sticky="w", pady=4)
        self.cb_method = ttk.Combobox(p, values=list(INPUT_METHODS), state="readonly", width=34)
        self.cb_method.set(next((k for k, v in INPUT_METHODS.items() if v == ap.get("method", "window")),
                                list(INPUT_METHODS)[0]))
        self.cb_method.grid(row=5, column=1, columnspan=2, sticky="w", padx=10)
        for cb in (self.cb_line_action, self.cb_method):
            cb.bind("<<ComboboxSelected>>", lambda e: self._apply_live())
        hk = self.cfg["hotkeys"]
        self.hk_entries = {}
        for i, (label, key) in enumerate([("停止這句", "stop"), ("暫停／繼續", "pause"), ("重念", "replay")], start=6):
            ttk.Label(p, text=f"快捷鍵：{label}").grid(row=i, column=0, sticky="w", pady=4)
            e = ttk.Entry(p, width=12)
            e.insert(0, hk[key])
            e.grid(row=i, column=1, sticky="w", padx=10)
            self.hk_entries[key] = e

        m = ttk.Labelframe(f, text="模型資料夾", padding=12)
        m.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.e_dir = ttk.Entry(m, width=60)
        self.e_dir.insert(0, self.cfg["models_dir"])
        self.e_dir.pack(side="left", fill="x", expand=True)
        ttk.Button(m, text="瀏覽…", command=self._browse_dir).pack(side="left", padx=6)
        ttk.Button(m, text="重新載入模型", command=lambda: self._reload_voices(True)).pack(side="left")

        ttk.Button(f, text="儲存設定", style="Accent.TButton", command=self.save_settings).grid(
            row=2, column=0, columnspan=2, sticky="e", pady=(14, 0))
        f.columnconfigure(0, weight=1)
        f.columnconfigure(1, weight=1)

    def _tab_alias(self, nb):
        f = self._tab(nb, "角色對應")
        ttk.Label(f, text="找不到模型的角色會用後備聲音。在這裡把角色名指定給某個模型，例如把你的旅行者名字對到「空」。",
                  style="Muted.TLabel", wraplength=880).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        left = ttk.Labelframe(f, text="最近沒對應到的角色（雙擊帶入）", padding=8)
        left.grid(row=1, column=0, sticky="nsew")
        self.lb_unmatched = tk.Listbox(left, height=12, activestyle="none")
        _style_tk(self.lb_unmatched)
        self.lb_unmatched.pack(fill="both", expand=True)
        self.lb_unmatched.bind("<Double-1>", self._pick_unmatched)

        mid = ttk.Frame(f, padding=(14, 0), style="Card.TFrame")
        mid.grid(row=1, column=1, sticky="n")
        ttk.Label(mid, text="遊戲裡的角色名").pack(anchor="w")
        self.e_alias = ttk.Entry(mid, width=18)
        self.e_alias.pack(anchor="w", pady=(2, 10))
        ttk.Label(mid, text="使用模型").pack(anchor="w")
        self.cb_alias = self._voice_combo(mid, "")
        self.cb_alias.pack(anchor="w", pady=(2, 10))
        ttk.Button(mid, text="新增／更新 →", style="Accent.TButton", command=self._add_alias).pack(anchor="w", fill="x")
        ttk.Button(mid, text="← 刪除選取", command=self._del_alias).pack(anchor="w", fill="x", pady=(6, 0))

        right = ttk.Labelframe(f, text="已設定的對應", padding=8)
        right.grid(row=1, column=2, sticky="nsew")
        self.lb_alias = tk.Listbox(right, height=12, activestyle="none")
        _style_tk(self.lb_alias)
        self.lb_alias.pack(fill="both", expand=True)
        f.columnconfigure(0, weight=1)
        f.columnconfigure(2, weight=1)
        f.rowconfigure(1, weight=1)
        self._refresh_alias()

    def _tab_download(self, nb):
        f = self._tab(nb, "模型下載")
        ttk.Label(f, text="來源：ModelScope aihobbyist/GPT-SoVITS_Model_Collection（中文，CC-BY-NC，禁止商用與二次散布）。"
                          "每個角色約 200–300MB；原神全部約 56GB、星穹鐵道約 36GB。已下載的會跳過，中斷後可以續傳。",
                  style="Muted.TLabel", wraplength=880).pack(anchor="w")
        row = ttk.Frame(f, style="Card.TFrame")
        row.pack(fill="x", pady=12)
        ttk.Label(row, text="遊戲：").pack(side="left")
        self.cb_dl_game = ttk.Combobox(row, values=[V.GAME_LABELS[g] for g in V.GAMES], width=14, state="readonly")
        self.cb_dl_game.set(V.GAME_LABELS.get(self.cfg["game"], self.cfg["game"]))
        self.cb_dl_game.pack(side="left", padx=(0, 14))
        self.b_dl_all = ttk.Button(row, text="下載全部", style="Accent.TButton", command=self.download_all)
        self.b_dl_all.pack(side="left")
        ttk.Button(row, text="停止下載", command=self.dl_stop.set).pack(side="left", padx=6)
        ttk.Label(row, text="或只下載：").pack(side="left", padx=(20, 4))
        self.e_dl_one = ttk.Entry(row, width=14)
        self.e_dl_one.pack(side="left")
        ttk.Button(row, text="下載", command=self.download_one).pack(side="left", padx=4)
        self.pb = ttk.Progressbar(f, mode="determinate")
        self.pb.pack(fill="x")
        self.l_dl = ttk.Label(f, text="", style="Muted.TLabel")
        self.l_dl.pack(anchor="w", pady=(6, 0))

    def _tab_test(self, nb):
        f = self._tab(nb, "試聽")
        ttk.Label(f, text="輸入文字（繁簡都可以），選一個角色念念看：").pack(anchor="w")
        self.t_test = tk.Text(f, height=4, wrap="word", font=FONT_BIG, padx=8, pady=6, insertbackground=BLUE)
        _style_tk(self.t_test)
        self.t_test.insert("1.0", "旅行者，我們快走吧！前面好像有寶箱哦。")
        self.t_test.pack(fill="x", pady=8)
        row = ttk.Frame(f, style="Card.TFrame")
        row.pack(fill="x")
        self.cb_test = self._voice_combo(row, "派蒙" if self.engine.library.get("派蒙") else self.cfg["voices"]["fallback"])
        self.cb_test.pack(side="left")
        ttk.Button(row, text="念出來", style="Accent.TButton", command=self._test_speak).pack(side="left", padx=8)
        ttk.Label(f, text="需要先按「開始」讓 TTS 伺服器啟動。", style="Muted.TLabel").pack(anchor="w", pady=(10, 0))

    # ---------- 動作 ----------
    def log(self, msg: str) -> None:  # 任何執行緒都能呼叫
        self.logq.put(f"{time.strftime('%H:%M:%S')}  {msg}")

    def toggle_run(self):
        if self.engine.state.running:
            threading.Thread(target=self.engine.stop, daemon=True).start()
            self.b_run.config(text="▶  開始")
        else:
            self.engine.start()
            self.b_run.config(text="■  停止")

    def toggle_pause(self):
        self.engine.set_paused(not self.engine.state.paused)

    def _bind_hotkeys(self):
        hk = self.cfg["hotkeys"]
        ui = lambda fn: (lambda: self.root.after(0, fn))  # noqa: E731  回到 UI 執行緒
        self.hotkeys.start({hk["stop"]: ui(self.engine.interrupt), hk["pause"]: ui(self.toggle_pause),
                            hk["replay"]: ui(self.engine.replay)})

    def _toggle_auto_play(self):
        on = self.var_auto_play.get()
        self.cfg["auto_play"]["enabled"] = on
        save_config(self.cfg)
        if on:
            ap = self.cfg["auto_play"]
            line = "點擊對話框" if ap.get("line_action") == "click" else "按空白鍵"
            where = "（遊戲要在前景）" if ap.get("method") == "screen" else "（直接送給原神視窗）"
            self.log(f"自動過劇情：開啟。台詞念完{line}，選項念完按 {ap.get('option_key', 'F')} 選第一個{where}")
            self._offer_admin(running=self.engine.state.running)
        else:
            self.log("自動過劇情：關閉")

    def _offer_admin(self, running: bool) -> bool:
        """不是系統管理員時，問要不要以系統管理員身分重開（原神會擋掉一般權限程式的點擊）。
        回傳 True 表示已經重開、這個視窗要關掉。"""
        from .gameinput import is_admin, relaunch_as_admin, release_instance

        if is_admin():
            return False
        if not messagebox.askyesno(
                "hoyoTTS", "自動過劇情需要以系統管理員身分執行（原神會擋掉一般權限程式的點擊）。\n\n"
                           "要以系統管理員身分重新開啟 hoyoTTS 嗎？", parent=self.root):
            self.log("⚠ 不是以系統管理員身分執行，自動過劇情的點擊會被原神擋掉")
            return False
        # 先放掉快捷鍵和 TTS 伺服器，新開的才拿得到
        self.hotkeys.stop()
        if running:
            self.engine.shutdown()
        release_instance()
        if relaunch_as_admin():
            self.dl_stop.set()
            if not running:
                self.engine.shutdown()
            self.root.after(0, self.root.destroy)
            return True
        self.log("沒有取得系統管理員權限，繼續用一般權限執行")
        self._bind_hotkeys()
        if running:
            self.engine.start()
        return False

    def _apply_live(self):
        self.cfg["volume"] = round(self.var_vol.get(), 2)
        self.cfg["speed"] = round(self.var_speed.get(), 2)
        try:
            self.cfg["finish_tail"] = min(10.0, max(0.0, round(float(self.var_tail.get()), 1)))
        except ValueError:
            pass
        try:
            self.cfg["auto_play"]["delay"] = min(5.0, max(0.0, round(float(self.var_auto_delay.get()), 1)))
        except ValueError:
            pass
        self.cfg["auto_play"]["line_action"] = LINE_ACTIONS.get(self.cb_line_action.get(), "space")
        self.cfg["auto_play"]["method"] = INPUT_METHODS.get(self.cb_method.get(), "window")

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

    def _reload_voices(self, from_entry: bool = False, quiet: bool = False):
        if from_entry:  # 「重新載入模型」按鈕：套用輸入框裡的資料夾
            self.cfg["models_dir"] = self.e_dir.get().strip()
        self.engine.reload_voices(quiet=quiet)
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

    def _dl_game(self) -> str:
        label = self.cb_dl_game.get()
        return next((g for g, l in V.GAME_LABELS.items() if l == label), self.cfg["game"])

    def download_all(self, names: list[str] | None = None):
        if self.dl_thread and self.dl_thread.is_alive():
            self.log("已經在下載中")
            return
        self.dl_stop.clear()
        models_dir = self.cfg["models_dir"]
        game, lang = self._dl_game(), self.cfg["lang"]

        def run():
            try:
                remote = V.list_remote(game, lang)
            except Exception as e:
                self.log(f"取得模型清單失敗：{e}")
                return
            if game == self.cfg["game"]:
                self.remote_count = len(remote)
            if names:
                remote = [m for m in remote if m.name in names]
                if not remote:
                    self.log(f"找不到模型：{'、'.join(names)}")
                    return
            dest = V.lang_dir(models_dir, game, lang)
            todo = [m for m in remote if not V.find_local(dest, m.name)]
            self.log(f"{V.GAME_LABELS.get(game, game)}：要下載 {len(todo)} 個角色（{sum(m.size for m in todo) / 1e9:.1f} GB）")
            self.dl_total = len(todo)
            self.dl_done = 0

            def logdone(s):
                if s.startswith("完成"):
                    self.dl_done += 1
                    self.dl_progress.pop(s[3:], None)
                self.log("下載" + s)

            failed = V.download_many(todo, models_dir, workers=3, log=logdone, stop=self.dl_stop, game=game, lang=lang,
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

        reader = self.engine.reader or DialogueReader(self.cfg["regions"], engine=self.cfg.get("ocr_engine", "rapid"))
        self.engine.reader = reader
        st = reader.read(frame)
        img = reader.debug_image(frame)
        img.thumbnail((960, 540))
        if self._preview_win and self._preview_win.winfo_exists():
            self._preview_win.destroy()
        w = tk.Toplevel(self.root, bg=CARD)
        w.title("擷取預覽")
        self._preview_win = w
        photo = ImageTk.PhotoImage(img)
        lab = ttk.Label(w, image=photo)
        lab.image = photo
        lab.pack()
        info = (f"在對話中：{'是' if st.in_dialogue else '否'}（綠線＝偵測到對話分隔線）\n"
                f"角色：{st.name or '—'}\n台詞：{st.text or '—'}\n選項：{' ／ '.join(st.options) or '—'}")
        ttk.Label(w, text=info, padding=10, wraplength=940, justify="left").pack(anchor="w")

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

    def _append_log(self, lines: list[str]) -> None:
        self.t_log.config(state="normal")
        for line in lines:
            ts, _, msg = line.partition("  ")
            tag = "synth" if msg.startswith("  ▶") else ("opt" if msg.startswith("選項：") else "")
            self.t_log.insert("end", ts + "  ", "time")
            self.t_log.insert("end", msg + "\n", tag)
        n = int(self.t_log.index("end-1c").split(".")[0])
        if n > 2000:
            self.t_log.delete("1.0", f"{n - 2000}.0")
        self.t_log.see("end")
        self.t_log.config(state="disabled")

    def _tick(self):
        lines = []
        try:
            while True:
                lines.append(self.logq.get_nowait())
        except queue.Empty:
            pass
        if lines:
            self._append_log(lines)

        s = self.engine.state
        phase = s.phase
        if phase != self._phase:
            self._phase = phase
            bg, fg, hint = PHASES[phase]
            self.l_phase.config(text=f"● {phase}", bg=bg, fg=fg)
            self.l_phase_hint.config(text=hint)

        cap = s.capture if s.running else "未啟動"
        self._set_light(self.l_cap, OK if "擷取中" in cap else (WARN if s.running else OFF), cap)
        srv = s.server
        self._set_light(self.l_srv, OK if srv == "就緒" else (BAD if "失敗" in srv else (WARN if s.running else OFF)), srv)
        n = len(self.engine.library.names())
        total = self.remote_count or 263
        dl = f"（下載中 {self.dl_done}/{self.dl_total}）" if self.dl_thread and self.dl_thread.is_alive() else ""
        self._set_light(self.l_mod, OK if n else BAD, f"{n}/{total} {dl}")
        self.b_pause.config(text=("▶ 繼續朗讀" if s.paused else "⏸ 暫停朗讀") + f"  {self.cfg['hotkeys']['pause']}")

        if s.running and s.in_dialogue:
            self.v_name.config(text=s.name or "（旁白）")
            v, note = self.engine.resolve_voice(s.name) if s.text else (None, "")
            self.v_voice.config(text=f"→ {v.name}{'（' + note + '）' if note else ''}" if v else "")
            self.v_text.config(text=s.text)
            self.v_opts.config(text=("選項：" + " ／ ".join(s.options)) if s.options else "")
        elif s.running:
            self.v_name.config(text="待機中")
            self.v_voice.config(text="進入劇情對話後會自動開始念")
            self.v_text.config(text="")
            self.v_opts.config(text="")
        else:
            self.v_name.config(text="—")
            self.v_voice.config(text="按「開始」監聽遊戲畫面")
        self.v_speaking.config(text=("🔊 正在念　" + s.speaking[:80]) if s.speaking else "")

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
                on_disk = -1
            # 跟上次掃描比（不是跟可用模型數比：少數上游模型缺檔，資料夾數會一直比可用數多）
            if on_disk != getattr(self, "_last_on_disk", on_disk):
                self._reload_voices(quiet=True)
            self._last_on_disk = on_disk
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


def set_window_icon(root: tk.Tk, ico: str) -> None:
    """Tk 只給 Windows 32px 的大圖示，Win11 工作列（100% 縮放是 24px）再自己縮，32→24 縮起來很糊。
    直接從 .ico 挑剛好工作列大小的那張（ico 裡有為小尺寸另外畫的清楚版本）設成視窗的大圖示。"""
    import ctypes
    import sys

    try:
        root.update_idletasks()
        hwnd = int(root.wm_frame(), 16)
        u32 = ctypes.windll.user32
        u32.LoadImageW.restype = ctypes.c_void_p
        u32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        dpi = u32.GetDpiForWindow(ctypes.c_void_p(hwnd)) or 96
        win11 = sys.getwindowsversion().build >= 22000
        big = round((24 if win11 else 32) * dpi / 96)
        small = round(16 * dpi / 96)
        for which, size in ((1, big), (0, small)):  # ICON_BIG、ICON_SMALL
            h = u32.LoadImageW(None, ico, 1, size, size, 0x10)  # IMAGE_ICON、LR_LOADFROMFILE
            if h:
                u32.SendMessageW(ctypes.c_void_p(hwnd), 0x80, ctypes.c_void_p(which), ctypes.c_void_p(h))  # WM_SETICON
    except Exception:
        pass


def ctypes_dpi() -> None:
    """高 DPI 螢幕下字不要糊掉；並設定自己的 AppUserModelID，工作列才會顯示 hoyoTTS 的圖示而不是 Python 的。"""
    import ctypes

    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("hoyoTTS.app")
    except (AttributeError, OSError):
        pass
