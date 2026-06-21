"""
番茄钟 - Pomodoro Timer
一个简洁美观的桌面番茄钟软件

核心原理：
  番茄工作法把时间分为「工作 → 短休息」循环，每完成 4 个番茄后插入一次「长休息」。
  本程序用 tkinter 画圆环进度 + 倒计时，用 after() 驱动每秒刷新。

文件扩展名说明：
  .pyw 是 Windows 专用扩展名，双击时用 pythonw.exe 运行（不弹黑色命令行窗口）。
"""

# ============================================================
#  导入模块
# ============================================================

import tkinter as tk            # Python 标准 GUI 库，本程序唯一的界面依赖
import math                     # 数学函数（正弦波生成用到）
import os                       # 操作系统功能
import array                    # 高效数组：批量将浮点转为 16-bit PCM（比 struct.pack 循环快）
import wave                     # WAV 文件格式处理
import winsound                 # Windows 专用：播放 WAV 文件
import ctypes                   # 调用 Windows API，处理高 DPI 适配 & 窗口闪烁
import tempfile                 # 临时文件目录

# 高 DPI 适配：告诉 Windows 本程序自己处理缩放，避免界面模糊或被裁剪
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass


# ============================================================
#  全局配置常量（可按需修改）
# ============================================================

WORK_MINUTES             = 25   # 一次工作番茄的时长（分钟）
SHORT_BREAK_MINUTES      = 5    # 短休息时长（分钟）
LONG_BREAK_MINUTES       = 15   # 长休息时长（分钟）
POMODOROS_BEFORE_LONG_BREAK = 4 # 每完成几个番茄后进入长休息


# ============================================================
#  颜色主题（Catppuccin Mocha 风格暗色主题）
# ============================================================
# 格式：十六进制颜色码 #RRGGBB
# 这些颜色贯穿整个界面，统一视觉风格。

COLORS = {
    # ── 背景与表面 ──────────────────────────────────────
    "bg":              "#1e1e2e",   # 窗口背景：深蓝黑
    "surface":         "#313244",   # 卡片/面板背景：略浅

    # ── 文字 ────────────────────────────────────────────
    "text":            "#cdd6f4",   # 主文字：乳白色
    "text_dim":        "#6c7086",   # 次要文字：灰色，用于计数未激活状态

    # ── 工作模式颜色 ───────────────────────────────────
    "work":            "#f38ba8",   # 工作模式主题色：粉色（番茄红）
    "work_bg":         "#45273a",   # 工作模式圆环背景：深粉

    # ── 短休息模式颜色 ─────────────────────────────────
    "short_break":     "#a6e3a1",   # 短休息主题色：绿色
    "short_break_bg":  "#2d3a2d",   # 短休息圆环背景：深绿

    # ── 长休息模式颜色 ─────────────────────────────────
    "long_break":      "#89b4fa",   # 长休息主题色：蓝色
    "long_break_bg":   "#273045",   # 长休息圆环背景：深蓝

    # ── 通用元素 ───────────────────────────────────────
    "accent":          "#cba6f7",   # 强调色（紫）
    "button":          "#45475a",   # 按钮背景：深灰
    "button_hover":    "#585b70",   # 按钮悬停高亮：略浅
}


