# ==================== core/comparator.py ====================
# 分隔符关键词（用于 SRT 解析？此处不需要，但保留以备扩展）
SEPARATOR_KEYWORDS = [
    "Verified Purchase",
    " people found this helpful",
    "Helpful",
    "Report",
    "Read more",
    "Translate review to English",
    "See more reviews",
    "See all photos",
    "Previous slide",
    "Next slide",
    "Reviews with images",
    "Capacity:",
    "Style:",
    "out of 5 stars",
    "Reviewed in",
]

def compare_duration(actual: float, expected: float, threshold: float = 0.5) -> bool:
    """返回 True 表示匹配（偏差 <= threshold）"""
    return abs(actual - expected) <= threshold