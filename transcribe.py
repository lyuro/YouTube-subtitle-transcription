#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
YouTube 无字幕视频转录工具
使用 yt-dlp 下载音频，Whisper 本地转录
"""

import argparse
import os
import re
import sys
import tempfile
import shutil
import importlib.util
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# 在 Windows 上自动添加 WinGet 安装的 FFmpeg 路径
def setup_ffmpeg_path():
    """确保 FFmpeg 在 PATH 中可用"""
    winget_ffmpeg = Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'WinGet' / 'Links'
    if winget_ffmpeg.exists() and (winget_ffmpeg / 'ffmpeg.exe').exists():
        current_path = os.environ.get('PATH', '')
        if str(winget_ffmpeg) not in current_path:
            os.environ['PATH'] = str(winget_ffmpeg) + os.pathsep + current_path
            return True
    return False

setup_ffmpeg_path()

import time

import yt_dlp
from faster_whisper import WhisperModel


# ===== 幻听检测与黑名单 =====

# 已知的 Whisper 高频幻听关键词（中文场景）
# 这些词源于 YouTube 训练语料中反复出现的片头/片尾话术
HALLUCINATION_KEYWORDS = (
    "请不吝点赞", "点赞订阅", "订阅转发", "打赏", "明镜", "点点栏目",
    "感谢观看", "下期再见", "欢迎收看", "订阅频道", "开启小铃铛",
    "不忘初心", "MBC 新闻", "中央社", "多谢观看",
)

# segment 被判定为幻听的最小关键词命中数
HALLUCINATION_KEYWORD_HIT = 1


class HallucinationDetected(Exception):
    """检测到幻听崩溃，中断转录用于 fallback 重试"""
    pass


class HallucinationMonitor:
    """
    流式监控 segment 输出，检测 Whisper 幻听崩溃。
    触发条件（任一满足）：
      1. 连续 >= consecutive_threshold 个 segment 文本完全一致
      2. 最近 window_seconds 秒音频内 unique segment 占比 < unique_ratio
      3. 最近 window_seconds 秒音频内黑名单词命中 >= keyword_hits
    """

    def __init__(
        self,
        consecutive_threshold: int = 10,
        window_seconds: float = 300.0,
        unique_ratio: float = 0.2,
        keyword_hits: int = 10,
        min_window_segments: int = 20,
    ) -> None:
        self.consecutive_threshold = consecutive_threshold
        self.window_seconds = window_seconds
        self.unique_ratio = unique_ratio
        self.keyword_hits = keyword_hits
        self.min_window_segments = min_window_segments
        self._last_text: str | None = None
        self._consecutive_same: int = 0
        # 滑动窗口：(end_time, text)
        self._window: list[tuple[float, str]] = []

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", "", text or "").strip()

    @staticmethod
    def _hits_keyword(text: str) -> bool:
        return any(kw in text for kw in HALLUCINATION_KEYWORDS)

    def feed(self, start: float, end: float, text: str) -> None:
        norm = self._normalize(text)
        if not norm:
            return

        # 1. 连续重复
        if norm == self._last_text:
            self._consecutive_same += 1
        else:
            self._consecutive_same = 1
            self._last_text = norm

        if self._consecutive_same >= self.consecutive_threshold:
            raise HallucinationDetected(
                f"连续 {self._consecutive_same} 个相同 segment: '{norm[:40]}'"
            )

        # 2/3. 滑动窗口统计
        self._window.append((end, norm))
        cutoff = end - self.window_seconds
        while self._window and self._window[0][0] < cutoff:
            self._window.pop(0)

        if len(self._window) >= self.min_window_segments:
            texts = [t for _, t in self._window]
            unique_count = len(set(texts))
            ratio = unique_count / len(texts)
            if ratio < self.unique_ratio:
                raise HallucinationDetected(
                    f"最近 {self.window_seconds:.0f}s 内 unique 占比 {ratio:.0%} < {self.unique_ratio:.0%}"
                )

            kw_hits = sum(1 for t in texts if self._hits_keyword(t))
            if kw_hits >= self.keyword_hits:
                raise HallucinationDetected(
                    f"最近 {self.window_seconds:.0f}s 内命中黑名单词 {kw_hits} 次"
                )


def filter_hallucinated_segments(segments: list[dict]) -> list[dict]:
    """后处理：剔除“全是黑名单关键词”的孤立 segment"""
    cleaned: list[dict] = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if any(kw in text for kw in HALLUCINATION_KEYWORDS):
            # 若该段除黑名单词之外几乎没有其他实质内容，则丢弃
            stripped = text
            for kw in HALLUCINATION_KEYWORDS:
                stripped = stripped.replace(kw, "")
            stripped = re.sub(r"[\s\u3000\.,\u3002\uff0c\u3001\uff01\uff1f!?]", "", stripped)
            if len(stripped) <= 2:
                continue
        cleaned.append(seg)
    return cleaned


def build_plain_text_from_segments(segments: list[dict]) -> str:
    """将转录 segment 转成每段一行的纯文本。"""
    lines: list[str] = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def print_segment_coverage(segments: list[dict], audio_duration: float) -> None:
    """打印 segment 覆盖统计，辅助判断是否可能缺失内容。"""
    print(f"🧩 Segment 数量: {len(segments)}")
    if not segments:
        print("⚠️ 未生成任何 segment")
        return

    last_end = float(segments[-1].get("end") or 0.0)
    if audio_duration > 0:
        coverage = min(100.0, last_end / audio_duration * 100)
        print(
            f"📈 覆盖进度: {format_duration(last_end)} / "
            f"{format_duration(audio_duration)} ({coverage:.1f}%)"
        )
    else:
        print(f"📈 最后片段结束: {format_duration(last_end)}")

    long_gaps: list[float] = []
    previous_end = float(segments[0].get("end") or 0.0)
    for seg in segments[1:]:
        start = float(seg.get("start") or 0.0)
        gap = start - previous_end
        if gap >= 10.0:
            long_gaps.append(gap)
        previous_end = float(seg.get("end") or previous_end)

    if long_gaps:
        print(
            f"ℹ️ 检测到 {len(long_gaps)} 个较长无转录间隔 "
            f"(最长 {format_duration(max(long_gaps))})，通常是静音/BGM/VAD 跳过"
        )


def get_audio_duration(audio_path: Path) -> float:
    """获取音频文件时长（秒）"""
    import subprocess
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', str(audio_path)],
            capture_output=True,
            text=True
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def format_duration(seconds: float) -> str:
    """将秒数格式化为易读的时间字符串"""
    if seconds < 60:
        return f"{seconds:.1f}秒"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}分{secs}秒"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}小时{mins}分"


def parse_youtube_url(url: str) -> str | None:
    """
    解析 YouTube URL，提取 video_id
    支持 watch、youtu.be、embed、v、shorts、live 等链接
    """
    url = url.strip()
    if re.fullmatch(r'[a-zA-Z0-9_-]{11}', url):
        return url

    if not re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', url):
        url = f'https://{url}'

    parsed = urlparse(url)
    host = parsed.netloc.lower().split(':', 1)[0]
    path_parts = [part for part in parsed.path.split('/') if part]

    def is_valid_video_id(value: str | None) -> bool:
        return bool(value and re.fullmatch(r'[a-zA-Z0-9_-]{11}', value))

    if host == 'youtu.be' and path_parts:
        video_id = path_parts[0]
        return video_id if is_valid_video_id(video_id) else None

    if host.endswith('youtube.com') or host.endswith('youtube-nocookie.com'):
        query = parse_qs(parsed.query)
        video_id = query.get('v', [None])[0]
        if is_valid_video_id(video_id):
            return video_id

        if len(path_parts) >= 2 and path_parts[0] in {'embed', 'v', 'shorts', 'live'}:
            video_id = path_parts[1]
            if is_valid_video_id(video_id):
                return video_id

    return None


def parse_url_list(values: list[str] | str) -> list[str]:
    """解析批量 URL 输入，支持竖线、回车和空白分隔。"""
    if isinstance(values, str):
        raw_text = values
    else:
        raw_text = "\n".join(values)
    return [part.strip() for part in re.split(r"(?:\||\s)+", raw_text) if part.strip()]


def sanitize_filename(filename: str) -> str:
    """清理文件名，移除非法字符"""
    illegal_chars = r'[<>:"/\\|?*]'
    sanitized = re.sub(illegal_chars, '_', filename)
    # 限制长度
    return sanitized[:200] if len(sanitized) > 200 else sanitized


def parse_js_runtimes(spec: str | None) -> dict | None:
    """解析 --js-runtimes 参数，返回 yt-dlp 需要的 dict"""
    if not spec:
        return None
    parts = [p.strip() for p in spec.split(",") if p.strip()]
    if not parts:
        return None
    runtimes: dict = {}
    for part in parts:
        if ":" in part:
            name, path = part.split(":", 1)
            name = name.strip()
            path = path.strip()
            if name:
                runtimes[name] = {"path": path} if path else {}
        else:
            runtimes[part] = {}
    return runtimes or None


def detect_js_runtime() -> dict | None:
    """自动检测可用 JS runtime"""
    runtime_bins = {
        "deno": ["deno"],
        "bun": ["bun"],
        "node": ["node"],
        "quickjs": ["qjs", "quickjs"],
    }
    for name, bins in runtime_bins.items():
        for bin_name in bins:
            path = shutil.which(bin_name)
            if path:
                return {name: {"path": path}}
    return None


def parse_remote_components(spec: str | None) -> set | None:
    """解析 --remote-components 参数，返回 set"""
    if not spec:
        return None
    parts = [p.strip() for p in spec.split(",") if p.strip()]
    return set(parts) if parts else None


def preflight_check(
    cookies_path: str | None,
    cookies_from_browser: str | None,
    js_runtimes: dict | None,
    remote_components: set | None
) -> None:
    """执行环境自检并输出提示"""
    print("🔍 环境自检...")

    # yt-dlp 版本
    try:
        from yt_dlp import version as ydl_version
        print(f"   yt-dlp: {ydl_version.__version__}")
    except Exception:
        print("   yt-dlp: unknown")

    # JS runtime
    if js_runtimes:
        print(f"   JS runtime: {', '.join(js_runtimes.keys())}")
    else:
        print("   JS runtime: 未检测到")
        print("     建议安装 Deno/Node/Bun，或传 --js-runtimes")

    # EJS 组件
    ejs_remote = False
    if remote_components:
        for comp in remote_components:
            if comp.startswith("ejs"):
                ejs_remote = True
                break

    ejs_local = False
    if importlib.util.find_spec("yt_dlp_ejs") is not None:
        ejs_local = True
    elif importlib.util.find_spec("ytdlp_ejs") is not None:
        ejs_local = True

    if ejs_local:
        print("   EJS: 已安装 (yt-dlp-ejs)")
    elif ejs_remote:
        print(f"   EJS: 将通过远程组件获取 ({', '.join(sorted(remote_components))})")
    else:
        print("   EJS: 未检测到")
        print("     解决: pip install \"yt-dlp[default]\" 或加 --remote-components ejs:github / ejs:npm")

    # Cookies 来源
    if cookies_path:
        cookiefile = Path(cookies_path).expanduser().resolve()
        exists = "存在" if cookiefile.exists() else "不存在"
        print(f"   Cookies: 文件 {cookiefile}（{exists}）")
    elif cookies_from_browser:
        print(f"   Cookies: 浏览器 {cookies_from_browser}")
    else:
        default_dir = Path(__file__).resolve().parent / "cookies"
        auto_cookie = find_cookie_file(default_dir)
        if auto_cookie:
            print(f"   Cookies: 自动发现 {auto_cookie}")
        else:
            print("   Cookies: 未配置（可放在 ./cookies 下）")


def find_cookie_file(search_dir: Path) -> Path | None:
    """在指定目录中查找 cookies 文件（优先 cookies.txt，其次最新的 .txt）"""
    if not search_dir.exists():
        return None
    preferred = search_dir / "cookies.txt"
    if preferred.exists():
        return preferred
    candidates = list(search_dir.glob("*.txt"))
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def parse_cookies_from_browser(spec: str) -> tuple[str, str] | tuple[str] | None:
    """解析 --cookies-from-browser 参数 (如: chrome 或 chrome:Profile 1)"""
    if not spec:
        return None
    spec = spec.strip()
    if not spec:
        return None
    if ":" in spec:
        browser, profile = spec.split(":", 1)
        browser = browser.strip()
        profile = profile.strip()
        if browser and profile:
            return (browser, profile)
        if browser:
            return (browser,)
        return None
    return (spec,)


def download_audio(
    url: str,
    output_dir: Path,
    cookies_path: str | None = None,
    cookies_from_browser: str | None = None,
    js_runtimes: dict | None = None,
    remote_components: set | None = None
) -> tuple[Path, str]:
    """
    使用 yt-dlp 下载音频
    返回 (音频文件路径, 视频标题)
    """
    print("📥 正在下载音频...")

    cookies_opts: dict = {}
    if cookies_path:
        cookiefile = Path(cookies_path).expanduser().resolve()
        if not cookiefile.exists():
            raise FileNotFoundError(f"Cookies 文件不存在: {cookiefile}")
        cookies_opts['cookiefile'] = str(cookiefile)
        print(f"🍪 使用 cookies 文件: {cookiefile}")
    elif cookies_from_browser:
        parsed = parse_cookies_from_browser(cookies_from_browser)
        if parsed:
            cookies_opts['cookiesfrombrowser'] = parsed
            print(f"🍪 从浏览器读取 cookies: {cookies_from_browser}")
    else:
        default_dir = Path(__file__).resolve().parent / "cookies"
        auto_cookie = find_cookie_file(default_dir)
        if auto_cookie:
            cookies_opts['cookiefile'] = str(auto_cookie)
            print(f"🍪 自动发现 cookies: {auto_cookie}")
    
    # 先获取视频信息
    base_opts = {'quiet': True}
    if js_runtimes:
        base_opts['js_runtimes'] = js_runtimes
    if remote_components:
        base_opts['remote_components'] = remote_components
    base_opts.update(cookies_opts)
    with yt_dlp.YoutubeDL(base_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        video_title = info.get('title', 'unknown')
        video_id = info.get('id', 'unknown')
    
    safe_title = sanitize_filename(video_title)
    output_template = str(output_dir / f"{safe_title}.%(ext)s")

    client_configs = [
        {'player_client': ['android', 'web']},
        {'player_client': ['tv', 'web']},
        {'player_client': ['web']},
        {'player_client': ['ios', 'web']},
        {},
    ]

    last_error = None
    for extractor_args in client_configs:
        client_name = extractor_args.get('player_client', 'default')
        print(f"🔄 尝试客户端: {client_name}")

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_template,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': False,
            'no_warnings': False,
        }
        if js_runtimes:
            ydl_opts['js_runtimes'] = js_runtimes
        if remote_components:
            ydl_opts['remote_components'] = remote_components
        ydl_opts.update(cookies_opts)
        if extractor_args:
            ydl_opts['extractor_args'] = {'youtube': extractor_args}

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            audio_path = output_dir / f"{safe_title}.mp3"
            if audio_path.exists():
                print(f"✅ 音频下载完成: {audio_path.name}")
                return audio_path, video_title
        except Exception as e:
            last_error = e
            print(f"⚠️ 客户端 {client_name} 失败: {str(e)[:120]}")

    raise RuntimeError(f"❌ 所有下载方式都失败。最后错误: {last_error}") from last_error


# CJK 语言的 initial_prompt，引导 Whisper 输出正确标点
INITIAL_PROMPTS = {
    'zh': '以下是普通话的句子，包含正确的标点符号。',
    'ja': '以下は日本語のテキストです。句読点を含みます。',
    'ko': '다음은 한국어 문장입니다. 올바른 구두점을 포함합니다.',
}


def normalize_language(language: str | None) -> str | None:
    """
    归一化语言参数：
      - None（未指定）→ 默认 zh
      - 'auto' 或空字符串 → None，由 faster-whisper 自动检测
      - 其他 → 去空格、转小写后作为语言代码使用
    """
    if language is None:
        return "zh"
    lang = language.strip().lower()
    if lang in ("", "auto"):
        return None
    return lang


def load_whisper_model(model_name: str = "large-v3") -> WhisperModel:
    """加载 faster-whisper 模型，自动选择 GPU/CPU"""
    import torch
    if torch.cuda.is_available():
        device = "cuda"
        compute_type = "float16"
    else:
        device = "cpu"
        compute_type = "int8"
    print(f"🔄 正在加载 faster-whisper 模型 ({model_name}, {device}/{compute_type})...")
    return WhisperModel(model_name, device=device, compute_type=compute_type)


def _build_transcribe_kwargs(language: str | None, aggressive: bool) -> dict:
    """
    构建 faster-whisper transcribe() 调用参数。
    language=None 时由 faster-whisper 用音频前 30 秒自动检测语言。
    aggressive=True 用于 fallback 重试：收紧 VAD、关 beam search。
    """
    # VAD 参数：宽松配置（直播/讲解类不易丢信息）
    if aggressive:
        vad_parameters = dict(
            threshold=0.5,
            min_speech_duration_ms=200,
            min_silence_duration_ms=1500,
            speech_pad_ms=400,
        )
    else:
        vad_parameters = dict(
            threshold=0.3,
            min_speech_duration_ms=200,
            min_silence_duration_ms=2000,
            speech_pad_ms=600,
        )

    kwargs: dict = {
        "language": language,
        "vad_filter": True,
        "vad_parameters": vad_parameters,
        # 反幻听核心参数
        "condition_on_previous_text": False,
        "compression_ratio_threshold": 2.2,
        "no_speech_threshold": 0.7,
        "log_prob_threshold": -1.0,
        "hallucination_silence_threshold": 2.0,
        "word_timestamps": False,
    }

    if aggressive:
        # fallback：贪心解码，温度固定 0
        kwargs["temperature"] = 0.0
        kwargs["beam_size"] = 1
    else:
        kwargs["beam_size"] = 5
        kwargs["temperature"] = [0.0, 0.2, 0.4]

    prompt_lang = kwargs["language"]
    if prompt_lang in INITIAL_PROMPTS:
        kwargs["initial_prompt"] = INITIAL_PROMPTS[prompt_lang]

    return kwargs


def _run_transcribe(
    model: WhisperModel,
    audio_path: Path,
    audio_duration: float,
    language: str | None,
    aggressive: bool,
) -> dict:
    """执行一次转录，流式收集 segment 并实时监控幻听"""
    kwargs = _build_transcribe_kwargs(language, aggressive)
    label = "fallback (激进)" if aggressive else "正常"
    print(f"🎙️ 正在转录音频... [{label}]")

    monitor = HallucinationMonitor(
        consecutive_threshold=10,
        window_seconds=300.0,
        unique_ratio=0.2,
        keyword_hits=10,
    )

    start_time = time.time()
    segments_iter, info = model.transcribe(str(audio_path), **kwargs)

    detected_lang = info.language
    if not language:
        print(f"🌐 检测到语言: {detected_lang}")

    collected: list[dict] = []
    last_progress_print = 0.0

    for seg in segments_iter:
        seg_dict = {
            "start": seg.start,
            "end": seg.end,
            "text": seg.text,
        }
        collected.append(seg_dict)

        # 实时打印抽样进度（每 30 秒音频时长打印一次）
        if seg.end - last_progress_print >= 30.0:
            ts = format_timestamp(seg.start).replace(",", ".")
            preview = seg.text.strip()[:60]
            if audio_duration > 0:
                pct = min(100.0, seg.end / audio_duration * 100)
                print(f"  进度预览 [{ts}] ({pct:5.1f}%) {preview}")
            else:
                print(f"  进度预览 [{ts}] {preview}")
            last_progress_print = seg.end

        # 反幻听监控（可能抛 HallucinationDetected）
        monitor.feed(seg.start, seg.end, seg.text)

    elapsed_time = time.time() - start_time

    full_text = build_plain_text_from_segments(collected)
    print(f"\n✅ 转录完成！语言: {detected_lang}")
    print(f"⏱️  处理耗时: {format_duration(elapsed_time)}")
    if audio_duration > 0:
        speed_ratio = audio_duration / elapsed_time
        print(f"🚀 处理速度: {speed_ratio:.2f}x 实时速度")
    print_segment_coverage(collected, audio_duration)

    return {
        "text": full_text,
        "segments": collected,
        "language": detected_lang,
    }


def transcribe_audio(
    audio_path: Path,
    model_name: str = "large-v3",
    language: str | None = None,
    model: WhisperModel | None = None,
) -> dict:
    """
    使用 faster-whisper 转录音频。
    language 传 'auto' 或空则自动检测，不传默认 zh。
    内置反幻听监控；触发后自动用激进参数重试一次，仍失败则抛异常。
    """
    language = normalize_language(language)

    if model is None:
        model = load_whisper_model(model_name)

    audio_duration = get_audio_duration(audio_path)
    if audio_duration > 0:
        print(f"🎵 音频时长: {format_duration(audio_duration)}")

    # 第一次尝试：正常参数
    try:
        result = _run_transcribe(model, audio_path, audio_duration, language, aggressive=False)
    except HallucinationDetected as e:
        print(f"\n⚠️ 检测到幻听: {e}")
        print("🔁 切换激进参数重试 (greedy + 收紧 VAD)...")
        # 第二次尝试：fallback 激进参数
        try:
            result = _run_transcribe(model, audio_path, audio_duration, language, aggressive=True)
        except HallucinationDetected as e2:
            raise RuntimeError(f"两次尝试均检测到幻听，放弃: {e2}") from e2

    # 后处理：剔除孤立的全黑名单 segment
    before = len(result["segments"])
    result["segments"] = filter_hallucinated_segments(result["segments"])
    after = len(result["segments"])
    if before != after:
        print(f"🧹 后处理过滤幻听 segment: {before - after} 个")
        result["text"] = build_plain_text_from_segments(result["segments"])

    return result


def format_timestamp(seconds: float) -> str:
    """将秒数转换为 SRT 时间戳格式 (HH:MM:SS,mmm)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def save_transcript(
    result: dict,
    output_path: Path,
    output_format: str = "txt"
) -> Path:
    """
    保存转录结果
    支持 txt 和 srt 格式
    """
    if output_format == "txt":
        output_file = output_path.with_suffix('.txt')
        text = result.get('text') or build_plain_text_from_segments(result.get('segments', []))
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(text.strip())
        print(f"📄 文本文件已保存: {output_file}")
        
    elif output_format == "srt":
        output_file = output_path.with_suffix('.srt')
        segments = result.get('segments', [])
        
        with open(output_file, 'w', encoding='utf-8') as f:
            for i, segment in enumerate(segments, start=1):
                start_time = format_timestamp(segment['start'])
                end_time = format_timestamp(segment['end'])
                text = segment['text'].strip()
                
                f.write(f"{i}\n")
                f.write(f"{start_time} --> {end_time}\n")
                f.write(f"{text}\n\n")
        
        print(f"📄 字幕文件已保存: {output_file}")
        
    elif output_format == "both":
        # 保存 txt
        txt_file = output_path.with_suffix('.txt')
        text = result.get('text') or build_plain_text_from_segments(result.get('segments', []))
        with open(txt_file, 'w', encoding='utf-8') as f:
            f.write(text.strip())
        print(f"📄 文本文件已保存: {txt_file}")
        
        # 保存 srt
        srt_file = output_path.with_suffix('.srt')
        segments = result.get('segments', [])
        with open(srt_file, 'w', encoding='utf-8') as f:
            for i, segment in enumerate(segments, start=1):
                start_time = format_timestamp(segment['start'])
                end_time = format_timestamp(segment['end'])
                text = segment['text'].strip()
                f.write(f"{i}\n")
                f.write(f"{start_time} --> {end_time}\n")
                f.write(f"{text}\n\n")
        print(f"📄 字幕文件已保存: {srt_file}")
        output_file = srt_file
    else:
        raise ValueError(f"不支持的输出格式: {output_format}")
    
    return output_file


