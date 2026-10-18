"""应用配置：按 BLOG_ENV 选择配置类（见 config_map），由 app.config.from_object() 加载。"""

import os
import secrets
import tempfile
import warnings
from typing import ClassVar
from urllib.parse import quote_plus

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ENV_FILE = os.path.join(_BASE_DIR, "app.env")
LEGACY_ENV_FILE = os.path.join(_BASE_DIR, ".env")

try:
    from dotenv import load_dotenv

    # 已存在的进程环境变量优先于文件值
    if os.path.exists(APP_ENV_FILE):
        load_dotenv(APP_ENV_FILE)
    elif os.path.exists(LEGACY_ENV_FILE):
        load_dotenv(LEGACY_ENV_FILE)
        warnings.warn(
            "检测到旧版 .env,已按兼容模式加载。应用侧配置已改用 app.env,"
            "建议执行 mv .env app.env（Windows: Move-Item .env app.env）完成迁移。",
            stacklevel=2,
        )
except ImportError:
    for _env_path in (APP_ENV_FILE, LEGACY_ENV_FILE):
        if os.path.exists(_env_path):
            warnings.warn(
                f"检测到 {os.path.basename(_env_path)} 文件但未安装 python-dotenv,"
                "该文件不会被加载。请执行 pip install python-dotenv 后重启服务。",
                stacklevel=2,
            )


def _env_bool(name: str, default: str = "false") -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        value = default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _normalize_trusted_host(entry: str) -> str:
    """把白名单条目归一化为纯主机名：兼容完整 URL 与裸域名两种写法。"""
    from urllib.parse import urlsplit

    entry = entry.strip().lower()
    if "://" in entry:
        entry = urlsplit(entry).netloc or ""
    # 去端口，IPv6 保留方括号形式
    entry = entry.split("]", 1)[0] + "]" if entry.startswith("[") else entry.split(":", 1)[0]
    return entry


# 应用版本（SemVer）
APP_VERSION = "1.3.6"

# 数据库结构版本；迁移登记见 app/database.py，初始结构见 MySQL/init.sql
SCHEMA_VERSION = "1.3.6"

PAGE_SIZE = int(os.environ.get("BLOG_PAGE_SIZE", "6"))

TITLE_MAX_LEN = 500
CAT_NAME_MAX_LEN = 60
SITE_NAME_MAX_LEN = 100
PASSWORD_MIN_LEN = 6
USERNAME_MAX_LEN = 50
COMMENT_MAX_LEN = 2000
REPLY_MAX_LEN = 2000

UPLOAD_ALLOWED_EXT = ("jpg", "jpeg", "png", "gif")
UPLOAD_ALLOWED_MIME = ("image/jpeg", "image/png", "image/gif")
UPLOAD_MAX_SIZE = 10 * 1024 * 1024
UPLOAD_BASE_NAME_LEN = 100
UPLOAD_MAX_WIDTH = 1200
BANNER_MAX_WIDTH = 1920
PIL_MAX_IMAGE_PIXELS = 50_000_000


# 密钥解析优先级：BLOG_SECRET_KEY > BLOG_SECRET_KEY_FILE > 随机值（仅开发）
INSECURE_DEFAULT_SECRET_KEYS = ("insecure-compose-default-key-CHANGE-ME-0123456789abcdef",)


def _read_secret_key_file(path: str) -> str:
    """读取密钥文件（去掉首尾空白）；不可读时告警并返回空串。"""
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError as exc:
        warnings.warn(
            f"BLOG_SECRET_KEY_FILE={path} 无法读取（{exc}），已忽略该配置。",
            stacklevel=2,
        )
        return ""


def _resolve_secret_key() -> str:
    """解析生效的 SECRET_KEY 原始值；完全未配置时返回空串（由调用方决定回退）。"""
    env_key = (os.environ.get("BLOG_SECRET_KEY") or "").strip()
    if env_key:
        return env_key
    return _read_secret_key_file((os.environ.get("BLOG_SECRET_KEY_FILE") or "").strip())


_RESOLVED_SECRET_KEY = _resolve_secret_key()


