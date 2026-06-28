import subprocess
from pathlib import Path

def cut_media(input_path: Path, output_path: Path, start_sec: float, end_sec: float, is_audio: bool = False):
    """精确截取媒体片段（重新编码）"""
    if is_audio:
        cmd = [
            "ffmpeg", "-i", str(input_path),
            "-ss", str(start_sec), "-to", str(end_sec),
            "-vn", "-c:a", "libmp3lame",
            "-y", str(output_path)
        ]
    else:
        cmd = [
            "ffmpeg",
            "-i", str(input_path),
            "-ss", str(start_sec),
            "-to", str(end_sec),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-y", str(output_path)
        ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {result.stderr}")

def cut_text(entry: dict, output_path: Path):
    """生成文字片段文件"""
    start_time = format_srt_time(entry['start_sec'])
    end_time = format_srt_time(entry['end_sec'])
    content = f"时间：{start_time} --> {end_time}\n台词：\n{entry['text']}\n"
    output_path.write_text(content, encoding='utf-8')

def format_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace('.', ',')