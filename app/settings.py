"""系统设置读取：时区上下文与运行时配置的数据库优先覆盖。"""

import contextlib
import logging
from datetime import timedelta

from flask import has_request_context, request

from app.timeutil import BROWSER_TZ_COOKIE, DEFAULT_TIMEZONE, TIMEZONE_CHOICES, is_valid_timezone

RUNTIME_CONFIG_KEYS = {
    "page_size": "PAGE_SIZE",
    "log_level": "LOG_LEVEL",
    "log_format": "LOG_FORMAT",
    "slow_request_ms": "SLOW_REQUEST_MS",
    "slow_query_ms": "SLOW_QUERY_MS",
    "static_max_age": "SEND_FILE_MAX_AGE_DEFAULT",
    "reset_token_max_age": "RESET_TOKEN_MAX_AGE",
    "auto_schema_migrate": "AUTO_SCHEMA_MIGRATE",
    "allow_schema_ahead": "ALLOW_SCHEMA_AHEAD",
    "cookie_secure": "SESSION_COOKIE_SECURE",
}


def get_system_setting():
    """读取 system_settings 单行配置；表不可用或异常时返回 None。"""
    try:
        from app.database import get_system_setting as _get

        return _get()
    except Exception:
        with contextlib.suppress(Exception):
            from app.extensions import db

            db.session.rollback()
        return None


def apply_runtime_settings(app):
    """把系统设置中已配置的运行时项覆盖到 app.config，未配置项保留环境变量值。"""
    setting = get_system_setting()
    if setting is None:
        return
    for column, config_key in RUNTIME_CONFIG_KEYS.items():
        value = getattr(setting, column, None)
        if value is None or value == "":
            continue
        if config_key == "LOG_LEVEL":
            value = str(value).upper()
        elif config_key == "LOG_FORMAT":
            value = str(value).lower()
        app.config[config_key] = value
    lifetime = getattr(setting, "session_lifetime", None)
    if lifetime is not None:
        app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(seconds=int(lifetime))
    level = getattr(logging, str(app.config.get("LOG_LEVEL", "")).upper(), None)
    if isinstance(level, int):
        app.logger.setLevel(level)
        logging.getLogger("blog").setLevel(level)


def site_timezone():
    """返回系统设置中的站点时区，未配置或无效时返回默认时区。"""
    setting = get_system_setting()
    name = (getattr(setting, "timezone", None) or DEFAULT_TIMEZONE).strip()
    return name if is_valid_timezone(name) else DEFAULT_TIMEZONE


def follow_browser_tz():
    """返回是否跟随访客浏览器时区。"""
    setting = get_system_setting()
    return True if setting is None else bool(setting.follow_browser_tz)


def display_timezone():
    """返回当前生效的显示时区；开启跟随时优先使用访客浏览器时区。"""
    if follow_browser_tz() and has_request_context():
        browser_tz = request.cookies.get(BROWSER_TZ_COOKIE, "")
        if browser_tz and is_valid_timezone(browser_tz):
            return browser_tz
    return site_timezone()


def timezone_context():
    """返回模板与前端脚本共用的时区上下文。"""
    setting = get_system_setting()
    name = (getattr(setting, "timezone", None) or DEFAULT_TIMEZONE).strip()
    site_tz = name if is_valid_timezone(name) else DEFAULT_TIMEZONE
    follow = True if setting is None else bool(setting.follow_browser_tz)
    display = site_tz
    if follow and has_request_context():
        browser_tz = request.cookies.get(BROWSER_TZ_COOKIE, "")
        if browser_tz and is_valid_timezone(browser_tz):
            display = browser_tz
    return {
        "site_timezone": site_tz,
        "display_timezone": display,
        "follow_browser_tz": follow,
        "timezone_choices": TIMEZONE_CHOICES,
        "browser_tz_cookie": BROWSER_TZ_COOKIE,
    }


FEED_SWITCH_COLUMNS = {"rss": "rss_enabled", "atom": "atom_enabled"}


def feed_enabled(kind):
    """返回指定订阅源是否开启；读取失败时默认开启。"""
    column = FEED_SWITCH_COLUMNS.get(kind)
    if column is None:
        return False
    try:
        from app.database import get_site_setting

        site = get_site_setting()
        return True if site is None else bool(getattr(site, column, True))
    except Exception:
        with contextlib.suppress(Exception):
            from app.extensions import db

            db.session.rollback()
        return True


DEFAULT_RUNTIME_VALUES = {
    "page_size": 10,
    "log_level": "",
    "log_format": "",
    "slow_request_ms": 500,
    "slow_query_ms": 200,
    "static_max_age": 0,
    "session_lifetime": 86400,
    "reset_token_max_age": 1800,
    "auto_schema_migrate": True,
    "allow_schema_ahead": False,
    "cookie_secure": False,
}
