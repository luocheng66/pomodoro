# 番茄钟 (Pomodoro Timer)

桌面番茄钟 + 日历 + 备忘录一体化效率工具，使用 Python + tkinter。

## 项目结构

```
pomodoro.pyw              # 主程序（.pyw = Windows 无黑窗运行）
~/.pomodoro_config.json   # 运行时生成：用户配置
~/.pomodoro_log.json      # 运行时生成：番茄日志
~/.pomodoro_events.json   # 运行时生成：日历事件
~/.pomodoro_notes.json    # 运行时生成：备忘录笔记
```

## 运行

```bash
pythonw pomodoro.pyw      # 无黑窗（推荐）
python  pomodoro.pyw      # 有黑窗，可看报错
```

## 功能

### 开启动画
- 果冻吉祥物弹跳入场（elastic_out 缓动）+ 珍珠进度条 + 装饰粒子

### 番茄钟（⏱ Tab）
- 25 分钟工作 → 5 分钟短休息 → 每 4 个番茄后 15 分钟长休息
- 圆环进度条 + 深色/浅色主题切换（Catppuccin Mocha / Latte）
- 100ms 刷新率丝滑圆环动画
- 自定义时长设置（弹窗对话框，持久化到 JSON）
- 任务标签（开始前填写本次专注内容）
- 番茄日志持久化 & 统计视图（柱状图）
- 自动开始下一阶段（可选 3 秒倒计时）
- 窗口可拖动

### 日历（📅 Tab）
- 月视图日历格，今天高亮，有事件的日期显示彩点
- 事件类型：🎂生日 / 🎄节日 / 📅纪念日 / 📝考试 / ✈️旅行
- 每年重复提醒
- 近期重要日子列表 + 倒计时胶囊
- 添加/删除事件

### 备忘录（📝 Tab）
- 笔记卡片列表（标题 + 内容预览 + 更新时间）
- 笔记编辑器（标题 + 正文 Text 区域 + 撤销）
- 搜索过滤（实时匹配标题和内容）
- 置顶/取消置顶
- 新建/编辑/删除笔记

## 技术栈

- Python 3.12+, tkinter（零外部依赖）
- Windows API: winsound, ctypes (DPI 适配 + 窗口闪烁)
- Git 推送到 GitHub: `luocheng66/pomodoro`
