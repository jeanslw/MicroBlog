"""时间与时区工具：库内统一存 UTC ISO 字符串，显示层按设置时区换算。"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
LEGACY_FORMAT = "%Y-%m-%d %H:%M:%S"
LEGACY_TIMEZONE = "Asia/Shanghai"
DEFAULT_TIMEZONE = "UTC"
BROWSER_TZ_COOKIE = "blog_tz"
BACKUP_STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
LOG_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"

TIMEZONE_CHOICES = (
    ("UTC", "协调世界时"),
    ("Asia/Shanghai", "中国 · 上海"),
    ("Asia/Hong_Kong", "中国 · 香港"),
    ("Asia/Taipei", "中国 · 台北"),
    ("Asia/Tokyo", "日本 · 东京"),
    ("Asia/Seoul", "韩国 · 首尔"),
    ("Asia/Singapore", "新加坡"),
    ("Asia/Bangkok", "泰国 · 曼谷"),
    ("Asia/Jakarta", "印度尼西亚 · 雅加达"),
    ("Asia/Manila", "菲律宾 · 马尼拉"),
    ("Asia/Kuala_Lumpur", "马来西亚 · 吉隆坡"),
    ("Asia/Ho_Chi_Minh", "越南 · 胡志明市"),
    ("Asia/Kolkata", "印度 · 加尔各答"),
    ("Asia/Dubai", "阿联酋 · 迪拜"),
    ("Asia/Riyadh", "沙特 · 利雅得"),
    ("Asia/Tehran", "伊朗 · 德黑兰"),
    ("Asia/Jerusalem", "以色列 · 耶路撒冷"),
    ("Europe/London", "英国 · 伦敦"),
    ("Europe/Dublin", "爱尔兰 · 都柏林"),
    ("Europe/Paris", "法国 · 巴黎"),
    ("Europe/Berlin", "德国 · 柏林"),
    ("Europe/Madrid", "西班牙 · 马德里"),
    ("Europe/Rome", "意大利 · 罗马"),
    ("Europe/Amsterdam", "荷兰 · 阿姆斯特丹"),
    ("Europe/Zurich", "瑞士 · 苏黎世"),
    ("Europe/Stockholm", "瑞典 · 斯德哥尔摩"),
    ("Europe/Moscow", "俄罗斯 · 莫斯科"),
    ("Europe/Istanbul", "土耳其 · 伊斯坦布尔"),
    ("Europe/Lisbon", "葡萄牙 · 里斯本"),
    ("Africa/Cairo", "埃及 · 开罗"),
    ("Africa/Nairobi", "肯尼亚 · 内罗毕"),
    ("Africa/Johannesburg", "南非 · 约翰内斯堡"),
    ("America/New_York", "美国 · 纽约"),
    ("America/Chicago", "美国 · 芝加哥"),
    ("America/Denver", "美国 · 丹佛"),
    ("America/Los_Angeles", "美国 · 洛杉矶"),
    ("America/Toronto", "加拿大 · 多伦多"),
    ("America/Vancouver", "加拿大 · 温哥华"),
    ("America/Mexico_City", "墨西哥 · 墨西哥城"),
    ("America/Sao_Paulo", "巴西 · 圣保罗"),
    ("America/Buenos_Aires", "阿根廷 · 布宜诺斯艾利斯"),
    ("America/Santiago", "智利 · 圣地亚哥"),
    ("Australia/Sydney", "澳大利亚 · 悉尼"),
    ("Australia/Melbourne", "澳大利亚 · 墨尔本"),
    ("Australia/Perth", "澳大利亚 · 珀斯"),
    ("Pacific/Auckland", "新西兰 · 奥克兰"),
    ("Pacific/Honolulu", "美国 · 檀香山"),
    ("Pacific/Fiji", "斐济"),
)


def zone(name):
    """按 IANA 名称返回时区对象，无效名称回退默认时区。"""
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        try:
            return ZoneInfo(DEFAULT_TIMEZONE)
        except ZoneInfoNotFoundError:
            return timezone.utc


def is_valid_timezone(name):
    """返回时区名称是否可被 IANA 数据库识别。"""
    try:
        ZoneInfo(name or "")
        return True
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return False


def utc_now():
    """返回当前 UTC 的 aware datetime。"""
    return datetime.now(timezone.utc)


def utc_now_str():
    """返回当前 UTC 时间的库内存储字符串。"""
    return utc_now().strftime(UTC_FORMAT)


def parse_stored_time(value):
    """解析库内时间字符串，返回 UTC aware datetime；无效值返回 None。"""
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = datetime.strptime(text, LEGACY_FORMAT)
            except (TypeError, ValueError):
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zone(LEGACY_TIMEZONE))
    return dt.astimezone(timezone.utc)


def to_utc_str(value):
    """把时间字符串规范为 UTC 存储字符串；空值返回空串，无效值原样返回。"""
    text = str(value or "").strip()
    if not text:
        return ""
    dt = parse_stored_time(text)
    return dt.strftime(UTC_FORMAT) if dt is not None else text


def in_timezone(value, tz_name):
    """把库内时间换算为指定时区的 aware datetime；无效值返回 None。"""
    dt = parse_stored_time(value)
    return dt.astimezone(zone(tz_name)) if dt is not None else None


def year_month(value, tz_name):
    """返回库内时间在指定时区下的 (年, 月)；无效值返回 (None, None)。"""
    local = in_timezone(value, tz_name)
    return (local.year, local.month) if local is not None else (None, None)


def from_epoch(seconds):
    """把 epoch 秒转为 UTC 存储字符串。"""
    return datetime.fromtimestamp(seconds, timezone.utc).strftime(UTC_FORMAT)


def backup_stamp():
    """返回带毫秒的 UTC 紧凑时间戳，用于备份文件名。"""
    now = utc_now()
    return now.strftime(BACKUP_STAMP_FORMAT) + f"_{now.microsecond // 1000:03d}"
