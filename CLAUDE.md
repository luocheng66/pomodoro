# 番茄钟 (Pomodoro Timer)

桌面番茄钟软件，使用 Python + tkinter。

## 项目结构

```
pomodoro.pyw    # 主程序（.pyw = Windows 无黑窗运行）
```

## 运行

```bash
pythonw pomodoro.pyw      # 无黑窗（推荐）
python  pomodoro.pyw      # 有黑窗，可看报错
```

## 功能

- 25 分钟工作 → 5 分钟短休息 → 每 4 个番茄后 15 分钟长休息
- 圆环进度条 + 深色主题（Catppuccin Mocha）
- 正弦波合成提示音（启动时生成 WAV，缓存播放）
- 窗口置顶

## 技术栈

- Python 3.12+, tkinter
- Windows API: winsound, ctypes (DPI 适配 + 窗口闪烁)
- Git 推送到 GitHub: `luocheng66/pomodoro`