class PomodoroTimer:
    """
    番茄钟主类，封装了全部界面和逻辑。

    状态机（运行流程）：

        ┌─────────────────────────────────────────────┐
        │                  ┌──────────┐               │
        │    ┌────────────▶│  work    │◀────────┐     │
        │    │             └────┬─────┘         │     │
        │    │                  │ 25min 完成     │     │
        │    │        ┌─────────▼──────────┐    │     │
        │    │        │ 不是第4个番茄？     │    │     │
        │    │        │ 是 → long_break     │    │     │
        │    │        │ 否 → short_break    │    │     │
        │    │        └─────────┬──────────┘    │     │
        │    │      short 5min  │  long 15min   │     │
        │    │      ┌───────────┘  └───────────┘│     │
        │    │      ▼                           ▼     │
        │    │   ┌──────────┐              ┌────────┐ │
        │    └───│ 休息完成  │              │长休完成│ │
        │        └──────────┘              └────────┘ │
        └─────────────────────────────────────────────┘
    """

    def __init__(self):
        # ── 1. 创建主窗口 ─────────────────────────────
        self.root = tk.Tk()
        self.root.title("🍅 番茄钟")          # 标题栏文字
        self.root.configure(bg=COLORS["bg"])   # 窗口背景色
        self.root.resizable(False, False)      # 禁止缩放，保持固定尺寸
        self.root.attributes("-topmost", True) # 始终置顶（方便边工作边看）

        # ── 2. 窗口尺寸 & 居中显示 ───────────────────
        win_w, win_h = 380, 560  # 窗口宽、高（像素）
        screen_w = self.root.winfo_screenwidth()   # 屏幕宽度
        screen_h = self.root.winfo_screenheight()   # 屏幕高度
        # 居中公式：(屏幕尺寸 - 窗口尺寸) / 2
        x = (screen_w - win_w) // 2
        y = (screen_h - win_h) // 2
        self.root.geometry(f"{win_w}x{win_h}+{x}+{y}")

        # ── 3. 初始化状态变量 ─────────────────────────
        #   is_running    : 计时器是否在运行（计时中或暂停中）
        #   is_paused     : 计时器是否处于暂停状态
        #   remaining     : 当前模式剩余秒数
        #   total_seconds : 当前模式总秒数（计算进度百分比用）
        #   current_mode  : 当前处于哪个阶段
        #   pomodoro_count: 本轮周期已完成的番茄数（用于控制长休息间隔）
        #   session_count : 累计完成的番茄总数
        #   timer_id      : after() 返回的 ID，用于取消定时回调
        self.is_running     = False
        self.is_paused      = False
        self.remaining_seconds = WORK_MINUTES * 60   # 初始：25 分钟
        self.total_seconds  = WORK_MINUTES * 60
        self.current_mode   = "work"     # work / short_break / long_break
        self.pomodoro_count = 0          # 本轮周期计数（0~3，到 4 时触发长休息）
        self.session_count  = 0          # 总完成番茄数
        self.timer_id       = None

        # ── 4. 缓存提示音 WAV（只生成一次，之后直接播放）───
        self._chime_path = os.path.join(tempfile.gettempdir(), "pomodoro_chime.wav")
        self._generate_wav(self._chime_path)

        # ── 5. 构建界面 & 绘制初始状态 ────────────────
        self._build_ui()
        self._draw_circle()  # 画一个满圆（还没开始倒计时）

    # ========================================================
    #  UI 构建
    # ========================================================

    def _build_ui(self):
        """
        构建整个界面，从上到下依次：
          标题 → 模式标签 → 圆环画布 → 时间数字 → 番茄计数 → 总计数 → 按钮栏
        """

        # ── 标题 ─────────────────────────────────────
        self.title_label = tk.Label(
            self.root,
            text="🍅 番茄钟",
            font=("Microsoft YaHei UI", 20, "bold"),  # 微软雅黑加粗 20pt
            bg=COLORS["bg"],
            fg=COLORS["text"],
        )
        self.title_label.pack(pady=(20, 5))  # pack 布局：从上往下堆叠，上下留白

        # ── 模式标签（"专注时间" / "短休息" / "长休息"）──
        self.mode_label = tk.Label(
            self.root,
            text="专注时间",
            font=("Microsoft YaHei UI", 11),
            bg=COLORS["bg"],
            fg=COLORS["work"],  # 初始为工作模式粉色
        )
        self.mode_label.pack()

        # ── 画布（绘制圆环进度）─────────────────────
        #   Canvas 是 tkinter 的矢量画布，可以在上面画线、圆、弧、文字等。
        #   220x220 像素，highlightthickness=0 去掉默认的焦点高亮边框。
        self.canvas = tk.Canvas(
            self.root,
            width=220, height=220,
            bg=COLORS["bg"],
            highlightthickness=0,
        )
        self.canvas.pack(pady=15)

        # ── 时间数字 ─────────────────────────────────
        self.time_label = tk.Label(
            self.root,
            text="25:00",   # 初始显示 25 分钟
            font=("Consolas", 42, "bold"),  # 等宽字体，数字不会跳动
            bg=COLORS["bg"],
            fg=COLORS["text"],
        )
        self.time_label.pack()

        # ── 番茄计数圆点（○ = 未完成，● = 已完成）────
        self.count_frame = tk.Frame(self.root, bg=COLORS["bg"])
        self.count_frame.pack(pady=(8, 0))
        self.count_labels = []
        for i in range(POMODOROS_BEFORE_LONG_BREAK):
            lbl = tk.Label(
                self.count_frame,
                text="○",            # 空心圆：未完成
                font=("Arial", 14),  # Arial 的圆圈符号比较好看
                bg=COLORS["bg"],
                fg=COLORS["text_dim"],
            )
            lbl.pack(side="left", padx=5)  # 水平排列
            self.count_labels.append(lbl)

        # ── 总番茄数 ─────────────────────────────────
        self.total_label = tk.Label(
            self.root,
            text="已完成 0 个番茄",
            font=("Microsoft YaHei UI", 9),
            bg=COLORS["bg"],
            fg=COLORS["text_dim"],
        )
        self.total_label.pack(pady=(5, 10))

        # ── 按钮栏 ───────────────────────────────────
        btn_frame = tk.Frame(self.root, bg=COLORS["bg"])
        btn_frame.pack(pady=(0, 15))

        self.start_btn = self._make_button(btn_frame, "▶ 开始", self._toggle_timer)
        self.start_btn.pack(side="left", padx=6)

        self.reset_btn = self._make_button(btn_frame, "↺ 重置", self._reset_timer)
        self.reset_btn.pack(side="left", padx=6)

        self.skip_btn  = self._make_button(btn_frame, "⏭ 跳过", self._skip_session)
        self.skip_btn.pack(side="left", padx=6)

    def _make_button(self, parent, text, command):
        """
        创建一个统一样式的按钮。
        同时绑定鼠标悬停（Enter/Leave）事件，实现 hover 高亮效果。
        """
        btn = tk.Button(
            parent,
            text=text,
            font=("Microsoft YaHei UI", 10),
            bg=COLORS["button"],               # 默认背景
            fg=COLORS["text"],                 # 文字颜色
            activebackground=COLORS["button_hover"],  # 按下时的背景
            activeforeground=COLORS["text"],
            relief="flat",        # 扁平风格，去掉立体边框
            padx=14, pady=6,
            cursor="hand2",       # 鼠标悬停时显示手形光标
            command=command,
        )
        # 绑定鼠标进入/离开事件，动态切换背景色实现 hover 效果
        btn.bind("<Enter>", lambda e: btn.configure(bg=COLORS["button_hover"]))
        btn.bind("<Leave>", lambda e: btn.configure(bg=COLORS["button"]))
        return btn

    # ========================================================
    #  类级常量（所有实例共享，不会改变，避免重复创建字典）
    # ========================================================

    # 各模式的 (前景色, 背景色) —— 每秒绘制圆环时直接查表，无需重建字典
    MODE_COLORS = {
        "work":        (COLORS["work"],        COLORS["work_bg"]),
        "short_break": (COLORS["short_break"], COLORS["short_break_bg"]),
        "long_break":  (COLORS["long_break"],  COLORS["long_break_bg"]),
    }

    # 各模式对应的总秒数、中文文字、主题色 —— _set_mode() 直接查表
    MODE_DURATIONS = {
        "work":        WORK_MINUTES * 60,          # 25 min = 1500 s
        "short_break": SHORT_BREAK_MINUTES * 60,   #  5 min =  300 s
        "long_break":  LONG_BREAK_MINUTES * 60,    # 15 min =  900 s
    }
    MODE_TEXT  = {"work": "专注时间", "short_break": "短休息", "long_break": "长休息"}
    MODE_EMOJI = {"work": "🍅",     "short_break": "☕",      "long_break": "🌙"}

    # ========================================================
    #  圆环进度绘制
    # ========================================================

    def _draw_circle(self):
        """
        在画布上绘制圆环进度条。

        绘制逻辑：
          1. 先画一个完整的「背景圆环」（表示总时间）
          2. 再画一个「进度弧」（表示剩余时间占比）
          3. 最后在圆心画 emoji 图标

        数学说明：
          tkinter 的 create_arc 的 start 角度：
            0° = 三点钟方向（正右）
           90° = 十二点钟方向（正上）  ← 我们从这里开始
          extent 是顺时针扫过的角度（负值 = 逆时针，这里用负值让弧从12点方向顺时针延伸）

          进度 = remaining / total
          弧度 = 360 × 进度
        """
        self.canvas.delete("all")  # 清空画布（每次重绘）

        cx, cy = 110, 110  # 圆心坐标（画布 220×220 的中心）
        r      = 105       # 圆的半径

        fg, bg = self.MODE_COLORS[self.current_mode]  # 查类级常量表，无需重建字典

        # 1. 背景圆环（full circle，width=10 是线条粗细）
        self.canvas.create_oval(
            cx - r, cy - r, cx + r, cy + r,   # 外接矩形的左上角和右下角
            width=10,
            outline=bg,                        # 用深色画背景环
        )

        # 2. 进度弧（只剩剩余比例的长度）
        if self.total_seconds > 0:
            progress = self.remaining_seconds / self.total_seconds  # 0.0 ~ 1.0
            extent   = 360 * progress                               # 扫过的角度

            self.canvas.create_arc(
                cx - r, cy - r, cx + r, cy + r,
                start=90,          # 从12点钟方向开始
                extent=-extent,    # 负值 = 顺时针（tkinter 默认逆时针）
                width=10,
                outline=fg,        # 前景色（粉/绿/蓝）
                style="arc",       # 只画弧线，不填充扇形
            )

        # 3. 圆心 emoji（不同模式显示不同图标，查类级常量表）
        self.canvas.create_text(
            cx, cy,
            text=self.MODE_EMOJI[self.current_mode],
            font=("Arial", 36),
        )

    # ========================================================
    #  计时核心逻辑
    # ========================================================

    def _toggle_timer(self):
        """
        开始/暂停/继续 的切换逻辑：
          - 未运行 → 启动
          - 运行中未暂停 → 暂停
          - 已暂停 → 继续
        """
        if not self.is_running:
            self._start_timer()      # 首次启动
        elif self.is_paused:
            self._resume_timer()     # 从暂停恢复
        else:
            self._pause_timer()      # 运行中，按下暂停

    def _start_timer(self):
        """启动计时器，调用 _tick() 开始第一秒倒计时。"""
        self.is_running = True
        self.is_paused  = False
        self.start_btn.configure(text="⏸ 暂停")  # 按钮文字切换
        self._tick()  # 触发第一次倒计时

    def _pause_timer(self):
        """暂停计时：取消下一次 after 回调，保持 remaining_seconds 不变。"""
        self.is_paused = True
        if self.timer_id:
            self.root.after_cancel(self.timer_id)  # 取消已安排的定时回调
            self.timer_id = None
        self.start_btn.configure(text="▶ 继续")

    def _resume_timer(self):
        """从暂停恢复：重新启动倒计时循环。"""
        self.is_paused = False
        self.start_btn.configure(text="⏸ 暂停")
        self._tick()

    def _reset_timer(self):
        """重置计时器到当前模式的起始状态。"""
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
            self.timer_id = None
        self.is_running = False
        self.is_paused  = False
        self._set_mode(self.current_mode)  # 重置剩余秒数和显示
        self.start_btn.configure(text="▶ 开始")

    def _skip_session(self):
        """跳过当前阶段，直接进入下一个阶段（不播放提示音）。"""
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
            self.timer_id = None
        self.is_running = False
        self.is_paused  = False
        self._on_session_complete()  # 触发阶段完成逻辑

    def _tick(self):
        """
        倒计时的核心驱动函数。

        工作原理：
          1. 检查是否在运行 & 未暂停，否则退出
          2. 如果剩余秒数 ≤ 0，触发阶段完成
          3. 更新显示，remaining_seconds -= 1
          4. 用 self.root.after(1000, self._tick) 安排 1 秒后再次调用自身

        after() 是 tkinter 的定时器：
          - 参数：延迟毫秒数 + 回调函数
          - 返回一个 ID，可用 after_cancel() 取消
          - 每秒调用一次 _tick，形成稳定的 1 秒间隔循环
        """
        if not self.is_running or self.is_paused:
            return  # 停止循环

        if self.remaining_seconds <= 0:
            self._on_session_complete()  # 时间到，处理阶段切换
            return

        self._update_display()            # 刷新时间文字 + 圆环
        self.remaining_seconds -= 1       # 剩余秒数减 1
        self.timer_id = self.root.after(1000, self._tick)  # 1 秒后再来一次

    def _update_display(self):
        """刷新时间数字和圆环进度。"""
        minutes = self.remaining_seconds // 60
        seconds = self.remaining_seconds % 60
        self.time_label.configure(text=f"{minutes:02d}:{seconds:02d}")
        self._draw_circle()

    # ========================================================
    #  阶段切换
    # ========================================================

    def _on_session_complete(self):
        """
        当前阶段结束时调用。

        工作完成后：
          - pomodoro_count += 1（本轮计数）
          - session_count  += 1（总数）
          - 如果本轮计数到 4 → 长休息，否则短休息

        休息完成后：
          - 直接进入工作模式
        """
        self.is_running = False
        self.start_btn.configure(text="▶ 开始")

        # 播放提示音
        self._play_sound()

        if self.current_mode == "work":
            # 工作阶段结束 → 更新计数，决定休息类型
            self.pomodoro_count += 1   # 本轮周期番茄数 +1
            self.session_count  += 1   # 总番茄数 +1
            self._update_count_display()

            if self.pomodoro_count % POMODOROS_BEFORE_LONG_BREAK == 0:
                # 每 4 个番茄后进入长休息
                self._set_mode("long_break")
            else:
                # 否则进入短休息
                self._set_mode("short_break")
        else:
            # 休息阶段结束 → 回到工作模式
            self._set_mode("work")

    def _set_mode(self, mode):
        """
        切换计时器模式，重置对应的总时间/剩余时间，并更新显示文字。

        参数 mode 只能是 "work" / "short_break" / "long_break"。
        所有映射都查类级常量，不重建字典。
        """
        self.current_mode = mode
        self.remaining_seconds = self.MODE_DURATIONS[mode]
        self.total_seconds     = self.MODE_DURATIONS[mode]

        self.mode_label.configure(
            text=self.MODE_TEXT[mode],
            fg=self.MODE_COLORS[mode][0],  # [0] = 前景色
        )
        self._update_display()

    def _update_count_display(self):
        """
        更新番茄计数圆点和总数文字。

        逻辑：
          - 前 session_count 个圆点显示为 ●（实心，粉色）
          - 其余显示为 ○（空心，灰色）
          - session_count 已经在 _on_session_complete 里加过 1 了
        """
        for i in range(POMODOROS_BEFORE_LONG_BREAK):
            if i < self.session_count:
                # 已完成：实心圆，粉色
                self.count_labels[i].configure(text="●", fg=COLORS["work"])
            else:
                # 未完成：空心圆，灰色
                self.count_labels[i].configure(text="○", fg=COLORS["text_dim"])

        self.total_label.configure(text=f"已完成 {self.pomodoro_count} 个番茄")

    # ========================================================
    #  提示音与窗口闪烁
    # ========================================================

    def _generate_wav(self, filepath):
        """
        用纯 Python 生成一段轻灵的正弦波旋律 WAV 文件。

        正弦波 vs 方波：
          winsound.Beep 生成的是方波（声音硬、刺耳）。
          正弦波是最柔和的波形，加上淡入淡出包络后听起来像风铃。

        包络（Envelope）：
          每个音符不是突然开始和结束的，而是：
            淡入(50ms) → 保持 → 淡出(100ms)
          这样音符之间过渡自然，不会出现"哒哒"的断点。
        """
        sample_rate = 44100    # CD 音质采样率
        amplitude   = 0.6      # 音量 0~1，0.6 比较舒适不刺耳

        # ── 旋律：每个音符 (频率Hz, 时长秒) ───────────
        # 模拟水滴落入水面的晶莹感，用五声音阶上行
        notes = [
            (523, 0.25),   # C5
            (659, 0.25),   # E5
            (784, 0.25),   # G5
            (1047, 0.50),  # C6（高音，时长更久，收尾）
        ]

        fade_in  = 0.05   # 淡入 50ms
        fade_out = 0.10   # 淡出 100ms

        samples = []
        for freq, duration in notes:
            num_samples = int(sample_rate * duration)
            for i in range(num_samples):
                t = i / sample_rate  # 当前时间点（秒）

                # 正弦波：sin(2π × 频率 × 时间)
                value = math.sin(2 * math.pi * freq * t)

                # 包络：淡入淡出，让声音柔和过渡
                t_ratio = i / num_samples  # 0.0 ~ 1.0
                if t_ratio < fade_in / duration:
                    # 淡入阶段：音量从 0 线性增长到 1
                    envelope = t_ratio / (fade_in / duration)
                elif t_ratio > 1 - fade_out / duration:
                    # 淡出阶段：音量从 1 线性衰减到 0
                    envelope = (1 - t_ratio) / (fade_out / duration)
                else:
                    # 保持阶段：满音量
                    envelope = 1.0

                sample = value * amplitude * envelope
                samples.append(sample)

        # ── 写入 WAV 文件 ─────────────────────────────
        # WAV 格式：16-bit PCM，单声道
        # array.array 在 C 层批量转换，比 struct.pack 循环快一个数量级
        with wave.open(filepath, 'w') as wf:
            wf.setnchannels(1)           # 单声道
            wf.setsampwidth(2)           # 每个采样 2 字节（16-bit）
            wf.setframerate(sample_rate) # 采样率
            pcm = array.array('h', [int(s * 32767) for s in samples])
            wf.writeframes(pcm.tobytes())

    def _play_sound(self):
        """
        播放已缓存的提示音 WAV（__init__ 时只生成一次）。

        用 SND_ASYNC 异步播放，不阻塞 UI 线程。
        如果缓存文件丢失（极少见），静默降级为系统提示音。
        """
        try:
            winsound.PlaySound(self._chime_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception:
            winsound.MessageBeep()
        self._flash_window()

    def _flash_window(self):
        """
        调用 Windows API 闪烁任务栏图标，提醒用户注意。

        用 self.root.winfo_id() 获取本窗口的 HWND，
        而非 GetForegroundWindow()（可能闪错窗口）。
        """
        try:
            hwnd = self.root.winfo_id()  # 本窗口句柄，始终正确
            ctypes.windll.user32.FlashWindow(hwnd, True)
        except Exception:
            pass  # 非 Windows 系统或权限不足时静默失败

    # ========================================================
    #  启动主循环
    # ========================================================

    def run(self):
        """
        进入 tkinter 事件主循环。

        mainloop() 是所有 tkinter 程序必须调用的函数：
          - 它会持续监听用户操作（鼠标点击、键盘输入等）
          - 同时执行所有通过 after() 安排的定时任务
          - 只有关闭窗口时才会退出
        """
        self.root.mainloop()


# ============================================================
#  程序入口
# ============================================================

if __name__ == "__main__":
    # 创建 PomodoroTimer 实例并启动
    # 当直接运行本文件时执行（被 import 时不执行）
    app = PomodoroTimer()
    app.run()
