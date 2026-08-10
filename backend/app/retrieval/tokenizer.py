"""共享检索分词器。

支持：Unicode NFKC 正规化、中文单字、中文二元组、
英文/数字词、条款编号、证书编号。

本模块不依赖任何外部分词库，完全基于正则和标准库实现。
"""

import re
import unicodedata
from typing import Iterable

# 分词器版本标识
TOKENIZER_NAME = "regex_cn_v1"
TOKENIZER_VERSION = "1.0.0"


# ── 模式定义 ────────────────────────────────────────────────

_CLAUSE_PATTERN = re.compile(
    r"SYN-(?:TENDER|CLAR|REQ|EQ|NUM|DATE|EVD)-\d{3}",
    re.IGNORECASE,
)
_CERT_PATTERN = re.compile(
    r"SYN-(?:JC|CMA)-\d{4,}(?:-\d{3,})?",
    re.IGNORECASE,
)

# 英文单词 / 数字 / 下划线组合
_WORD_PATTERN = re.compile(r"[a-zA-Z0-9_]+")

# 中文字符
_CHINESE_CHAR_PATTERN = re.compile(r"[一-鿿]")

# 数字序列（独立提取用于纯数字匹配）
_NUMBER_PATTERN = re.compile(r"\d+")

# 中日韩统一表意文字扩展区 A
_CJK_EXT_A = re.compile(r"[㐀-䶿]")

# 全角数字和字母（规范化）
_FULLWIDTH_DIGIT = re.compile(r"[０-９]")
_FULLWIDTH_UPPER = re.compile(r"[Ａ-Ｚ]")
_FULLWIDTH_LOWER = re.compile(r"[ａ-ｚ]")


def _to_halfwidth(text: str) -> str:
    """全角数字/字母转半角。"""
    result = []
    for ch in text:
        code = ord(ch)
        if 0xFF10 <= code <= 0xFF19:
            result.append(chr(code - 0xFF10 + ord("0")))
        elif 0xFF21 <= code <= 0xFF3A:
            result.append(chr(code - 0xFF21 + ord("A")))
        elif 0xFF41 <= code <= 0xFF5A:
            result.append(chr(code - 0xFF41 + ord("a")))
        else:
            result.append(ch)
    return "".join(result)


def tokenize(text: str) -> list[str]:
    """对文本执行 NFKC 正规化并分词。

    返回 token 列表，包含：
    - 英文/数字词（小写）
    - 中文单字
    - 中文二元组
    - 条款编号（保留原始大小写）
    - 证书编号（保留原始大小写）
    """
    if not text:
        return []

    # 1. Unicode NFKC 正规化
    normalized = unicodedata.normalize("NFKC", text)

    # 2. 全角数字/字母转半角
    normalized = _to_halfwidth(normalized)

    tokens: list[str] = []

    # 3. 提取特殊编号（条款号、证书号）
    clause_numbers = _CLAUSE_PATTERN.findall(normalized)
    cert_numbers = _CERT_PATTERN.findall(normalized)

    # 4. 提取英文单词和数字（小写）
    words = _WORD_PATTERN.findall(normalized)
    tokens.extend(w.lower() for w in words)

    # 5. 中文单字
    chinese_chars = _CHINESE_CHAR_PATTERN.findall(normalized)
    ext_a_chars = _CJK_EXT_A.findall(normalized)
    tokens.extend(chinese_chars)
    tokens.extend(ext_a_chars)

    # 6. 中文二元组（在连续中文字符上滑动窗口）
    chinese_spans: list[tuple[int, int]] = []
    i = 0
    while i < len(normalized):
        ch = normalized[i]
        if "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿":
            start = i
            while i < len(normalized) and (
                "一" <= normalized[i] <= "鿿"
                or "㐀" <= normalized[i] <= "䶿"
            ):
                i += 1
            chinese_spans.append((start, i))
        else:
            i += 1

    for start, end in chinese_spans:
        span_text = normalized[start:end]
        for j in range(len(span_text) - 1):
            tokens.append(span_text[j : j + 2])

    # 7. 添加特殊编号 token
    tokens.extend(clause_numbers)
    tokens.extend(cert_numbers)

    # 8. 过滤空 token
    return [t for t in tokens if t.strip()]


def tokenize_for_keyword(text: str) -> list[str]:
    """为关键词检索生成 token（保留更多原始形式）。

    与 tokenize 的区别：中文二元组不区分大小写处理。
    """
    return tokenize(text)
