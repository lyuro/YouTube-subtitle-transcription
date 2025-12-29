# 🎬 YouTube 视频转录工具 (Google Colab 版)

一键在 Google Colab 上转录 YouTube 视频，输出 `.txt` 和 `.srt` 文件到 Google Drive。

## 🚀 快速开始

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/YOUR_USERNAME/YoutubeSubtitle-Colab/blob/main/YouTube_Transcribe.ipynb)

1. 点击上方按钮打开 Colab
2. 依次运行单元格
3. 在配置单元格填入 YouTube URL
4. 执行转录，文件自动保存到 Google Drive

## 📋 功能

- ✅ 支持任意 YouTube 视频 URL
- ✅ 使用 OpenAI Whisper 进行高质量转录
- ✅ 支持多种语言自动检测或手动指定
- ✅ 输出 `.txt` (纯文本) 和 `.srt` (字幕文件)
- ✅ 自动保存到 Google Drive
- ✅ 免费使用 Colab GPU 加速

## 📦 依赖

无需手动安装，Notebook 会自动安装：
- `yt-dlp` - YouTube 音频下载
- `openai-whisper` - 语音转文字

## 🎯 使用说明

### 1. 选择 GPU 运行时
`Runtime → Change runtime type → T4 GPU`

### 2. 运行安装依赖
首次运行需要安装依赖包

### 3. 挂载 Google Drive
授权访问你的 Google Drive

### 4. 配置参数
- **YOUTUBE_URL**: YouTube 视频链接
- **MODEL**: Whisper 模型 (推荐 `large-v3`)
- **LANGUAGE**: 语言代码 (留空自动检测)

### 5. 执行转录
运行最后一个单元格，等待完成

## 🎛️ Whisper 模型

| 模型 | 大小 | 速度 | 准确度 | 推荐场景 |
|------|------|------|--------|----------|
| tiny | 39M | ~32x | ★★☆☆☆ | 快速预览 |
| base | 74M | ~16x | ★★★☆☆ | 简单内容 |
| small | 244M | ~6x | ★★★★☆ | 日常使用 |
| medium | 769M | ~2x | ★★★★☆ | 高质量需求 |
| large-v3 | 1550M | 1x | ★★★★★ | 最佳质量 |

## 📁 输出文件

文件保存在 Google Drive:
```
Google Drive/
└── YouTubeTranscripts/
    ├── 视频标题.txt    # 纯文本
    └── 视频标题.srt    # SRT 字幕
```

## 🌐 支持的语言

Whisper 支持 99 种语言，常用代码：
- `zh` - 中文
- `en` - 英语
- `ja` - 日语
- `ko` - 韩语
- 留空 = 自动检测

## ⚠️ 注意事项

1. Colab 免费版有使用时长限制
2. 长视频 (>1小时) 建议使用 `medium` 或更小模型
3. 确保 Google Drive 有足够空间
4. 部分视频可能因版权限制无法下载

## 📄 License

MIT License