class Config:
    """基类配置（所有环境共享）"""

    SECRET_KEY = _RESOLVED_SECRET_KEY or secrets.token_hex(32)
    DEBUG = _env_bool("BLOG_DEBUG", "false")
    TESTING = False

    # 生成重置链接、RSS、sitemap 等绝对 URL 的站点域名；留空时回退 request.host_url
    CANONICAL_URL = (os.environ.get("BLOG_CANONICAL_URL") or "").rstrip("/")
    # 非白名单 Host 返回 400；留空不校验。键名不可改为 TRUSTED_HOSTS，该键由 Flask 3.1 原生消费
    HOST_WHITELIST: ClassVar[list[str]] = [
        h for h in (_normalize_trusted_host(x) for x in (os.environ.get("BLOG_TRUSTED_HOSTS") or "").split(",")) if h
    ]

    CSP_POLICY = (
        "default-src 'self'; "
        "img-src 'self' data: https:; "
        "media-src 'self' https:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; "
        "frame-ancestors 'self'"
    )
    # 防盗链的静态路径前缀；空 Referer 与白名单 Host 放行，其余 403
    HOTLINK_PROTECTED_PREFIXES: ClassVar[tuple[str, ...]] = ("/uploads/banner/", "/uploads/image/")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _env_bool("BLOG_COOKIE_SECURE", "false")
    # 由 app/__init__.py 在 from_object 之后转为 timedelta
    PERMANENT_SESSION_LIFETIME = int(os.environ.get("BLOG_SESSION_LIFETIME", "86400"))  # 单位秒

    SEND_FILE_MAX_AGE_DEFAULT = int(os.environ.get("BLOG_STATIC_MAX_AGE", "0"))
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # Flask 整体请求上限

    LOG_DIR = os.environ.get("BLOG_LOG_DIR") or os.path.join(_BASE_DIR, "logs")
    LOG_MAX_BYTES = int(os.environ.get("BLOG_LOG_MAX_BYTES", str(10 * 1024 * 1024)))
    LOG_BACKUP_COUNT = int(os.environ.get("BLOG_LOG_BACKUP_COUNT", "5"))
    LOG_FORMAT = (os.environ.get("BLOG_LOG_FORMAT") or "auto").lower()  # auto | json | text
    LOG_LEVEL = (os.environ.get("BLOG_LOG_LEVEL") or "auto").upper()  # auto | DEBUG | INFO | WARNING | ERROR | CRITICAL
    SLOW_REQUEST_MS = int(os.environ.get("BLOG_SLOW_REQUEST_MS", "500"))  # 单位毫秒，0 = 全部告警
    SLOW_QUERY_MS = int(os.environ.get("BLOG_SLOW_QUERY_MS", "200"))  # 单位毫秒，0 = 全部记录

    AUTO_SCHEMA_MIGRATE = _env_bool("BLOG_AUTO_MIGRATE", "true")  # false = 手动模式
    ALLOW_SCHEMA_AHEAD = _env_bool("BLOG_ALLOW_SCHEMA_AHEAD", "false")  # 数据库版本高于程序版本时拒绝启动

    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None  # 令牌不设过期时间
    WTF_I18N_ENABLED = False

    SEARCH_KEYWORD_MAX_LEN = 100

    BABEL_DEFAULT_LOCALE = "zh_CN"
    BABEL_TRANSLATION_DIRECTORIES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "translations")
    BABEL_LOCALES = ("zh_CN", "en")

    INIT_ADMIN_USERNAME = os.environ.get("BLOG_INIT_ADMIN_USER", "admin")
    INIT_ADMIN_PASSWORD = os.environ.get("BLOG_INIT_ADMIN_PWD", "")

    PROXY_FIX_X_FOR = int(os.environ.get("BLOG_PROXY_XFOR", "0"))
    PROXY_FIX_X_PROTO = int(os.environ.get("BLOG_PROXY_XPROTO", "0"))
    PROXY_FIX_X_HOST = int(os.environ.get("BLOG_PROXY_XHOST", "0"))

    MAIL_HOST = os.environ.get("BLOG_MAIL_HOST", "")
    MAIL_PORT = int(os.environ.get("BLOG_MAIL_PORT", "587") or "587")
    MAIL_USER = os.environ.get("BLOG_MAIL_USER", "")
    MAIL_PASSWORD = os.environ.get("BLOG_MAIL_PASSWORD", "")
    MAIL_FROM = os.environ.get("BLOG_MAIL_FROM", "")
    MAIL_USE_SSL = _env_bool("BLOG_MAIL_USE_SSL", "false")
    MAIL_USE_TLS = _env_bool("BLOG_MAIL_USE_TLS", "true")
    RESET_TOKEN_MAX_AGE = int(os.environ.get("BLOG_RESET_TOKEN_MAX_AGE", "1800"))  # 单位秒

    # 模块级常量在此显式声明，供 app.config.from_object() 收集
    APP_VERSION: ClassVar[str] = APP_VERSION
    PAGE_SIZE: ClassVar[int] = PAGE_SIZE
    UPLOAD_ALLOWED_EXT: ClassVar[tuple[str, ...]] = UPLOAD_ALLOWED_EXT
    UPLOAD_ALLOWED_MIME: ClassVar[tuple[str, ...]] = UPLOAD_ALLOWED_MIME
    UPLOAD_MAX_SIZE: ClassVar[int] = UPLOAD_MAX_SIZE
    UPLOAD_BASE_NAME_LEN: ClassVar[int] = UPLOAD_BASE_NAME_LEN
    UPLOAD_MAX_WIDTH: ClassVar[int] = UPLOAD_MAX_WIDTH
    BANNER_MAX_WIDTH: ClassVar[int] = BANNER_MAX_WIDTH
    PIL_MAX_IMAGE_PIXELS: ClassVar[int] = PIL_MAX_IMAGE_PIXELS


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # SQLALCHEMY_DATABASE_URI 由下方 _resolve_db_uri_for_class 解析


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = _env_bool("BLOG_COOKIE_SECURE", "true")
    SQLALCHEMY_TRACK_MODIFICATIONS = False


