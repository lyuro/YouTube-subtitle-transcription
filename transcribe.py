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
from pathlib import Path

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
import whisper


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
    支持 youtu.be 短链和 youtube.com 完整链接
    """
    patterns = [
        r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?(?:www\.)?youtube\.com/embed/([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?(?:www\.)?youtube\.com/v/([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?youtu\.be/([a-zA-Z0-9_-]{11})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    return None


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
        {'player_client': ['ios', 'web']},
        {'player_client': ['android', 'web']},
        {'player_client': ['tv', 'web']},
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

    raise Exception(f"❌ 所有下载方式都失败。最后错误: {last_error}")


def transcribe_audio(
    audio_path: Path,
    model_name: str = "large-v3",
    language: str | None = None
) -> dict:
    """
    使用 Whisper 转录音频
    """
    print(f"🔄 正在加载 Whisper 模型 ({model_name})...")
    
    # 加载模型
    model = whisper.load_model(model_name)
    
    # 获取音频时长
    audio_duration = get_audio_duration(audio_path)
    if audio_duration > 0:
        print(f"🎵 音频时长: {format_duration(audio_duration)}")
    
    print("🎙️ 正在转录音频...")
    
    # 转录配置
    transcribe_options = {
        'verbose': True,  # 显示进度
        'fp16': True,     # 使用 FP16 加速
    }
    
    if language:
        transcribe_options['language'] = language
    
    # 记录开始时间
    start_time = time.time()
    
    result = model.transcribe(str(audio_path), **transcribe_options)
    
    # 计算处理耗时和速度
    elapsed_time = time.time() - start_time
    
    detected_lang = result.get('language', 'unknown')
    print(f"\n✅ 转录完成！检测到语言: {detected_lang}")
    print(f"⏱️  处理耗时: {format_duration(elapsed_time)}")
    
    if audio_duration > 0:
        speed_ratio = audio_duration / elapsed_time
        print(f"🚀 处理速度: {speed_ratio:.2f}x 实时速度")
    
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
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(result['text'].strip())
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
        with open(txt_file, 'w', encoding='utf-8') as f:
            f.write(result['text'].strip())
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
        """
    )
    
    parser.add_argument(
        'url',
        type=str,
        help='YouTube 视频 URL'
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
        '--language', '-l',
        type=str,
        default=None,
        help='指定音频语言 (如: zh, en, ja)，不指定则自动检测'
    )
    
    parser.add_argument(
        '--output-dir', '-d',
        type=str,
        default='.',
        help='输出目录 (默认: 当前目录)'
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
    
    # 验证 URL
    video_id = parse_youtube_url(args.url)
    if not video_id:
        print("❌ 无效的 YouTube URL")
        sys.exit(1)
    
    print(f"🎬 Video ID: {video_id}")
    
    # 设置输出目录
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 创建临时目录用于下载
    temp_dir = Path(tempfile.mkdtemp())
    audio_path = None
    
    try:
        # 下载音频
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

        audio_path, video_title = download_audio(
            args.url,
            temp_dir,
            cookies_path=args.cookies,
            cookies_from_browser=args.cookies_from_browser,
            js_runtimes=js_runtimes,
            remote_components=remote_components
        )
        
        # 转录
        result = transcribe_audio(
            audio_path,
            model_name=args.model,
            language=args.language
        )
        
        # 保存结果
        safe_title = sanitize_filename(video_title)
        output_path = output_dir / safe_title
        save_transcript(result, output_path, args.output)
        
        # 如果需要保留音频，移动到输出目录
        if args.keep_audio and audio_path:
            import shutil
            dest_audio = output_dir / audio_path.name
            shutil.move(str(audio_path), str(dest_audio))
            print(f"🎵 音频文件已保存: {dest_audio}")
            audio_path = None
        
        print("\n✨ 处理完成！")
        
    except KeyboardInterrupt:
        print("\n⚠️ 用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        sys.exit(1)
    finally:
        # 清理临时文件
        if temp_dir.exists():
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
            print("🧹 临时文件已清理")


if __name__ == "__main__":
    main()
