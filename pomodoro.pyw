"""
番茄钟 - Pomodoro Timer
一个功能丰富的桌面番茄钟软件

核心功能：
  - 番茄工作法计时（工作 → 短休息 → 长休息循环）
  - 圆环进度条 + 深色/浅色主题切换
  - 自定义时长设置（持久化到本地文件）
  - 任务标签（记录每个番茄做了什么）
  - 番茄日志 & 统计视图（柱状图）
  - 自动开始下一阶段
  - 窗口可拖动
  - 正弦波提示音 + 窗口闪烁提醒

文件扩展名说明：
  .pyw 是 Windows 专用扩展名，双击时用 pythonw.exe 运行（不弹黑色命令行窗口）。
"""

# ============================================================
#  导入模块
# ============================================================

import tkinter as tk
import math
import os
import array
import wave
import winsound
import ctypes
import tempfile
import json
import random
import uuid
import calendar as cal_mod
from datetime import datetime, timedelta

# 高 DPI 适配
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass


# ============================================================
#  持久化文件路径
# ============================================================

_HOME_DIR = os.path.expanduser("~")
CONFIG_PATH  = os.path.join(_HOME_DIR, ".pomodoro_config.json")
LOG_PATH     = os.path.join(_HOME_DIR, ".pomodoro_log.json")
EVENTS_PATH  = os.path.join(_HOME_DIR, ".pomodoro_events.json")
NOTES_PATH   = os.path.join(_HOME_DIR, ".pomodoro_notes.json")


# ============================================================
#  全局配置常量（默认值，会被配置文件覆盖）
# ============================================================

WORK_MINUTES             = 25
SHORT_BREAK_MINUTES      = 5
LONG_BREAK_MINUTES       = 15
POMODOROS_BEFORE_LONG_BREAK = 4
AUTO_START_ENABLED       = False


# ============================================================
#  主题配色
# ============================================================

THEMES = {
    "dark": {
        "bg":              "#1e1e2e",
        "surface":         "#313244",
        "text":            "#cdd6f4",
        "text_dim":        "#6c7086",
        "work":            "#f38ba8",
        "work_bg":         "#45273a",
        "short_break":     "#a6e3a1",
        "short_break_bg":  "#2d3a2d",
        "long_break":      "#89b4fa",
        "long_break_bg":   "#273045",
        "accent":          "#cba6f7",
        "button":          "#45475a",
        "button_hover":    "#585b70",
        "entry_bg":        "#45475a",
        "entry_fg":        "#cdd6f4",
        "chart_bg":        "#313244",
        "chart_bar":       "#89b4fa",
        "splash_bg":       "#2a2a3d",
    },
    "light": {
        "bg":              "#eff1f5",
        "surface":         "#ccd0da",
        "text":            "#4c4f69",
        "text_dim":        "#8c8fa1",
        "work":            "#d20f39",
        "work_bg":         "#f2d5d5",
        "short_break":     "#40a02b",
        "short_break_bg":  "#d5f0c8",
        "long_break":      "#1e66f5",
        "long_break_bg":   "#c8d8f8",
        "accent":          "#8839ef",
        "button":          "#ccd0da",
        "button_hover":    "#bcc0cc",
        "entry_bg":        "#ccd0da",
        "entry_fg":        "#4c4f69",
        "chart_bg":        "#ccd0da",
        "chart_bar":       "#1e66f5",
        "splash_bg":       "#e8e4df",
    },
}

# 当前主题名和颜色字典（运行时可切换）
_current_theme_name = "dark"
COLORS = dict(THEMES["dark"])


def _apply_theme(theme_name):
    """切换全局主题。"""
    global _current_theme_name, COLORS
    _current_theme_name = theme_name
    COLORS = THEMES[theme_name]


# ── Windows FLASHWINFO 结构体（模块级，避免每次闪烁重建类）──
class FLASHWINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize",    ctypes.c_uint),
        ("hwnd",      ctypes.c_void_p),
        ("dwFlags",   ctypes.c_uint),
        ("uCount",    ctypes.c_uint),
        ("dwTimeout", ctypes.c_uint),
    ]


def _json_load(path, default=None):
    """通用 JSON 加载。文件不存在或解析失败返回 default。"""
    if default is None:
        default = []
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, type(default)):
                    return data
    except Exception:
        pass
    return default