def main():
    parser = argparse.ArgumentParser(
        description="YouTube 无字幕视频转录工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python transcribe.py "https://youtu.be/xxxxx"
  python transcribe.py "https://youtube.com/watch?v=xxxxx" --model medium
  python transcribe.py "https://youtu.be/xxxxx" --output srt
  python transcribe.py "https://youtu.be/xxxxx" --output both --language ja
  python transcribe.py "https://youtu.be/xxxxx" --language auto
        """
    )
    
    parser.add_argument(
        'urls',
        type=str,
        nargs='+',
        help='YouTube 视频 URL；批量时支持空格、换行或 | 分隔'
    )
    
    parser.add_argument(
        '--model', '-m',
        type=str,
        default='large-v3',
        choices=['tiny', 'base', 'small', 'medium', 'large', 'large-v2', 'large-v3'],
        help='Whisper 模型 (默认: large-v3)'
    )
    
    parser.add_argument(
        '--output', '-o',
        type=str,
        default='txt',
        choices=['txt', 'srt', 'both'],
        help='输出格式 (默认: txt)'
    )
    
    parser.add_argument(
        '--srt',
        action='store_true',
        help='同时生成 SRT 字幕文件（等同于 --output both）'
    )
    
    parser.add_argument(
        '--language', '-l',
        type=str,
        default=None,
        help='指定音频语言 (如: zh, en, ja)；auto 表示自动检测；不指定默认 zh'
    )
    
    parser.add_argument(
        '--output-dir', '-d',
        type=str,
        default=None,
        help='输出目录 (默认: 脚本目录下的 output 文件夹)'
    )
    
    parser.add_argument(
        '--keep-audio', '-k',
        action='store_true',
        help='保留下载的音频文件'
    )

    parser.add_argument(
        '--cookies',
        type=str,
        default=None,
        help='cookies.txt 文件路径 (可选)'
    )

    parser.add_argument(
        '--cookies-from-browser',
        type=str,
        default=None,
        help='从浏览器读取 cookies，如: chrome 或 chrome:Profile 1 (可选)'
    )

    parser.add_argument(
        '--js-runtimes',
        type=str,
        default=None,
        help='JS runtime 列表，逗号分隔，如: deno 或 node:C:\\\\path\\\\node.exe'
    )

    parser.add_argument(
        '--remote-components',
        type=str,
        default=None,
        help='允许下载的远程组件，逗号分隔，如: ejs:github 或 ejs:npm'
    )
    
    args = parser.parse_args()
    
    # --srt 等同于 --output both
    if args.srt:
        args.output = 'both'
    
    url_list = parse_url_list(args.urls)
    if not url_list:
        print("❌ 未提供任何 URL")
        sys.exit(1)
    
    # 设置输出目录（默认为脚本目录下的 output 文件夹）
    if args.output_dir:
        output_dir = Path(args.output_dir).resolve()
    else:
        output_dir = Path(__file__).resolve().parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 创建临时目录用于整批下载
    temp_dir = Path(tempfile.mkdtemp())
    downloaded_items: list[tuple[str, Path, str]] = []
    failed_items: list[tuple[str, str]] = []
    
    try:
        js_runtimes = parse_js_runtimes(args.js_runtimes)
        if js_runtimes is None:
            js_runtimes = detect_js_runtime()
        remote_components = parse_remote_components(args.remote_components)

        preflight_check(
            args.cookies,
            args.cookies_from_browser,
            js_runtimes,
            remote_components
        )

        print(f"\n📋 批量任务: 共 {len(url_list)} 个视频")
        print("=" * 50)
        print("📥 阶段 1/2: 下载全部音频")

        valid_urls: list[tuple[str, str]] = []
        for url in url_list:
            video_id = parse_youtube_url(url)
            if video_id:
                valid_urls.append((url, video_id))
            else:
                print(f"❌ 无效的 YouTube URL: {url}")
                failed_items.append((url, "无效的 YouTube URL"))

        if not valid_urls:
            print("\n❌ 没有可处理的有效 URL")
            sys.exit(1)

        for idx, (url, video_id) in enumerate(valid_urls, 1):
            print(f"\n{'=' * 50}")
            print(f"📌 下载 [{idx}/{len(valid_urls)}]")
            print(f"🎬 Video ID: {video_id}")
            print(f"🔗 {url}")
            print("-" * 50)

            try:
                audio_path, video_title = download_audio(
                    url,
                    temp_dir,
                    cookies_path=args.cookies,
                    cookies_from_browser=args.cookies_from_browser,
                    js_runtimes=js_runtimes,
                    remote_components=remote_components
                )
                downloaded_items.append((url, audio_path, video_title))
            except Exception as e:
                print(f"❌ 下载失败: {e}")
                traceback.print_exc()
                failed_items.append((url, str(e)))

        if not downloaded_items:
            print("\n❌ 没有音频下载成功，跳过转录")
            sys.exit(1)

        print("\n" + "=" * 50)
        print(f"🎙️ 阶段 2/2: 转录已下载音频（{len(downloaded_items)} 个）")
        model = load_whisper_model(args.model)

        success_count = 0
        for idx, (url, audio_path, video_title) in enumerate(downloaded_items, 1):
            print(f"\n{'=' * 50}")
            print(f"📌 转录 [{idx}/{len(downloaded_items)}]")
            print(f"🔗 {url}")
            print("-" * 50)

            try:
                result = transcribe_audio(
                    audio_path,
                    model_name=args.model,
                    language=args.language,
                    model=model
                )

                safe_title = sanitize_filename(video_title)
                output_path = output_dir / safe_title
                save_transcript(result, output_path, args.output)

                if args.keep_audio:
                    dest_audio = output_dir / audio_path.name
                    shutil.move(str(audio_path), str(dest_audio))
                    print(f"🎵 音频文件已保存: {dest_audio}")

                success_count += 1
            except Exception as e:
                print(f"❌ 转录失败: {e}")
                traceback.print_exc()
                failed_items.append((url, str(e)))

        fail_count = len(failed_items)
        print("\n" + "=" * 50)
        print("📊 批量处理完成！")
        print(f"   ✅ 成功: {success_count}")
        print(f"   ❌ 失败: {fail_count}")
        print(f"📁 文件位置: {output_dir}")

        if failed_items:
            print("\n⚠️ 失败的 URL:")
            for url, error in failed_items:
                print(f"   - {url} ({error})")
            sys.exit(1)

        print("\n✨ 处理完成！")
        
    except KeyboardInterrupt:
        print("\n⚠️ 用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        # 清理临时文件
        if temp_dir.exists():
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
            print("🧹 临时文件已清理")


if __name__ == "__main__":
    main()

