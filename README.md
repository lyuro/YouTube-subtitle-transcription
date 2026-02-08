# 🎬 YouTube 视频转录工具

将 YouTube 视频转换为文字和字幕文件 (`.txt` + `.srt`)

提供两种使用方式：
- 🌐 **Google Colab** - 免费云端 GPU 加速，无需本地配置
- 💻 **本地脚本** - 支持 NVIDIA GPU，完全离线运行

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

# 指定语言
python transcribe.py "https://youtu.be/xxxxx" --language zh

# 保留下载的音频
python transcribe.py "https://youtu.be/xxxxx" --keep-audio

# 使用 cookies (应对 403 错误)
python transcribe.py "https://youtu.be/xxxxx" --cookies cookies.txt
```

### 交互模式

直接运行 `.\run.ps1` 进入交互模式，支持批量输入多个 URL。

### 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `url` | YouTube 视频链接 | (必填) |
| `--model, -m` | Whisper 模型 | `large-v3` |
| `--output, -o` | 输出格式 (txt/srt/both) | `txt` |
| `--language, -l` | 指定语言代码 | 自动检测 |
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
- `zh` - 中文
- `en` - 英语
- `ja` - 日语
- `ko` - 韩语
- 留空 = 自动检测

---

## ⚠️ 注意事项

1. 首次运行需要下载 Whisper 模型 (large-v3 约 3GB)
2. GPU 显存建议 8GB+ (large-v3 模型)
3. 部分视频可能因版权限制无法下载
4. Colab 免费版有 GPU 使用时长限制

---

## 📄 License

MIT License