def _json_save(path, data):
    """通用 JSON 保存。"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class PomodoroTimer:
    """
    番茄钟主类，封装全部界面和逻辑。

    状态机：

        work ──(完成)──▶ short_break / long_break ──(完成)──▶ work
                     ↑ pomodoro_count % 4 == 0 → long_break
                     ↑ 否则 → short_break
    """

    # 各模式的 (前景色, 背景色) 查表键
    MODE_COLORS_KEYS = {
        "work":        ("work",        "work_bg"),
        "short_break": ("short_break", "short_break_bg"),
        "long_break":  ("long_break",  "long_break_bg"),
    }

    MODE_TEXT  = {"work": "专注时间", "short_break": "短休息", "long_break": "长休息"}
    MODE_EMOJI = {"work": "🍅",     "short_break": "☕",      "long_break": "🌙"}

    WEEKDAY_NAMES = ["一", "二", "三", "四", "五", "六", "日"]

    EVENT_TYPE_EMOJI = {
        "birthday": "🎂", "holiday": "🎄", "anniversary": "📅",
        "exam": "📝", "travel": "✈️", "other": "📌",
    }

    # ============================================================
    #  初始化
    # ============================================================

    def __init__(self):
        # ── 1. 加载配置 & 日志 ─────────────────────────
        self.config = self._load_config()
        self.log_data = self._load_log()

        # 用配置覆盖默认常量
        global WORK_MINUTES, SHORT_BREAK_MINUTES, LONG_BREAK_MINUTES
        global POMODOROS_BEFORE_LONG_BREAK, AUTO_START_ENABLED
        WORK_MINUTES             = self.config.get("work_minutes", 25)
        SHORT_BREAK_MINUTES      = self.config.get("short_break_minutes", 5)
        LONG_BREAK_MINUTES       = self.config.get("long_break_minutes", 15)
        POMODOROS_BEFORE_LONG_BREAK = self.config.get("pomodoros_before_long", 4)
        AUTO_START_ENABLED       = self.config.get("auto_start", False)

        # 应用保存的主题
        saved_theme = self.config.get("theme", "dark")
        if saved_theme in THEMES:
            _apply_theme(saved_theme)

        # ── 2. 创建主窗口 ─────────────────────────────
        self.root = tk.Tk()
        self.root.title("🍅 番茄钟")
        self.root.configure(bg=COLORS["bg"])
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)

        # 窗口居中
        win_w, win_h = 380, 700
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = (screen_w - win_w) // 2
        y = (screen_h - win_h) // 2
        self.root.geometry(f"{win_w}x{win_h}+{x}+{y}")

        # ── 3. 初始化状态变量 ─────────────────────────
        self.is_running     = False
        self.is_paused      = False
        self.remaining_seconds = WORK_MINUTES * 60
        self.total_seconds  = WORK_MINUTES * 60
        self.current_mode   = "work"
        self.pomodoro_count = 0      # 本轮周期已完成番茄数
        self.current_task   = ""     # 当前任务名
        self.timer_id       = None

        # 平滑动画：100ms 为一个 tick，tick_count 累计到 10 = 1 秒
        self.tick_count     = 0

        # 自动开始状态
        self.auto_start_counter = 0
        self.auto_start_id      = None

        # ── 4. 缓存提示音 ─────────────────────────────
        self._chime_path = os.path.join(tempfile.gettempdir(), "pomodoro_chime.wav")
        self._generate_wav(self._chime_path)

        # ── 5. 播放开启动画（动画结束后自动构建主界面）──
        self._show_splash()

    # ============================================================
    #  配置 & 日志
    # ============================================================

    def _load_config(self):
        """从 JSON 文件加载配置，文件不存在则返回空字典。"""
        return _json_load(CONFIG_PATH, {})

    def _save_config(self):
        """保存当前配置到 JSON 文件。"""
        _json_save(CONFIG_PATH, {
            "work_minutes":          WORK_MINUTES,
            "short_break_minutes":   SHORT_BREAK_MINUTES,
            "long_break_minutes":    LONG_BREAK_MINUTES,
            "pomodoros_before_long": POMODOROS_BEFORE_LONG_BREAK,
            "auto_start":            AUTO_START_ENABLED,
            "theme":                 _current_theme_name,
        })

    def _load_log(self):
        """从 JSON 文件加载番茄日志。"""
        return _json_load(LOG_PATH, [])

    def _save_log(self):
        """保存番茄日志到 JSON 文件。"""
        _json_save(LOG_PATH, self.log_data)

    def _log_pomodoro(self, task, duration_minutes):
        """记录一个完成的番茄到日志。"""
        entry = {
            "time":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "task":     task,
            "duration": duration_minutes,
        }
        self.log_data.append(entry)
        self._save_log()

    def _get_today_stats(self):
        """返回 (今日番茄数, 今日专注总分钟数)。"""
        today = datetime.now().strftime("%Y-%m-%d")
        today_entries = [e for e in self.log_data if e.get("time", "").startswith(today)]
        count = len(today_entries)
        total_min = sum(e.get("duration", WORK_MINUTES) for e in today_entries)
        return count, total_min

    def _get_week_data(self):
        """返回最近 7 天每天的番茄数 [(日期str, 数量), ...]。"""
        today = datetime.now().date()
        result = []
        for i in range(6, -1, -1):
            day = today - timedelta(days=i)
            day_str = day.strftime("%Y-%m-%d")
            count = sum(1 for e in self.log_data if e.get("time", "").startswith(day_str))
            result.append((day_str, count))
        return result

    def _get_total_focus_minutes(self):
        """返回历史总专注分钟数。"""
        return sum(e.get("duration", WORK_MINUTES) for e in self.log_data)

    # ============================================================
    #  窗口拖动
    # ============================================================

    def _bind_drag(self, widget):
        """递归绑定拖动事件到所有子组件。"""
        widget.bind("<Button-1>",       self._on_drag_start)
        widget.bind("<B1-Motion>",      self._on_drag_motion)
        widget.bind("<ButtonRelease-1>", self._on_drag_end)
        for child in widget.winfo_children():
            self._bind_drag(child)

    def _on_drag_start(self, event):
        self._drag_data["x"] = event.x_root - self.root.winfo_x()
        self._drag_data["y"] = event.y_root - self.root.winfo_y()

    def _on_drag_motion(self, event):
        new_x = event.x_root - self._drag_data["x"]
        new_y = event.y_root - self._drag_data["y"]
        self.root.geometry(f"+{new_x}+{new_y}")

    def _on_drag_end(self, event):
        pass

    # ============================================================
    #  开启动画
    # ============================================================

    def _show_splash(self):
        """
        显示开启动画：果冻吉祥物弹跳入场 + 珍珠进度条。
        动画持续约 2.5 秒，结束后自动进入主界面。
        """
        self.splash_canvas = tk.Canvas(
            self.root,
            width=380, height=700,
            bg=COLORS.get("splash_bg", "#2a2a3d"),
            highlightthickness=0,
        )
        self.splash_canvas.place(x=0, y=0, relwidth=1, relheight=1)

        self.splash_start_time = self.root.tk.call("clock", "milliseconds")
        self.splash_duration = 2500  # 毫秒
        self.splash_particles = []
        self._draw_splash_frame(0)

    def _draw_splash_frame(self, progress):
        """
        绘制开启动画的一帧。
        progress: 0.0 ~ 1.0+
        """
        c = self.splash_canvas
        c.delete("all")

        W, H = 380, 700
        cx, cy = W // 2, H // 2 - 40
        bg = COLORS.get("splash_bg", "#2a2a3d")

        # ── 背景 ──────────────────────────────────
        c.create_rectangle(0, 0, W, H, fill=bg, outline="")

        # ── 吉祥物（果冻弹跳）─────────────────────
        # scale: 从 0 弹到 1，用 elastic_out 缓动
        raw_t = min(progress / 0.6, 1.0)
        scale = self._elastic_out(raw_t)

        # 果冻拉伸：弹跳过程中水平/垂直有微小差异
        jelly_x = 1.0 + 0.15 * math.sin(progress * 12) * max(0, 1 - progress * 1.5)
        jelly_y = 1.0 - 0.10 * math.sin(progress * 12) * max(0, 1 - progress * 1.5)

        r = int(60 * scale)
        if r > 2:
            rx = int(r * jelly_x)
            ry = int(r * jelly_y)
            # 主体圆
            c.create_oval(
                cx - rx, cy - ry, cx + rx, cy + ry,
                fill=COLORS.get("work", "#f38ba8"),
                outline="",
            )
            # 高光（左上偏移的小椭圆）
            hl_r = max(1, int(r * 0.3))
            hl_x = cx - int(r * 0.25)
            hl_y = cy - int(r * 0.25)
            c.create_oval(
                hl_x - hl_r, hl_y - hl_r,
                hl_x + hl_r, hl_y + hl_r,
                fill="#ffffff",
                stipple="gray50",
                outline="",
            )
            # 番茄图标（缩放渐显）
            if scale > 0.5:
                icon_alpha = min(1, (scale - 0.5) * 4)
                font_size = max(1, int(40 * icon_alpha))
                c.create_text(
                    cx, cy,
                    text="🍅",
                    font=("Arial", font_size),
                )

        # ── 扩散环 ────────────────────────────────
        ring_t = max(0, (progress - 0.2) / 0.8)
        if ring_t > 0 and ring_t < 1.2:
            ring_r = int(80 * ring_t)
            ring_alpha = max(0, 1 - ring_t)
            outline_color = COLORS.get("accent", "#cba6f7")
            c.create_oval(
                cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r,
                outline=outline_color,
                width=max(1, int(3 * ring_alpha)),
            )

        # ── 珍珠进度条 ────────────────────────────
        pearl_count = 12
        pearl_r = 5
        spacing = 22
        total_w = (pearl_count - 1) * spacing
        start_x = cx - total_w // 2
        pearl_y = cy + 120

        filled = int(progress * pearl_count)
        for i in range(pearl_count):
            px = start_x + i * spacing
            if i < filled:
                # 已填充：渐变色
                t_color = i / max(1, pearl_count - 1)
                pr = int(243 * (1 - t_color) + 138 * t_color)
                pg = int(139 * (1 - t_color) + 180 * t_color)
                pb = int(168 * (1 - t_color) + 250 * t_color)
                color = f"#{pr:02x}{pg:02x}{pb:02x}"
                c.create_oval(
                    px - pearl_r, pearl_y - pearl_r,
                    px + pearl_r, pearl_y + pearl_r,
                    fill=color, outline="#ffffff", width=1,
                )
                # 珍珠弹入动画
                if i == filled - 1 and progress < 1:
                    bounce = abs(math.sin(progress * 20)) * 3
                    c.create_oval(
                        px - pearl_r, pearl_y - pearl_r - bounce,
                        px + pearl_r, pearl_y + pearl_r - bounce,
                        fill=color, outline="#ffffff", width=1,
                    )
            else:
                # 未填充：半透明
                c.create_oval(
                    px - pearl_r, pearl_y - pearl_r,
                    px + pearl_r, pearl_y + pearl_r,
                    fill=COLORS.get("surface", "#313244"),
                    outline="",
                )

        # ── 装饰粒子（小星星/圆点）─────────────────
        if not self.splash_particles:
            for _ in range(8):
                angle = random.uniform(0, 2 * math.pi)
                dist = random.uniform(100, 200)
                speed = random.uniform(0.3, 1.0)
                size = random.uniform(2, 5)
                self.splash_particles.append((angle, dist, speed, size))

        for angle, dist, speed, size in self.splash_particles:
            p_t = min(1, progress * speed * 1.5)
            if p_t > 0.1:
                px = cx + math.cos(angle) * dist * self._elastic_out(p_t)
                py = cy + math.sin(angle) * dist * self._elastic_out(p_t)
                alpha = max(0, 1 - progress * 1.2)
                if alpha > 0:
                    ps = max(1, int(size * alpha))
                    c.create_oval(
                        px - ps, py - ps, px + ps, py + ps,
                        fill=COLORS.get("accent", "#cba6f7"),
                        outline="",
                    )

        # ── 底部标题文字 ──────────────────────────
        if progress > 0.3:
            text_alpha = min(1, (progress - 0.3) * 2)
            c.create_text(
                cx, pearl_y + 50,
                text="🍅 番茄钟",
                font=("Microsoft YaHei UI", max(1, int(18 * text_alpha)), "bold"),
                fill=COLORS.get("text", "#cdd6f4"),
            )

        # ── 继续动画或结束 ────────────────────────
        if progress < 1.0:
            self.root.after(16, lambda: self._draw_splash_frame(progress + 0.016 / (self.splash_duration / 1000)))
        else:
            # 动画完成，延迟一小段时间后进入主界面
            self.root.after(300, self._splash_to_main)

    @staticmethod
    def _elastic_out(t):
        """弹性缓出函数：模拟果冻弹跳效果。"""
        if t <= 0:
            return 0
        if t >= 1:
            return 1
        return math.pow(2, -10 * t) * math.sin((t * 10 - 0.75) * (2 * math.pi) / 3) + 1

    def _splash_to_main(self):
        """从开启动画过渡到主界面。"""
        if hasattr(self, 'splash_canvas') and self.splash_canvas:
            self.splash_canvas.destroy()
            self.splash_canvas = None

        # 构建主界面
        self._build_ui()
        self._draw_circle()

        # 初始化窗口拖动
        self._drag_data = {"x": 0, "y": 0}
        self._bind_drag(self.root)

    # ============================================================
    #  UI 构建
    # ============================================================

    def _build_ui(self):
        """构建完整界面：内容区域 + 底部导航栏。"""

        # ── Tab 内容容器 ─────────────────────────────
        self.tab_frames = {}
        for name in ("timer", "calendar", "memo"):
            frame = tk.Frame(self.root, bg=COLORS["bg"])
            self.tab_frames[name] = frame

        # 构建番茄钟 Tab 内容
        self._build_timer_tab(self.tab_frames["timer"])
        # 构建日历 Tab（占位）
        self._build_calendar_tab(self.tab_frames["calendar"])
        # 构建备忘录 Tab（占位）
        self._build_memo_tab(self.tab_frames["memo"])

        # 默认显示番茄钟
        self.tab_frames["timer"].pack(fill="both", expand=True)

        # ── 底部导航栏 ──────────────────────────────
        self._build_tab_bar()

    def _build_timer_tab(self, parent):
        """构建番茄钟计时器 Tab 内容。"""

        # ── 顶部栏（标题 + 主题切换）────────────────
        top_frame = tk.Frame(parent, bg=COLORS["bg"])
        top_frame.pack(fill="x", padx=15, pady=(15, 0))

        self.title_label = tk.Label(
            top_frame,
            text="🍅 番茄钟",
            font=("Microsoft YaHei UI", 20, "bold"),
            bg=COLORS["bg"],
            fg=COLORS["text"],
        )
        self.title_label.pack(side="left")

        self.theme_btn = tk.Button(
            top_frame,
            text="🌙" if _current_theme_name == "dark" else "☀",
            font=("Arial", 16),
            bg=COLORS["bg"],
            fg=COLORS["text"],
            activebackground=COLORS["bg"],
            activeforeground=COLORS["text"],
            relief="flat",
            cursor="hand2",
            command=self._toggle_theme,
            bd=0,
        )
        self.theme_btn.pack(side="right")

        # ── 模式标签 ────────────────────────────────
        self.mode_label = tk.Label(
            parent,
            text="专注时间",
            font=("Microsoft YaHei UI", 11),
            bg=COLORS["bg"],
            fg=COLORS["work"],
        )
        self.mode_label.pack()

        # ── 任务标签（当前任务名）────────────────────
        self.task_label = tk.Label(
            parent,
            text="",
            font=("Microsoft YaHei UI", 9),
            bg=COLORS["bg"],
            fg=COLORS["text_dim"],
        )
        self.task_label.pack()

        # ── 画布（圆环进度）─────────────────────────
        self.canvas = tk.Canvas(
            parent,
            width=220, height=220,
            bg=COLORS["bg"],
            highlightthickness=0,
        )
        self.canvas.pack(pady=12)

        # ── 时间数字 ────────────────────────────────
        self.time_label = tk.Label(
            parent,
            text="25:00",
            font=("Consolas", 42, "bold"),
            bg=COLORS["bg"],
            fg=COLORS["text"],
        )
        self.time_label.pack()

        # ── 番茄计数圆点 ────────────────────────────
        self.count_frame = tk.Frame(parent, bg=COLORS["bg"])
        self.count_frame.pack(pady=(8, 0))
        self.count_labels = []
        for i in range(POMODOROS_BEFORE_LONG_BREAK):
            lbl = tk.Label(
                self.count_frame,
                text="○",
                font=("Arial", 14),
                bg=COLORS["bg"],
                fg=COLORS["text_dim"],
            )
            lbl.pack(side="left", padx=5)
            self.count_labels.append(lbl)

        # ── 统计信息行 ──────────────────────────────
        stats = self._get_today_stats()
        self.total_label = tk.Label(
            parent,
            text=f"今日 {stats[0]} 个番茄 · {stats[1]} 分钟",
            font=("Microsoft YaHei UI", 9),
            bg=COLORS["bg"],
            fg=COLORS["text_dim"],
        )
        self.total_label.pack(pady=(5, 10))

        # ── 按钮栏 ──────────────────────────────────
        btn_frame = tk.Frame(parent, bg=COLORS["bg"])
        btn_frame.pack(pady=(0, 8))

        self.start_btn = self._make_button(btn_frame, "▶ 开始", self._on_start_click)
        self.start_btn.pack(side="left", padx=5)

        self.reset_btn = self._make_button(btn_frame, "↺ 重置", self._reset_timer)
        self.reset_btn.pack(side="left", padx=5)

        self.skip_btn = self._make_button(btn_frame, "⏭ 跳过", self._skip_session)
        self.skip_btn.pack(side="left", padx=5)

        # ── 底部工具栏 ──────────────────────────────
        bottom_frame = tk.Frame(parent, bg=COLORS["bg"])
        bottom_frame.pack(pady=(0, 5))

        self.settings_btn = self._make_button(bottom_frame, "⚙ 设置", self._open_settings)
        self.settings_btn.pack(side="left", padx=5)

        self.stats_btn = self._make_button(bottom_frame, "📊 统计", self._open_stats)
        self.stats_btn.pack(side="left", padx=5)

    def _build_calendar_tab(self, parent):
        """构建日历 Tab 内容（第一阶段：基础月历 + 事件列表）。"""
        # ── 顶部标题 ────────────────────────────────
        top = tk.Frame(parent, bg=COLORS["bg"])
        top.pack(fill="x", padx=15, pady=(15, 5))

        tk.Label(
            top, text="📅 重要日子",
            font=("Microsoft YaHei UI", 18, "bold"),
            bg=COLORS["bg"], fg=COLORS["text"],
        ).pack(side="left")

        # ── 月份导航 ────────────────────────────────
        self.cal_year = datetime.now().year
        self.cal_month = datetime.now().month

        nav = tk.Frame(parent, bg=COLORS["bg"])
        nav.pack(fill="x", padx=15, pady=5)

        self.cal_prev_btn = tk.Button(
            nav, text="◀", font=("Arial", 12),
            bg=COLORS["button"], fg=COLORS["text"],
            activebackground=COLORS["button_hover"],
            relief="flat", cursor="hand2", bd=0,
            command=self._cal_prev_month,
        )
        self.cal_prev_btn.pack(side="left")

        self.cal_month_label = tk.Label(
            nav, text="",
            font=("Microsoft YaHei UI", 13, "bold"),
            bg=COLORS["bg"], fg=COLORS["text"],
        )
        self.cal_month_label.pack(side="left", expand=True)

        self.cal_next_btn = tk.Button(
            nav, text="▶", font=("Arial", 12),
            bg=COLORS["button"], fg=COLORS["text"],
            activebackground=COLORS["button_hover"],
            relief="flat", cursor="hand2", bd=0,
            command=self._cal_next_month,
        )
        self.cal_next_btn.pack(side="right")

        # ── 星期标题行 ──────────────────────────────
        week_header = tk.Frame(parent, bg=COLORS["bg"])
        week_header.pack(fill="x", padx=15)
        for d in ["一", "二", "三", "四", "五", "六", "日"]:
            tk.Label(
                week_header, text=d, width=4,
                font=("Microsoft YaHei UI", 9),
                bg=COLORS["bg"], fg=COLORS["text_dim"],
            ).pack(side="left", expand=True)

        # ── 日历格子区域（Canvas）────────────────────
        self.cal_grid = tk.Canvas(
            parent, bg=COLORS["bg"], highlightthickness=0,
        )
        self.cal_grid.pack(fill="x", padx=10, pady=5)

        # ── 事件列表标题 ────────────────────────────
        tk.Label(
            parent, text="近期重要日子",
            font=("Microsoft YaHei UI", 11, "bold"),
            bg=COLORS["bg"], fg=COLORS["text"],
        ).pack(anchor="w", padx=15, pady=(10, 5))

        # ── 事件列表（可滚动区域）────────────────────
        event_outer = tk.Frame(parent, bg=COLORS["surface"], relief="flat")
        event_outer.pack(fill="both", expand=True, padx=15, pady=(0, 5))

        self.cal_event_canvas = tk.Canvas(
            event_outer, bg=COLORS["surface"], highlightthickness=0,
        )
        cal_scrollbar = tk.Scrollbar(
            event_outer, orient="vertical",
            command=self.cal_event_canvas.yview,
        )
        self.cal_event_inner = tk.Frame(self.cal_event_canvas, bg=COLORS["surface"])

        self.cal_event_inner.bind(
            "<Configure>",
            lambda e: self.cal_event_canvas.configure(scrollregion=self.cal_event_canvas.bbox("all")),
        )
        self.cal_event_canvas.create_window((0, 0), window=self.cal_event_inner, anchor="nw")
        self.cal_event_canvas.configure(yscrollcommand=cal_scrollbar.set)

        self.cal_event_canvas.pack(side="left", fill="both", expand=True)
        cal_scrollbar.pack(side="right", fill="y")

        # ── 添加按钮 ────────────────────────────────
        add_btn = tk.Button(
            parent, text="＋ 添加新日子",
            font=("Microsoft YaHei UI", 10, "bold"),
            bg=COLORS["accent"], fg="#ffffff",
            activebackground=COLORS["button_hover"],
            activeforeground="#ffffff",
            relief="flat", padx=16, pady=6,
            cursor="hand2",
            command=self._add_event_dialog,
        )
        add_btn.pack(pady=(0, 10))

        # ── 加载数据 & 绘制 ─────────────────────────
        self.events_data = self._load_events()
        self._cal_refresh()

    def _build_memo_tab(self, parent):
        """构建备忘录 Tab：笔记列表 + 编辑器。"""
        self.notes_data = self._load_notes()

        # ── 列表视图 ────────────────────────────────
        self.memo_list_frame = tk.Frame(parent, bg=COLORS["bg"])

        top = tk.Frame(self.memo_list_frame, bg=COLORS["bg"])
        top.pack(fill="x", padx=15, pady=(15, 5))
        tk.Label(
            top, text="📝 备忘录",
            font=("Microsoft YaHei UI", 18, "bold"),
            bg=COLORS["bg"], fg=COLORS["text"],
        ).pack(side="left")

        # 搜索框
        search_frame = tk.Frame(self.memo_list_frame, bg=COLORS["bg"])
        search_frame.pack(fill="x", padx=15, pady=(0, 8))
        self.memo_search_var = tk.StringVar()
        self.memo_search_var.trace_add("write", lambda *_: self._memo_refresh())
        search_entry = tk.Entry(
            search_frame,
            textvariable=self.memo_search_var,
            font=("Microsoft YaHei UI", 10),
            bg=COLORS["entry_bg"], fg=COLORS["entry_fg"],
            insertbackground=COLORS["entry_fg"],
            relief="flat",
        )
        search_entry.pack(fill="x", ipady=4)
        # 添加搜索图标提示
        search_entry.insert(0, "")
        search_entry.bind("<FocusIn>", lambda e: search_entry.configure(bg=COLORS["entry_bg"]))
        tk.Label(
            search_frame, text="🔍 搜索笔记...",
            font=("Microsoft YaHei UI", 9),
            bg=COLORS["entry_bg"], fg=COLORS["text_dim"],
        ).place(x=8, rely=0.5, anchor="w")

        # 笔记卡片列表（可滚动）
        list_outer = tk.Frame(self.memo_list_frame, bg=COLORS["bg"])
        list_outer.pack(fill="both", expand=True, padx=10, pady=(0, 5))

        self.memo_canvas = tk.Canvas(
            list_outer, bg=COLORS["bg"], highlightthickness=0,
        )
        memo_scrollbar = tk.Scrollbar(
            list_outer, orient="vertical", command=self.memo_canvas.yview,
        )
        self.memo_inner = tk.Frame(self.memo_canvas, bg=COLORS["bg"])
        self.memo_inner.bind(
            "<Configure>",
            lambda e: self.memo_canvas.configure(scrollregion=self.memo_canvas.bbox("all")),
        )
        self.memo_canvas.create_window((0, 0), window=self.memo_inner, anchor="nw")
        self.memo_canvas.configure(yscrollcommand=memo_scrollbar.set)
        self.memo_canvas.pack(side="left", fill="both", expand=True)
        memo_scrollbar.pack(side="right", fill="y")

        # FAB 新建按钮
        fab = tk.Button(
            self.memo_list_frame,
            text="＋",
            font=("Arial", 20, "bold"),
            bg=COLORS["accent"], fg="#ffffff",
            activebackground=COLORS["button_hover"],
            relief="flat", width=3, height=1,
            cursor="hand2",
            command=lambda: self._memo_open_editor(),
        )
        fab.place(relx=0.85, rely=0.92, anchor="center")

        # ── 编辑器视图 ──────────────────────────────
        self.memo_editor_frame = tk.Frame(parent, bg=COLORS["bg"])

        ed_top = tk.Frame(self.memo_editor_frame, bg=COLORS["bg"])
        ed_top.pack(fill="x", padx=10, pady=(10, 5))

        tk.Button(
            ed_top, text="← 返回",
            font=("Microsoft YaHei UI", 10),
            bg=COLORS["button"], fg=COLORS["text"],
            activebackground=COLORS["button_hover"],
            relief="flat", padx=10, pady=4, cursor="hand2",
            command=self._memo_back_to_list,
        ).pack(side="left")

        tk.Button(
            ed_top, text="💾 保存",
            font=("Microsoft YaHei UI", 10),
            bg=COLORS["accent"], fg="#ffffff",
            activebackground=COLORS["button_hover"],
            relief="flat", padx=10, pady=4, cursor="hand2",
            command=self._memo_save_note,
        ).pack(side="right")

        tk.Button(
            ed_top, text="🗑 删除",
            font=("Microsoft YaHei UI", 10),
            bg=COLORS["button"], fg=COLORS["work"],
            activebackground=COLORS["button_hover"],
            relief="flat", padx=10, pady=4, cursor="hand2",
            command=self._memo_delete_current,
        ).pack(side="right", padx=5)

        # 标题输入
        self.memo_title_var = tk.StringVar()
        tk.Entry(
            self.memo_editor_frame,
            textvariable=self.memo_title_var,
            font=("Microsoft YaHei UI", 14, "bold"),
            bg=COLORS["entry_bg"], fg=COLORS["entry_fg"],
            insertbackground=COLORS["entry_fg"],
            relief="flat",
        ).pack(fill="x", padx=15, pady=(5, 8), ipady=4)

        # 内容编辑区
        self.memo_text = tk.Text(
            self.memo_editor_frame,
            font=("Microsoft YaHei UI", 11),
            bg=COLORS["entry_bg"], fg=COLORS["entry_fg"],
            insertbackground=COLORS["entry_fg"],
            relief="flat",
            wrap="word",
            undo=True,
            spacing1=3,
        )
        self.memo_text.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        # 默认显示列表
        self.memo_current_id = None
        self.memo_list_frame.pack(fill="both", expand=True)
        self._memo_refresh()

    # ── 备忘录数据方法 ──────────────────────────────

    def _load_notes(self):
        """加载笔记数据。"""
        return _json_load(NOTES_PATH, [])

    def _save_notes(self):
        """保存笔记数据。"""
        _json_save(NOTES_PATH, self.notes_data)

    def _memo_refresh(self):
        """刷新笔记列表。"""
        for w in self.memo_inner.winfo_children():
            w.destroy()

        query = self.memo_search_var.get().strip().lower() if hasattr(self, 'memo_search_var') else ""

        # 排序：置顶优先，然后按更新时间倒序
        display_notes = sorted(
            self.notes_data,
            key=lambda n: (not n.get("pinned", False), n.get("updated", "")),
            reverse=True,
        )

        # 搜索过滤
        if query:
            display_notes = [
                n for n in display_notes
                if query in n.get("title", "").lower()
                or query in n.get("content", "").lower()
            ]

        if not display_notes:
            tk.Label(
                self.memo_inner,
                text="暂无笔记，点击 ＋ 新建" if not query else "未找到匹配的笔记",
                font=("Microsoft YaHei UI", 11),
                bg=COLORS["bg"], fg=COLORS["text_dim"],
            ).pack(pady=40)
            return

        for note in display_notes:
            self._memo_draw_card(note)

    def _memo_draw_card(self, note):
        """绘制一张笔记卡片。"""
        card = tk.Frame(
            self.memo_inner,
            bg=COLORS["surface"],
            relief="flat",
            padx=10, pady=8,
        )
        card.pack(fill="x", padx=5, pady=3)

        # 置顶图标
        pin_text = "📌 " if note.get("pinned") else ""

        # 标题
        title_text = note.get("title", "无标题")
        tk.Label(
            card,
            text=f"{pin_text}{title_text}",
            font=("Microsoft YaHei UI", 11, "bold"),
            bg=COLORS["surface"], fg=COLORS["text"],
            anchor="w",
        ).pack(anchor="w")

        # 内容预览（前 80 字符）
        content = note.get("content", "")
        preview = content[:80].replace("\n", " ")
        if len(content) > 80:
            preview += "..."
        tk.Label(
            card,
            text=preview,
            font=("Microsoft YaHei UI", 9),
            bg=COLORS["surface"], fg=COLORS["text_dim"],
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        # 底部：时间 + 操作按钮
        bottom = tk.Frame(card, bg=COLORS["surface"])
        bottom.pack(fill="x", pady=(4, 0))

        updated = note.get("updated", "")
        if updated:
            try:
                dt = datetime.strptime(updated, "%Y-%m-%d %H:%M:%S")
                time_text = dt.strftime("%m/%d %H:%M")
            except ValueError:
                time_text = updated[:16]
        else:
            time_text = ""

        tk.Label(
            bottom,
            text=time_text,
            font=("Microsoft YaHei UI", 8),
            bg=COLORS["surface"], fg=COLORS["text_dim"],
        ).pack(side="left")

        # 置顶切换
        pin_btn = tk.Button(
            bottom,
            text="取消置顶" if note.get("pinned") else "置顶",
            font=("Microsoft YaHei UI", 8),
            bg=COLORS["surface"], fg=COLORS["accent"],
            relief="flat", bd=0, cursor="hand2",
            command=lambda nid=note.get("id"): self._memo_toggle_pin(nid),
        )
        pin_btn.pack(side="right")

        # 删除
        del_btn = tk.Button(
            bottom, text="删除",
            font=("Microsoft YaHei UI", 8),
            bg=COLORS["surface"], fg=COLORS["work"],
            relief="flat", bd=0, cursor="hand2",
            command=lambda nid=note.get("id"): self._memo_delete_note(nid),
        )
        del_btn.pack(side="right", padx=5)

        # 点击卡片打开编辑器
        for widget in [card] + card.winfo_children():
            widget.bind("<Button-1>", lambda e, nid=note.get("id"): self._memo_open_editor(nid))
            widget.configure(cursor="hand2")

    def _memo_open_editor(self, note_id=None):
        """打开笔记编辑器。note_id=None 表示新建。"""
        self.memo_current_id = note_id
        note = next((n for n in self.notes_data if n.get("id") == note_id), None) if note_id else None

        self.memo_title_var.set(note.get("title", "") if note else "")
        self.memo_text.delete("1.0", "end")
        if note:
            self.memo_text.insert("1.0", note.get("content", ""))

        self.memo_list_frame.pack_forget()
        self.memo_editor_frame.pack(fill="both", expand=True)

    def _memo_back_to_list(self):
        """返回笔记列表。"""
        self.memo_editor_frame.pack_forget()
        self.memo_list_frame.pack(fill="both", expand=True)
        self.memo_current_id = None
        self._memo_refresh()

    def _memo_save_note(self):
        """保存当前编辑的笔记。"""
        title = self.memo_title_var.get().strip()
        content = self.memo_text.get("1.0", "end").strip()

        if not title and not content:
            return

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if self.memo_current_id:
            # 更新已有笔记
            for note in self.notes_data:
                if note.get("id") == self.memo_current_id:
                    note["title"] = title or "无标题"
                    note["content"] = content
                    note["updated"] = now_str
                    break
        else:
            # 新建笔记
            new_note = {
                "id": str(uuid.uuid4())[:8],
                "title": title or "无标题",
                "content": content,
                "created": now_str,
                "updated": now_str,
                "pinned": False,
            }
            self.notes_data.append(new_note)
            self.memo_current_id = new_note["id"]

        self._save_notes()

    def _memo_delete_current(self):
        """删除当前编辑的笔记。"""
        if self.memo_current_id:
            self._memo_delete_note(self.memo_current_id)
            self._memo_back_to_list()

    def _memo_delete_note(self, note_id):
        """删除指定笔记。"""
        self.notes_data = [n for n in self.notes_data if n.get("id") != note_id]
        self._save_notes()
        if self.memo_current_id == note_id:
            self.memo_current_id = None
        self._memo_refresh()

    def _memo_toggle_pin(self, note_id):
        """切换笔记置顶状态。"""
        for note in self.notes_data:
            if note.get("id") == note_id:
                note["pinned"] = not note.get("pinned", False)
                break
        self._save_notes()
        self._memo_refresh()

    def _build_tab_bar(self):
        """构建底部导航栏。"""
        bar = tk.Frame(self.root, bg=COLORS["surface"], height=50)
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)

        self.tab_buttons = {}
        tabs = [
            ("timer",    "⏱", "番茄钟"),
            ("calendar", "📅", "日历"),
            ("memo",     "📝", "备忘"),
        ]

        for name, icon, label in tabs:
            btn = tk.Button(
                bar,
                text=f"{icon}\n{label}",
                font=("Microsoft YaHei UI", 9),
                bg=COLORS["surface"],
                fg=COLORS["text"],
                activebackground=COLORS["button_hover"],
                activeforeground=COLORS["text"],
                relief="flat", bd=0, cursor="hand2",
                command=lambda n=name: self._switch_tab(n),
            )
            btn.pack(side="left", fill="both", expand=True)
            self.tab_buttons[name] = btn

        self._current_tab = "timer"
        self._highlight_tab("timer")

    def _switch_tab(self, name):
        """切换 Tab。"""
        if name == self._current_tab:
            return
        self.tab_frames[self._current_tab].pack_forget()
        self.tab_frames[name].pack(fill="both", expand=True)
        self._current_tab = name
        self._highlight_tab(name)

    def _highlight_tab(self, active):
        """高亮当前 Tab 按钮。"""
        for name, btn in self.tab_buttons.items():
            if name == active:
                btn.configure(bg=COLORS["button_hover"], fg=COLORS["accent"])
            else:
                btn.configure(bg=COLORS["surface"], fg=COLORS["text"])

    def _make_button(self, parent, text, command):
        """创建统一样式的按钮。"""
        btn = tk.Button(
            parent,
            text=text,
            font=("Microsoft YaHei UI", 10),
            bg=COLORS["button"],
            fg=COLORS["text"],
            activebackground=COLORS["button_hover"],
            activeforeground=COLORS["text"],
            relief="flat",
            padx=14, pady=6,
            cursor="hand2",
            command=command,
        )
        btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=COLORS["button_hover"]))
        btn.bind("<Leave>", lambda e, b=btn: b.configure(bg=COLORS["button"]))
        return btn

    # ============================================================
    #  主题切换
    # ============================================================

    def _toggle_theme(self):
        """切换深色/浅色主题。"""
        new_theme = "light" if _current_theme_name == "dark" else "dark"
        _apply_theme(new_theme)
        self._save_config()
        self._apply_theme_to_widgets()
        self.theme_btn.configure(text="🌙" if new_theme == "dark" else "☀")

    def _apply_theme_to_widgets(self):
        """将当前主题颜色应用到所有已创建的组件。"""
        self.root.configure(bg=COLORS["bg"])
        self.canvas.configure(bg=COLORS["bg"])

        # 更新所有 Label 的颜色
        label_widgets = [
            self.title_label, self.mode_label, self.task_label,
            self.time_label, self.total_label,
        ]
        for lbl in label_widgets:
            lbl.configure(bg=COLORS["bg"])

        self.title_label.configure(fg=COLORS["text"])
        self.time_label.configure(fg=COLORS["text"])
        self.total_label.configure(fg=COLORS["text_dim"])
        self.task_label.configure(fg=COLORS["text_dim"])

        # 更新模式标签颜色
        fg_key, _ = self.MODE_COLORS_KEYS[self.current_mode]
        self.mode_label.configure(fg=COLORS[fg_key])

        # 更新番茄计数圆点
        for i, lbl in enumerate(self.count_labels):
            lbl.configure(bg=COLORS["bg"])
            if i < self.pomodoro_count:
                lbl.configure(fg=COLORS["work"])
            else:
                lbl.configure(fg=COLORS["text_dim"])

        # 更新主题按钮
        self.theme_btn.configure(
            bg=COLORS["bg"],
            activebackground=COLORS["bg"],
        )

        # 更新所有 Frame 背景
        for frame in [self.count_frame, self.root]:
            try:
                frame.configure(bg=COLORS["bg"])
            except Exception:
                pass

        # 更新所有按钮（先 unbind 旧回调避免累积）
        all_buttons = [
            self.start_btn, self.reset_btn, self.skip_btn,
            self.settings_btn, self.stats_btn,
        ]
        for btn in all_buttons:
            btn.configure(
                bg=COLORS["button"],
                fg=COLORS["text"],
                activebackground=COLORS["button_hover"],
                activeforeground=COLORS["text"],
            )
            btn.unbind("<Enter>")
            btn.unbind("<Leave>")
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=COLORS["button_hover"]))
            btn.bind("<Leave>", lambda e, b=btn: b.configure(bg=COLORS["button"]))

        # 重新绑定拖动（新颜色不影响，但确保一致性）
        self._draw_circle()

    # ============================================================
    #  圆环进度绘制
    # ============================================================

    def _draw_circle(self, override_text=None):
        """
        绘制圆环进度条。

        参数 override_text: 如果提供，圆心显示此文字而非 emoji（用于自动开始倒计时）。
        """
        self.canvas.delete("all")

        cx, cy = 110, 110
        r = 105

        fg_key, bg_key = self.MODE_COLORS_KEYS[self.current_mode]
        fg = COLORS[fg_key]
        bg = COLORS[bg_key]

        # 背景圆环
        self.canvas.create_oval(
            cx - r, cy - r, cx + r, cy + r,
            width=10,
            outline=bg,
        )

        # 进度弧
        if self.total_seconds > 0:
            if self.auto_start_counter > 0:
                # 自动开始倒计时：显示满圆
                extent = 360
            else:
                progress = self.remaining_seconds / self.total_seconds
                extent = 360 * progress

            self.canvas.create_arc(
                cx - r, cy - r, cx + r, cy + r,
                start=90,
                extent=-extent,
                width=10,
                outline=fg,
                style="arc",
            )

        # 圆心文字
        if override_text:
            self.canvas.create_text(
                cx, cy,
                text=override_text,
                font=("Microsoft YaHei UI", 36, "bold"),
                fill=COLORS["text"],
            )
        else:
            self.canvas.create_text(
                cx, cy,
                text=self.MODE_EMOJI[self.current_mode],
                font=("Arial", 36),
            )

    # ============================================================
    #  设置对话框
    # ============================================================

    def _open_settings(self):
        """打开设置弹窗。"""
        dlg = tk.Toplevel(self.root)
        dlg.title("⚙ 设置")
        dlg.configure(bg=COLORS["bg"])
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        dlg_w, dlg_h = 320, 360
        sx = self.root.winfo_x() + (380 - dlg_w) // 2
        sy = self.root.winfo_y() + (700 - dlg_h) // 2
        dlg.geometry(f"{dlg_w}x{dlg_h}+{sx}+{sy}")

        tk.Label(
            dlg, text="⚙ 番茄钟设置",
            font=("Microsoft YaHei UI", 14, "bold"),
            bg=COLORS["bg"], fg=COLORS["text"],
        ).pack(pady=(15, 10))

        entries = {}
        fields = [
            ("work_minutes",       "工作时长（分钟）",  WORK_MINUTES),
            ("short_break_minutes", "短休息（分钟）",   SHORT_BREAK_MINUTES),
            ("long_break_minutes",  "长休息（分钟）",   LONG_BREAK_MINUTES),
            ("pomodoros_before_long", "长休息间隔番茄数", POMODOROS_BEFORE_LONG_BREAK),
        ]

        for key, label, default in fields:
            row = tk.Frame(dlg, bg=COLORS["bg"])
            row.pack(fill="x", padx=25, pady=4)
            tk.Label(
                row, text=label, font=("Microsoft YaHei UI", 10),
                bg=COLORS["bg"], fg=COLORS["text"],
            ).pack(side="left")
            var = tk.StringVar(value=str(default))
            ent = tk.Entry(
                row, textvariable=var, width=8,
                font=("Consolas", 11),
                bg=COLORS["entry_bg"], fg=COLORS["entry_fg"],
                insertbackground=COLORS["entry_fg"],
                relief="flat",
            )
            ent.pack(side="right")
            entries[key] = var

        # 自动开始开关
        auto_var = tk.BooleanVar(value=AUTO_START_ENABLED)
        auto_frame = tk.Frame(dlg, bg=COLORS["bg"])
        auto_frame.pack(fill="x", padx=25, pady=8)
        auto_cb = tk.Checkbutton(
            auto_frame,
            text="自动开始下一阶段（3秒倒计时）",
            variable=auto_var,
            font=("Microsoft YaHei UI", 10),
            bg=COLORS["bg"],
            fg=COLORS["text"],
            selectcolor=COLORS["surface"],
            activebackground=COLORS["bg"],
            activeforeground=COLORS["text"],
        )
        auto_cb.pack(side="left")

        # 错误提示
        err_label = tk.Label(
            dlg, text="", font=("Microsoft YaHei UI", 9),
            bg=COLORS["bg"], fg="#f38ba8",
        )
        err_label.pack(pady=2)

        def save_settings():
            global WORK_MINUTES, SHORT_BREAK_MINUTES, LONG_BREAK_MINUTES
            global POMODOROS_BEFORE_LONG_BREAK, AUTO_START_ENABLED

            try:
                wm  = int(entries["work_minutes"].get())
                sbm = int(entries["short_break_minutes"].get())
                lbm = int(entries["long_break_minutes"].get())
                pbl = int(entries["pomodoros_before_long"].get())

                if not (1 <= wm <= 120):
                    raise ValueError("工作时长需在 1~120 分钟")
                if not (1 <= sbm <= 60):
                    raise ValueError("短休息需在 1~60 分钟")
                if not (1 <= lbm <= 60):
                    raise ValueError("长休息需在 1~60 分钟")
                if not (1 <= pbl <= 10):
                    raise ValueError("长休息间隔需在 1~10")
            except ValueError as e:
                err_label.configure(text=str(e) if str(e) else "请输入有效数字")
                return

            WORK_MINUTES             = wm
            SHORT_BREAK_MINUTES      = sbm
            LONG_BREAK_MINUTES       = lbm
            POMODOROS_BEFORE_LONG_BREAK = pbl
            AUTO_START_ENABLED       = auto_var.get()

            # 重建计数圆点
            for lbl in self.count_labels:
                lbl.destroy()
            self.count_labels.clear()
            for i in range(POMODOROS_BEFORE_LONG_BREAK):
                lbl = tk.Label(
                    self.count_frame,
                    text="●" if i < self.pomodoro_count else "○",
                    font=("Arial", 14),
                    bg=COLORS["bg"],
                    fg=COLORS["work"] if i < self.pomodoro_count else COLORS["text_dim"],
                )
                lbl.pack(side="left", padx=5)
                self.count_labels.append(lbl)

            # 重置计时器到工作模式
            self.pomodoro_count = 0
            self._set_mode("work")
            self._save_config()
            dlg.destroy()

        self._make_dialog_button(dlg, "💾 保存", save_settings).pack(pady=(5, 10))

    def _make_dialog_button(self, parent, text, command):
        """对话框内按钮。"""
        btn = tk.Button(
            parent, text=text,
            font=("Microsoft YaHei UI", 10),
            bg=COLORS["button"], fg=COLORS["text"],
            activebackground=COLORS["button_hover"],
            activeforeground=COLORS["text"],
            relief="flat", padx=16, pady=6,
            cursor="hand2", command=command,
        )
        btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=COLORS["button_hover"]))
        btn.bind("<Leave>", lambda e, b=btn: b.configure(bg=COLORS["button"]))
        return btn

    # ============================================================
    #  统计窗口
    # ============================================================

    def _open_stats(self):
        """打开统计弹窗。"""
        dlg = tk.Toplevel(self.root)
        dlg.title("📊 番茄统计")
        dlg.configure(bg=COLORS["bg"])
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        dlg_w, dlg_h = 360, 420
        sx = self.root.winfo_x() + (380 - dlg_w) // 2
        sy = self.root.winfo_y() + (700 - dlg_h) // 2
        dlg.geometry(f"{dlg_w}x{dlg_h}+{sx}+{sy}")

        tk.Label(
            dlg, text="📊 番茄统计",
            font=("Microsoft YaHei UI", 14, "bold"),
            bg=COLORS["bg"], fg=COLORS["text"],
        ).pack(pady=(15, 10))

        # 今日统计
        today_count, today_min = self._get_today_stats()
        total_min = self._get_total_focus_minutes()

        stats_text = (
            f"🍅 今日完成 {today_count} 个番茄\n"
            f"⏱  今日专注 {today_min} 分钟\n"
            f"📈 历史总计 {total_min} 分钟"
        )
        tk.Label(
            dlg, text=stats_text,
            font=("Microsoft YaHei UI", 11),
            bg=COLORS["bg"], fg=COLORS["text"],
            justify="left",
        ).pack(pady=(0, 10), padx=25, anchor="w")

        # 本周柱状图
        tk.Label(
            dlg, text="本周每日番茄数",
            font=("Microsoft YaHei UI", 10, "bold"),
            bg=COLORS["bg"], fg=COLORS["text"],
        ).pack(pady=(5, 5))

        week_data = self._get_week_data()
        chart_w, chart_h = 300, 160
        chart = tk.Canvas(
            dlg, width=chart_w, height=chart_h,
            bg=COLORS["chart_bg"], highlightthickness=0,
        )
        chart.pack(padx=30)

        max_count = max(c for _, c in week_data) if week_data else 0
        if max_count == 0:
            max_count = 1

        bar_count = len(week_data)
        bar_spacing = chart_w / bar_count
        bar_width = bar_spacing * 0.5
        top_margin = 25
        bottom_margin = 30
        chart_area_h = chart_h - top_margin - bottom_margin

        day_names = self.WEEKDAY_NAMES

        for i, (day_str, count) in enumerate(week_data):
            # 计算星期几
            day_date = datetime.strptime(day_str, "%Y-%m-%d")
            dow = day_date.weekday()  # 0=周一

            bar_h = (count / max_count) * chart_area_h if count > 0 else 0
            x_center = bar_spacing * i + bar_spacing / 2
            x0 = x_center - bar_width / 2
            x1 = x_center + bar_width / 2
            y1 = chart_h - bottom_margin
            y0 = y1 - bar_h

            if count > 0:
                chart.create_rectangle(x0, y0, x1, y1, fill=COLORS["chart_bar"], outline="")
                chart.create_text(
                    x_center, y0 - 10,
                    text=str(count),
                    font=("Consolas", 9, "bold"),
                    fill=COLORS["text"],
                )

            # 星期标签
            is_today = (day_str == datetime.now().strftime("%Y-%m-%d"))
            chart.create_text(
                x_center, chart_h - 12,
                text=f"{'·' if is_today else ''}{day_names[dow]}",
                font=("Microsoft YaHei UI", 9),
                fill=COLORS["accent"] if is_today else COLORS["text_dim"],
            )

        # 清除日志按钮
        def clear_log():
            if self.log_data:
                self.log_data.clear()
                self._save_log()
                dlg.destroy()
                self._update_today_stats()

        self._make_dialog_button(dlg, "🗑 清除日志", clear_log).pack(pady=(10, 10))

    # ============================================================
    #  日历 & 事件
    # ============================================================

    def _load_events(self):
        """加载事件数据。"""
        return _json_load(EVENTS_PATH, [])

    def _save_events(self):
        """保存事件数据。"""
        _json_save(EVENTS_PATH, self.events_data)

    def _cal_prev_month(self):
        """切换到上个月。"""
        self.cal_month -= 1
        if self.cal_month < 1:
            self.cal_month = 12
            self.cal_year -= 1
        self._cal_refresh()

    def _cal_next_month(self):
        """切换到下个月。"""
        self.cal_month += 1
        if self.cal_month > 12:
            self.cal_month = 1
            self.cal_year += 1
        self._cal_refresh()

    def _cal_refresh(self):
        """刷新日历网格和事件列表。"""
        self.cal_month_label.configure(
            text=f"{self.cal_year} 年 {self.cal_month} 月"
        )
        self._draw_cal_grid()
        self._refresh_event_list()

    def _draw_cal_grid(self):
        """绘制月历网格。"""
        c = self.cal_grid
        c.delete("all")

        year, month = self.cal_year, self.cal_month
        today = datetime.now()
        first_day = datetime(year, month, 1)
        # weekday(): 0=周一
        start_weekday = first_day.weekday()
        days_in_month = cal_mod.monthrange(year, month)[1]

        cell_w = 48
        cell_h = 36
        total_w = cell_w * 7
        start_x = (360 - total_w) // 2
        start_y = 5

        # 今天的事件日期集合
        event_dates = set()
        for ev in self.events_data:
            try:
                d = datetime.strptime(ev["date"], "%Y-%m-%d")
                if d.year == year and d.month == month:
                    event_dates.add(d.day)
            except (ValueError, KeyError):
                pass

        for day in range(1, days_in_month + 1):
            col = (start_weekday + day - 1) % 7
            row = (start_weekday + day - 1) // 7
            x = start_x + col * cell_w + cell_w // 2
            y = start_y + row * cell_h + cell_h // 2

            is_today = (year == today.year and month == today.month and day == today.day)
            has_event = day in event_dates

            # 今天的高亮圆点
            if is_today:
                c.create_oval(
                    x - 13, y - 13, x + 13, y + 13,
                    fill=COLORS["work"], outline="",
                )
                c.create_text(
                    x, y, text=str(day),
                    font=("Microsoft YaHei UI", 10, "bold"),
                    fill="#ffffff",
                )
            else:
                c.create_text(
                    x, y, text=str(day),
                    font=("Microsoft YaHei UI", 10),
                    fill=COLORS["text"],
                )

            # 有事件的小彩点
            if has_event and not is_today:
                c.create_oval(
                    x + 8, y + 8, x + 12, y + 12,
                    fill=COLORS["accent"], outline="",
                )

        # 设置 canvas 高度
        rows = (start_weekday + days_in_month + 6) // 7
        c.configure(height=start_y + rows * cell_h + 5)

    def _refresh_event_list(self):
        """刷新近期事件列表。"""
        for w in self.cal_event_inner.winfo_children():
            w.destroy()

        today = datetime.now().date()
        upcoming = []
        for ev in self.events_data:
            try:
                ev_date = datetime.strptime(ev["date"], "%Y-%m-%d").date()
                # 如果是每年重复，调整到今年或明年
                if ev.get("repeat_annually"):
                    adjusted = ev_date.replace(year=today.year)
                    if adjusted < today:
                        adjusted = ev_date.replace(year=today.year + 1)
                    ev_date = adjusted
                delta = (ev_date - today).days
                if delta >= -1:  # 包含昨天和未来
                    upcoming.append((ev, ev_date, delta))
            except (ValueError, KeyError):
                pass

        # 按距今天数排序
        upcoming.sort(key=lambda x: x[2])

        if not upcoming:
            tk.Label(
                self.cal_event_inner,
                text="暂无事件，点击下方添加",
                font=("Microsoft YaHei UI", 10),
                bg=COLORS["surface"], fg=COLORS["text_dim"],
            ).pack(pady=20)
            return

        # 只显示今天及未来的事件
        future = [(ev, ev_date, delta) for ev, ev_date, delta in upcoming if delta >= 0]

        for ev, ev_date, delta in future[:10]:  # 最多显示 10 条
            row = tk.Frame(self.cal_event_inner, bg=COLORS["surface"])
            row.pack(fill="x", padx=10, pady=4)

            emoji = self.EVENT_TYPE_EMOJI.get(ev.get("type", "other"), "📌")
            name = ev.get("name", "未命名")

            if delta == 0:
                text = f"{emoji} 今天是 {name}"
                fg = COLORS["work"]
            elif delta == 1:
                text = f"{emoji} 明天是 {name}"
                fg = COLORS["accent"]
            else:
                text = f"{emoji} {delta}天以后是 {name}"
                fg = COLORS["text"]

            tk.Label(
                row,
                text=text,
                font=("Microsoft YaHei UI", 10),
                bg=COLORS["surface"], fg=fg,
                anchor="w",
            ).pack(side="left", fill="x", expand=True)

            # 删除按钮
            tk.Button(
                row, text="✕",
                font=("Arial", 9),
                bg=COLORS["surface"], fg=COLORS["text_dim"],
                relief="flat", bd=0, cursor="hand2",
                command=lambda eid=ev.get("id"): self._delete_event(eid),
            ).pack(side="right", padx=(5, 0))

            # 删除按钮
            del_btn = tk.Button(
                row, text="🗑",
                font=("Arial", 9),
                bg=COLORS["surface"], fg=COLORS["text_dim"],
                relief="flat", bd=0, cursor="hand2",
                command=lambda eid=ev.get("id"): self._delete_event(eid),
            )
            del_btn.pack(side="right")

    def _add_event_dialog(self):
        """弹出添加事件对话框。"""
        dlg = tk.Toplevel(self.root)
        dlg.title("添加重要日子")
        dlg.configure(bg=COLORS["bg"])
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        dlg_w, dlg_h = 320, 380
        sx = self.root.winfo_x() + (380 - dlg_w) // 2
        sy = self.root.winfo_y() + (700 - dlg_h) // 2
        dlg.geometry(f"{dlg_w}x{dlg_h}+{sx}+{sy}")

        tk.Label(
            dlg, text="📅 添加重要日子",
            font=("Microsoft YaHei UI", 14, "bold"),
            bg=COLORS["bg"], fg=COLORS["text"],
        ).pack(pady=(15, 10))

        # 名称
        tk.Label(
            dlg, text="事件名称", font=("Microsoft YaHei UI", 10),
            bg=COLORS["bg"], fg=COLORS["text_dim"],
        ).pack(anchor="w", padx=25)
        name_var = tk.StringVar()
        tk.Entry(
            dlg, textvariable=name_var, width=30,
            font=("Microsoft YaHei UI", 11),
            bg=COLORS["entry_bg"], fg=COLORS["entry_fg"],
            insertbackground=COLORS["entry_fg"], relief="flat",
        ).pack(padx=25, pady=(0, 8), fill="x")

        # 日期
        tk.Label(
            dlg, text="日期（如 2025-06-21）", font=("Microsoft YaHei UI", 10),
            bg=COLORS["bg"], fg=COLORS["text_dim"],
        ).pack(anchor="w", padx=25)
        date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        tk.Entry(
            dlg, textvariable=date_var, width=30,
            font=("Consolas", 11),
            bg=COLORS["entry_bg"], fg=COLORS["entry_fg"],
            insertbackground=COLORS["entry_fg"], relief="flat",
        ).pack(padx=25, pady=(0, 8), fill="x")

        # 类型选择
        tk.Label(
            dlg, text="类型", font=("Microsoft YaHei UI", 10),
            bg=COLORS["bg"], fg=COLORS["text_dim"],
        ).pack(anchor="w", padx=25)
        type_var = tk.StringVar(value="anniversary")
        type_frame = tk.Frame(dlg, bg=COLORS["bg"])
        type_frame.pack(fill="x", padx=25, pady=(0, 8))
        types = [
            ("birthday", "🎂 生日"), ("holiday", "🎄 节日"),
            ("anniversary", "📅 纪念日"), ("exam", "📝 考试"),
            ("travel", "✈️ 旅行"), ("other", "📌 其他"),
        ]
        for val, label in types:
            rb = tk.Radiobutton(
                type_frame, text=label, variable=type_var, value=val,
                font=("Microsoft YaHei UI", 9),
                bg=COLORS["bg"], fg=COLORS["text"],
                selectcolor=COLORS["surface"],
                activebackground=COLORS["bg"],
            )
            rb.pack(anchor="w")

        # 每年重复
        repeat_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            dlg, text="每年提醒我", variable=repeat_var,
            font=("Microsoft YaHei UI", 10),
            bg=COLORS["bg"], fg=COLORS["text"],
            selectcolor=COLORS["surface"],
            activebackground=COLORS["bg"],
        ).pack(anchor="w", padx=25, pady=(0, 5))

        err_label = tk.Label(
            dlg, text="", font=("Microsoft YaHei UI", 9),
            bg=COLORS["bg"], fg="#f38ba8",
        )
        err_label.pack()

        def save_event():
            name = name_var.get().strip()
            if not name:
                err_label.configure(text="请输入事件名称")
                return
            try:
                datetime.strptime(date_var.get().strip(), "%Y-%m-%d")
            except ValueError:
                err_label.configure(text="日期格式错误，请用 YYYY-MM-DD")
                return

            event = {
                "id": str(uuid.uuid4())[:8],
                "name": name,
                "date": date_var.get().strip(),
                "type": type_var.get(),
                "repeat_annually": repeat_var.get(),
            }
            self.events_data.append(event)
            self._save_events()
            self._cal_refresh()
            dlg.destroy()

        self._make_dialog_button(dlg, "💾 保存", save_event).pack(pady=(5, 10))

    def _delete_event(self, event_id):
        """删除指定事件。"""
        self.events_data = [e for e in self.events_data if e.get("id") != event_id]
        self._save_events()
        self._cal_refresh()

    # ============================================================
    #  任务输入对话框
    # ============================================================

    def _ask_task_name(self, callback):
        """
        弹出任务输入框，用户输入后调用 callback(task_name)。
        用户关闭对话框则调用 callback(None)。
        """
        dlg = tk.Toplevel(self.root)
        dlg.title("📝 任务标签")
        dlg.configure(bg=COLORS["bg"])
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        dlg_w, dlg_h = 300, 160
        sx = self.root.winfo_x() + (380 - dlg_w) // 2
        sy = self.root.winfo_y() + (700 - dlg_h) // 2
        dlg.geometry(f"{dlg_w}x{dlg_h}+{sx}+{sy}")

        tk.Label(
            dlg, text="📝 这个番茄要做什么？",
            font=("Microsoft YaHei UI", 12, "bold"),
            bg=COLORS["bg"], fg=COLORS["text"],
        ).pack(pady=(15, 8))

        var = tk.StringVar()
        ent = tk.Entry(
            dlg, textvariable=var, width=30,
            font=("Microsoft YaHei UI", 11),
            bg=COLORS["entry_bg"], fg=COLORS["entry_fg"],
            insertbackground=COLORS["entry_fg"],
            relief="flat",
        )
        ent.pack(pady=5)
        ent.focus_set()

        task_result = None

        def on_ok(event=None):
            nonlocal task_result
            task_result = var.get().strip()
            dlg.destroy()

        def on_skip():
            nonlocal task_result
            task_result = ""
            dlg.destroy()

        def on_close():
            nonlocal task_result
            task_result = None
            dlg.destroy()

        dlg.protocol("WM_DELETE_WINDOW", on_close)
        ent.bind("<Return>", on_ok)

        btn_row = tk.Frame(dlg, bg=COLORS["bg"])
        btn_row.pack(pady=(8, 10))

        ok_btn = self._make_dialog_button(btn_row, "▶ 开始", on_ok)
        ok_btn.pack(side="left", padx=5)

        skip_btn = self._make_dialog_button(btn_row, "⏭ 跳过", on_skip)
        skip_btn.pack(side="left", padx=5)

        self.root.wait_window(dlg)
        callback(task_result)

    # ============================================================
    #  计时核心逻辑
    # ============================================================

    def _on_start_click(self):
        """
        点击开始按钮：弹出任务输入框，确认后启动计时。
        如果是继续（暂停后），直接恢复。
        """
        if self.is_running and self.is_paused:
            self._resume_timer()
            return

        if self.is_running:
            return

        # 弹出任务输入
        self._ask_task_name(self._on_task_confirmed)

    def _on_task_confirmed(self, task_name):
        """任务输入确认后的回调。task_name=None 表示用户关闭了对话框。"""
        if task_name is None:
            return  # 用户关闭了对话框，不启动

        self.current_task = task_name
        if task_name:
            self.task_label.configure(text=f"📋 {task_name}")
        else:
            self.task_label.configure(text="")
        self._start_timer()

    def _start_timer(self):
        """启动计时器。"""
        self.is_running = True
        self.is_paused  = False
        self.tick_count = 0
        self.start_btn.configure(text="⏸ 暂停")
        self._tick()

    def _pause_timer(self):
        """暂停计时。"""
        self.is_paused = True
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
            self.timer_id = None
        self.start_btn.configure(text="▶ 继续")

    def _resume_timer(self):
        """从暂停恢复。"""
        self.is_paused = False
        self.start_btn.configure(text="⏸ 暂停")
        self._tick()

    def _cancel_all_timers(self):
        """取消所有计时器（主计时 + 自动开始），重置运行状态。"""
        self._cancel_auto_start()
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
            self.timer_id = None
        self.is_running = False
        self.is_paused  = False

    def _reset_timer(self):
        """重置计时器。"""
        self._cancel_all_timers()
        self._set_mode(self.current_mode)
        self.start_btn.configure(text="▶ 开始")

    def _skip_session(self):
        """跳过当前阶段。"""
        self._cancel_all_timers()
        self._on_session_complete()

    def _cancel_auto_start(self):
        """取消自动开始倒计时。"""
        if self.auto_start_id:
            self.root.after_cancel(self.auto_start_id)
            self.auto_start_id = None
        self.auto_start_counter = 0

    def _tick(self):
        """
        倒计时核心驱动。每 100ms 调用一次。
        tick_count 累计到 10 = 1 秒。
        """
        if not self.is_running or self.is_paused:
            return

        if self.remaining_seconds <= 0:
            self._on_session_complete()
            return

        self._update_display()
        self.tick_count += 1

        if self.tick_count >= 10:
            self.tick_count = 0
            self.remaining_seconds -= 1

        self.timer_id = self.root.after(100, self._tick)

    def _update_display(self):
        """刷新时间数字和圆环。"""
        minutes = self.remaining_seconds // 60
        seconds = self.remaining_seconds % 60
        self.time_label.configure(text=f"{minutes:02d}:{seconds:02d}")
        self._draw_circle()

    # ============================================================
    #  阶段切换
    # ============================================================

    def _on_session_complete(self):
        """当前阶段结束。"""
        self.is_running = False
        self.start_btn.configure(text="▶ 开始")
        self._play_sound()

        if self.current_mode == "work":
            duration = WORK_MINUTES
            self._log_pomodoro(self.current_task, duration)
            self.pomodoro_count += 1
            self._update_count_display()
            self._update_today_stats()

            if self.pomodoro_count % POMODOROS_BEFORE_LONG_BREAK == 0:
                next_mode = "long_break"
            else:
                next_mode = "short_break"
        else:
            next_mode = "work"

        self._set_mode(next_mode)

        if AUTO_START_ENABLED:
            self._start_auto_start()

    def _set_mode(self, mode):
        """切换模式，重置时间。"""
        self.current_mode = mode
        if mode == "work":
            seconds = WORK_MINUTES * 60
        elif mode == "short_break":
            seconds = SHORT_BREAK_MINUTES * 60
        else:
            seconds = LONG_BREAK_MINUTES * 60
        self.remaining_seconds = seconds
        self.total_seconds     = seconds

        fg_key, _ = self.MODE_COLORS_KEYS[mode]
        self.mode_label.configure(
            text=self.MODE_TEXT[mode],
            fg=COLORS[fg_key],
        )
        self._update_display()

    def _update_count_display(self):
        """更新番茄计数圆点。"""
        for i in range(POMODOROS_BEFORE_LONG_BREAK):
            if i < self.pomodoro_count:
                self.count_labels[i].configure(text="●", fg=COLORS["work"])
            else:
                self.count_labels[i].configure(text="○", fg=COLORS["text_dim"])

    def _update_today_stats(self):
        """刷新今日统计文字。"""
        stats = self._get_today_stats()
        self.total_label.configure(text=f"今日 {stats[0]} 个番茄 · {stats[1]} 分钟")

    # ============================================================
    #  自动开始
    # ============================================================

    def _start_auto_start(self):
        """启动 3 秒自动开始倒计时。"""
        self.auto_start_counter = 3
        self.start_btn.configure(text="⏸ 取消自动开始", state="normal")
        self.is_running = False
        self.is_paused  = False
        # 重写按钮行为：点击取消自动开始
        self.start_btn.configure(command=self._cancel_auto_start_click)
        self._auto_start_tick()

    def _cancel_auto_start_click(self):
        """取消自动开始，回到待机状态。"""
        self._cancel_auto_start()
        self.start_btn.configure(text="▶ 开始", command=self._on_start_click)
        self._draw_circle()

    def _auto_start_tick(self):
        """自动开始倒计时每 100ms 刷新。"""
        if self.auto_start_counter <= 0:
            self._auto_start_go()
            return

        # 显示倒计时数字
        self._draw_circle(override_text=str(self.auto_start_counter))
        self.time_label.configure(text=f"0{self.auto_start_counter}:00")

        self.auto_start_counter -= 1
        self.auto_start_id = self.root.after(1000, self._auto_start_tick)

    def _auto_start_go(self):
        """自动开始倒计时结束，启动计时。"""
        self.auto_start_id = None
        self.auto_start_counter = 0
        self.start_btn.configure(command=self._on_start_click)
        self._start_timer()

    # ============================================================
    #  提示音与窗口闪烁
    # ============================================================

    def _generate_wav(self, filepath):
        """生成正弦波提示音 WAV。"""
        sample_rate = 44100
        amplitude   = 0.6

        notes = [
            (523, 0.25),   # C5
            (659, 0.25),   # E5
            (784, 0.25),   # G5
            (1047, 0.50),  # C6
        ]

        fade_in  = 0.05
        fade_out = 0.10

        samples = []
        for freq, duration in notes:
            num_samples = int(sample_rate * duration)
            for i in range(num_samples):
                t = i / sample_rate
                value = math.sin(2 * math.pi * freq * t)

                t_ratio = i / num_samples
                if t_ratio < fade_in / duration:
                    envelope = t_ratio / (fade_in / duration)
                elif t_ratio > 1 - fade_out / duration:
                    envelope = (1 - t_ratio) / (fade_out / duration)
                else:
                    envelope = 1.0

                samples.append(value * amplitude * envelope)

        with wave.open(filepath, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            pcm = array.array('h', [int(s * 32767) for s in samples])
            wf.writeframes(pcm.tobytes())

    def _play_sound(self):
        """播放提示音并闪烁窗口。"""
        try:
            winsound.PlaySound(self._chime_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception:
            winsound.MessageBeep()
        self._flash_window()

    def _flash_window(self):
        """闪烁任务栏图标提醒用户。"""
        try:
            hwnd = self.root.winfo_id()
            FLASHW_ALL      = 0x03
            FLASHW_TIMERNOFG = 0x0C
            fwi = FLASHWINFO()
            fwi.cbSize    = ctypes.sizeof(FLASHWINFO)
            fwi.hwnd      = hwnd
            fwi.dwFlags   = FLASHW_ALL | FLASHW_TIMERNOFG
            fwi.uCount    = 5
            fwi.dwTimeout = 0
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(fwi))
        except Exception:
            try:
                hwnd = self.root.winfo_id()
                ctypes.windll.user32.FlashWindow(hwnd, True)
            except Exception:
                pass

    # ============================================================
    #  启动主循环
    # ============================================================

    def run(self):
        """进入 tkinter 事件主循环。"""
        self.root.mainloop()


# ============================================================
#  程序入口
# ============================================================

if __name__ == "__main__":
    app = PomodoroTimer()
    app.run()
