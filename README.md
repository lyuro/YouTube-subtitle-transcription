# 🎬 YouTube 视频转录工具

将 YouTube 视频转换为文字和字幕文件 (`.txt` + `.srt`)

提供两种使用方式：
- 🌐 **Google Colab** - 免费云端 GPU 加速，无需本地配置
- 💻 **本地脚本** - 支持 NVIDIA GPU，完全离线运行

底层使用 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)（比原版 openai-whisper 快 2-4 倍，显存更低），内置 VAD 语音检测与反幻听机制。

---

## 🌐 Google Colab 使用

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/lyuro/YouTube-subtitle-transcription/blob/main/YouTube_Transcribe.ipynb)

1. 点击按钮打开 Colab
2. 依次运行单元格
3. 在配置单元格填入 YouTube URL
4. 执行转录，文件自动保存到 Google Drive

> ⚠️ Colab 免费版有使用时长限制，长视频建议使用本地脚本

---

## 💻 本地使用

### 系统要求

- Python 3.10+
- FFmpeg
- NVIDIA GPU (可选，CPU 也可运行但较慢)

### 快速开始

**Windows:**
```powershell
# 1. 克隆仓库
git clone https://github.com/lyuro/YouTube-subtitle-transcription.git
cd YouTube-subtitle-transcription

# 2. 运行安装脚本
.\setup.ps1

# 3. 转录视频
.\run.ps1 "https://youtu.be/xxxxx"
```

**手动安装:**
```bash
# 创建虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 安装依赖
pip install -r requirements.txt

# 安装 PyTorch CUDA 版 (可选，需要 NVIDIA GPU)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

### 命令行使用

```bash
# 基本用法
python transcribe.py "https://youtu.be/xxxxx"

# 指定模型和输出格式
python transcribe.py "https://youtu.be/xxxxx" --model medium --output both

# 指定语言（zh/en/ja 等；auto = 自动检测）
python transcribe.py "https://youtu.be/xxxxx" --language ja
python transcribe.py "https://youtu.be/xxxxx" --language auto

# 保留下载的音频
python transcribe.py "https://youtu.be/xxxxx" --keep-audio

# 使用 cookies (应对 403 错误)
python transcribe.py "https://youtu.be/xxxxx" --cookies cookies.txt
```

### 交互模式

直接运行 `.\run.ps1` 进入交互模式，支持批量输入多个 URL。
支持常见 YouTube 链接格式，包括 `watch?v=...`、`youtu.be/...`、`/shorts/...`、`/live/...`。

### 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `url` | YouTube 视频链接 | (必填) |
| `--model, -m` | Whisper 模型 | `large-v3` |
| `--output, -o` | 输出格式 (txt/srt/both) | `txt` |
| `--language, -l` | 指定语言代码 (zh/en/ja 等)，`auto` 为自动检测 | `zh` |
| `--output-dir, -d` | 输出目录 | 当前目录 |
| `--keep-audio, -k` | 保留音频文件 | 否 |
| `--cookies` | cookies.txt 文件路径 | 自动查找 `./cookies/` |
| `--cookies-from-browser` | 从浏览器读取 cookies | - |
| `--js-runtimes` | 指定 JS 运行时 | 自动检测 |
| `--remote-components` | 远程组件 | - |

---

## 🎛️ Whisper 模型选择

| 模型 | 大小 | 速度 | 准确度 | 推荐场景 |
|------|------|------|--------|----------|
| tiny | 39M | ~32x | ★★☆☆☆ | 快速预览 |
| base | 74M | ~16x | ★★★☆☆ | 简单内容 |
| small | 244M | ~6x | ★★★★☆ | 日常使用 |
| medium | 769M | ~2x | ★★★★☆ | 高质量需求 |
| large-v3 | 1550M | 1x | ★★★★★ | 最佳质量 |

---

## 🍪 处理 403 错误

如果遇到 HTTP 403 错误，可以使用 cookies 绕过：

### 方法 1: 放置 cookies 文件

1. 安装浏览器扩展 [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
2. 登录 YouTube 账号
3. 在 YouTube 页面导出 cookies.txt
4. 将文件放入 `cookies/` 目录 (本地) 或 Google Drive 根目录 (Colab)

### 方法 2: 从浏览器直接读取 (仅本地)

```bash
python transcribe.py "URL" --cookies-from-browser chrome
# 或指定浏览器配置
python transcribe.py "URL" --cookies-from-browser "chrome:Profile 1"
```

---

## 📁 输出文件

```
./
├── 视频标题.txt    # 纯文本
└── 视频标题.srt    # SRT 字幕
```

Colab 版本输出到:
```
Google Drive/
└── YouTubeTranscripts/
    ├── 视频标题.txt
    └── 视频标题.srt
```

---

## 🌐 支持的语言

Whisper 支持 99 种语言，常用代码：
- `zh` - 中文（默认）
- `en` - 英语
- `ja` - 日语
- `ko` - 韩语
- 明确传空字符串可启用自动检测

---

## 🛡️ 反幻听机制

Whisper 遇到长静音 / 纯 BGM / 低 SNR 音频时容易“幻听”出训练语料中的高频话术（如「请不吝点赞订阅」、「明镜与点点栏目」、「感谢观看」等）。本工具集成三重防护：

1. **VAD 预过滤**：Silero VAD 剧除静音 / 纯音乐段，默认宽松配置不丢信息（适合直播 / 讲解类）
2. **解码参数**：`condition_on_previous_text=False` + `compression_ratio_threshold=2.2` + `hallucination_silence_threshold=2.0`，阐断重复链
3. **实时监控 + Fallback**：流式检测连续重复 / 滑动窗口 unique 占比 / 黑名单词命中；触发后自动以激进参数（greedy + 收紧 VAD）重试一次，仍失败则跳过该视频

中断阈值（可在 `transcribe.py` 中调整 `HallucinationMonitor` 入参）：

| 项 | 阈值 | 说明 |
|---|---|---|
| 连续相同 segment | 10 | 防止误伤正常重复句 |
| 滑动窗口时长 | 5 分钟 | 一段足够长的取样 |
| Unique 占比下限 | 20% | 低于此值判为崩溃 |
| 黑名单命中上限 | 10 次/窗 | 阈值内触发中断 |

---

## ⚠️ 注意事项

1. 首次运行需要下载 Whisper 模型 (large-v3 约 3GB)
2. GPU 显存建议 8GB+ (large-v3 模型)
3. 部分视频可能因版权限制无法下载
4. Colab 免费版有 GPU 使用时长限制

---

## 📄 License

MIT License
