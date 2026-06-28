# ==================== core/srt_parser.py ====================
import re
from typing import List, Dict

SRT_BLOCK = re.compile(r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.+?)(?=\n\n|\Z)', re.DOTALL)

def srt_time_to_sec(time_str: str) -> float:
    """将 SRT 时间字符串转换为秒数"""
    h, m, s = time_str.replace(',', '.').split(':')
    return int(h) * 3600 + int(m) * 60 + float(s)

def extract_chinese(text: str) -> str:
    """
    从文本中提取中文字符及常见中文标点，去除英文、数字、英文标点等。
    保留的中文标点：，。！？、；：“”‘’（）【】《》—…·
    """
    # 保留中文字符 + 中文标点 + 全角符号
    chinese_pattern = re.compile(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef，。！？、；：“”‘’（）【】《》—…·\n]')
    result = ''.join(chinese_pattern.findall(text))
    # 合并多余空行（保留换行结构）
    result = re.sub(r'\n{3,}', '\n\n', result).strip()
    return result

def parse_srt(srt_path) -> List[Dict]:
    """解析 SRT 文件，返回列表，每个元素包含 start_sec, end_sec, text（仅中文）"""
    with open(srt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    entries = []
    for match in SRT_BLOCK.finditer(content):
        idx = int(match.group(1))
        start_str = match.group(2)
        end_str = match.group(3)
        raw_text = match.group(4).strip()
        # 提取纯中文
        chinese_text = extract_chinese(raw_text)
        if not chinese_text:
            continue  # 跳过无中文的片段（如纯英文时间戳等）
        entries.append({
            'index': idx,
            'start_sec': srt_time_to_sec(start_str),
            'end_sec': srt_time_to_sec(end_str),
            'text': chinese_text
        })
    return entries