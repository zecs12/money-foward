"""
マネーフォワードME画面上の文字列(金額・日付・パーセント)を、
プログラムで扱いやすい数値に変換するための共通処理。
"""

import re

_STRIP_CHARS_PATTERN = re.compile(r"[¥$,\s円+\-−▲]")
_OKU_PATTERN = re.compile(r"(\d+(?:\.\d+)?)億")
_MAN_PATTERN = re.compile(r"(\d+(?:\.\d+)?)万")
_PERCENT_STRIP_PATTERN = re.compile(r"[%％\s+\-−▲]")
_SLASH_DATE_PATTERN = re.compile(r"^(\d{1,2})/(\d{1,2})")
_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}")

_NEGATIVE_MARKERS = ("-", "−", "▲")
_EMPTY_MARKERS = ("-", "−", "—", "–", "―")


def _is_negative(text: str) -> bool:
    return any(marker in text for marker in _NEGATIVE_MARKERS)


def parse_japanese_number(text: str) -> int:
    """「1億9,233万」「¥12,300」のような文字列を整数(円)に変換する。"""
    if not text:
        return 0

    is_negative = _is_negative(text)
    remaining = _STRIP_CHARS_PATTERN.sub("", text)

    oku_match = _OKU_PATTERN.search(remaining)
    man_match = _MAN_PATTERN.search(remaining)

    if oku_match or man_match:
        total = 0.0
        if oku_match:
            total += float(oku_match.group(1)) * 100_000_000
            remaining = _OKU_PATTERN.sub("", remaining)
        if man_match:
            total += float(man_match.group(1)) * 10_000
            remaining = _MAN_PATTERN.sub("", remaining)

        digits_only = re.sub(r"\D", "", remaining)
        if digits_only:
            total += int(digits_only)

        rounded = round(total)
        return -rounded if is_negative else rounded

    cleaned = _STRIP_CHARS_PATTERN.sub("", text)
    if not cleaned.isdigit():
        return 0
    value = int(cleaned)
    return -value if is_negative else value


def parse_decimal_number(text: str) -> float:
    """口数・単価など、小数を含む可能性のある数値を変換する。"""
    if not text:
        return 0.0
    is_negative = _is_negative(text)
    cleaned = _STRIP_CHARS_PATTERN.sub("", text)
    try:
        value = float(cleaned)
    except ValueError:
        return 0.0
    return -value if is_negative else value


def parse_optional_japanese_number(text: str) -> float | None:
    """空欄や「-」を None として扱う版の parse_decimal_number。"""
    trimmed = text.strip()
    if not trimmed or trimmed in _EMPTY_MARKERS:
        return None
    return parse_decimal_number(trimmed)


def parse_percentage(text: str) -> float | None:
    """「+3.2%」のような文字列を数値(3.2 / -3.2)に変換する。"""
    if not text:
        return None
    is_negative = _is_negative(text)
    cleaned = _PERCENT_STRIP_PATTERN.sub("", text)
    if not cleaned:
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return -value if is_negative else value


def convert_date_to_iso(date_text: str, year: int) -> str:
    """「01/22(木)」のような表示を「YYYY-MM-DD」形式に変換する。"""
    if not date_text:
        return ""
    if _ISO_DATE_PATTERN.match(date_text):
        return date_text[:10]

    match = _SLASH_DATE_PATTERN.match(date_text)
    if match:
        month, day = match.group(1).zfill(2), match.group(2).zfill(2)
        return f"{year}-{month}-{day}"

    return date_text