def _prepare_sqlite_dir(abs_path: str) -> str:
    """确保 SQLite 库文件的父目录存在且可写，返回库文件绝对路径。"""
    directory = os.path.dirname(abs_path)
    if not directory:
        return abs_path
    try:
        os.makedirs(directory, exist_ok=True)
        # makedirs 不校验已存在目录的可写性，用一次真实写入探测
        with tempfile.NamedTemporaryFile(prefix=".sqlite_write_probe", dir=directory):
            pass
    except OSError as exc:
        raise RuntimeError(
            f"SQLite 库文件目录不可用: {directory}（{exc}）。"
            "Serverless 平台（Vercel / AWS Lambda）的代码目录是只读的，仅 /tmp 可写，"
            "无法按默认路径 data/blog.db 建库。请任选其一：\n"
            "  1) 生产推荐：改用外部 MySQL —— 设置 BLOG_DB_TYPE=mysql 与 BLOG_MYSQL_HOST / "
            "BLOG_MYSQL_USER / BLOG_MYSQL_PWD / BLOG_MYSQL_DB；\n"
            "  2) 仅演示/试跑：设置 BLOG_SQLITE_PATH=/tmp/blog.db（临时目录非持久化，"
            "实例重启或缩容后数据会丢失，多实例之间也不共享）。"
        ) from exc
    return abs_path


def _resolve_db_uri_for_class(cls):
    """解析数据库连接 URI，写入 cls 的 SQLALCHEMY_DATABASE_URI 与 SQLALCHEMY_ENGINE_OPTIONS。"""
    db_type = (os.environ.get("BLOG_DB_TYPE") or "sqlite").strip().lower()
    if db_type == "mysql":
        host = (os.environ.get("BLOG_MYSQL_HOST") or "").strip()
        user = (os.environ.get("BLOG_MYSQL_USER") or "").strip()
        pwd = os.environ.get("BLOG_MYSQL_PWD") or ""
        db_name = (os.environ.get("BLOG_MYSQL_DB") or "").strip()
        if not host or not user or not db_name:
            raise RuntimeError(
                "BLOG_DB_TYPE=mysql 但缺少必要连接字段,请检查 BLOG_MYSQL_HOST / "
                "BLOG_MYSQL_USER / BLOG_MYSQL_DB 环境变量。"
            )
        # 用户名与口令须编码后再拼接：口令含 @ : / # ? 等字符时会导致 URI 解析错位
        cls.SQLALCHEMY_DATABASE_URI = (
            f"mysql+pymysql://{quote_plus(user)}:{quote_plus(pwd)}@{host}/{db_name}?charset=utf8mb4"
        )
        cls.SQLALCHEMY_ENGINE_OPTIONS = {
            "connect_args": {
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION'",
            },
        }
        return
    abs_path = _prepare_sqlite_dir(os.path.abspath(os.environ.get("BLOG_SQLITE_PATH") or "data/blog.db"))
    cls.SQLALCHEMY_DATABASE_URI = "sqlite:///" + abs_path
    cls.SQLALCHEMY_ENGINE_OPTIONS = {}


_resolve_db_uri_for_class(DevelopmentConfig)
_resolve_db_uri_for_class(ProductionConfig)


class TestingConfig(Config):
    TESTING = True
    DEBUG = True
    WTF_CSRF_ENABLED = False  # 关闭 CSRF 校验
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    HOST_WHITELIST: ClassVar[list[str]] = []
    CANONICAL_URL = ""


config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}


def get_config():
    """按 BLOG_ENV 返回配置类；生产环境未配置会话密钥或仍为公开默认值时抛错。"""
    env = os.environ.get("BLOG_ENV", "development").lower()
    cls = config_map.get(env, config_map["default"])
    if cls is ProductionConfig:
        if not _RESOLVED_SECRET_KEY:
            raise RuntimeError(
                "生产环境必须设置 BLOG_SECRET_KEY 环境变量（或 BLOG_SECRET_KEY_FILE 指向的密钥文件）后再启动。"
                '生成命令: python -c "import secrets;print(secrets.token_hex(32))"'
            )
        if _RESOLVED_SECRET_KEY in INSECURE_DEFAULT_SECRET_KEYS:
            raise RuntimeError(
                "生产环境的 BLOG_SECRET_KEY 是仓库中公开的默认值，任何人都能据此伪造管理员登录态。"
                '请改为随机值: python -c "import secrets;print(secrets.token_hex(32))" '
                "（容器部署删除该环境变量即可，入口脚本会自动生成并持久化随机密钥）"
            )
    elif _RESOLVED_SECRET_KEY in INSECURE_DEFAULT_SECRET_KEYS:
        warnings.warn(
            "BLOG_SECRET_KEY 仍是仓库中公开的默认值，仅可用于本机调试；"
            "公网部署请改为随机值，否则可被伪造管理员登录态。",
            stacklevel=2,
        )
    return cls
