"""应用配置 —— Flask 标准的 Config 类模式。

通过环境变量 BLOG_ENV 切换:
- 未设置/development  -> DevelopmentConfig
- production          -> ProductionConfig
- testing             -> TestingConfig

所有配置通过 app.config.from_object() 加载,业务常量也写入 app.config,
其他模块读取时用 current_app.config['KEY'] 或直接 import 对应常量。
"""

import os
import secrets
from typing import ClassVar

# 优先加载项目根目录 .env（若存在），不强制依赖 python-dotenv
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    # python-dotenv 未安装时 .env 会被静默忽略,多 worker 下还会因随机
    # SECRET_KEY 导致登录/CSRF 随机失败。若根目录存在 .env 则明确告警,
    # 避免这种"配置写了却没生效"的隐蔽故障。
    import warnings

    if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")):
        warnings.warn(
            "检测到 .env 文件但未安装 python-dotenv,该文件不会被加载。"
            "请执行 pip install python-dotenv 后重启服务。",
            stacklevel=2,
        )


def _env_bool(name: str, default: str = "false") -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        value = default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _normalize_trusted_host(entry: str) -> str:
    """把白名单条目归一化为纯主机名：兼容完整 URL（http://host:port）与裸域名两种写法。

    统一去端口（IPv6 保留 [方括号] 形式），与请求 Host 的比对逻辑保持一致。
    """
    from urllib.parse import urlsplit

    entry = entry.strip().lower()
    if "://" in entry:
        entry = urlsplit(entry).netloc or ""
    # 去端口（IPv6 保留 [方括号] 形式）
    entry = entry.split("]", 1)[0] + "]" if entry.startswith("[") else entry.split(":", 1)[0]
    return entry


# ── 业务常量（不随环境变化，直接定义供模块导入） ───────────
# 应用版本（SemVer）。发布新版本时更新，须与 Git Tag 保持一致。
APP_VERSION = "1.3.4"

PAGE_SIZE = int(os.environ.get("BLOG_PAGE_SIZE", "6"))

# 文章/评论/上传校验
TITLE_MAX_LEN = 500
CAT_NAME_MAX_LEN = 60
SITE_NAME_MAX_LEN = 100
PASSWORD_MIN_LEN = 6
USERNAME_MAX_LEN = 50
COMMENT_MAX_LEN = 2000
REPLY_MAX_LEN = 2000

# 上传文件
UPLOAD_ALLOWED_EXT = ("jpg", "jpeg", "png", "gif")
UPLOAD_ALLOWED_MIME = ("image/jpeg", "image/png", "image/gif")
UPLOAD_MAX_SIZE = 10 * 1024 * 1024  # 10MB
UPLOAD_BASE_NAME_LEN = 100
UPLOAD_MAX_WIDTH = 1200
BANNER_MAX_WIDTH = 1920
PIL_MAX_IMAGE_PIXELS = 50_000_000  # Pillow 解压炸弹防护


class Config:
    """基类配置（所有环境共享）"""

    # ── Flask ───────────────────────────────────────────
    SECRET_KEY = os.environ.get("BLOG_SECRET_KEY") or secrets.token_hex(32)
    DEBUG = _env_bool("BLOG_DEBUG", "false")
    TESTING = False

    # ── 站点外链域名（防 Host 头注入） ────────────────────
    # 用于生成邮件重置链接、RSS/Atom 订阅源、sitemap 等绝对 URL。
    # 生产环境务必配置（如 https://blog.example.com），不依赖请求 Host 头，
    # 避免攻击者伪造 Host 头向管理员邮件投毒外站链接。
    # 留空时回退到 request.host_url（仅开发便捷，不推荐生产）。
    CANONICAL_URL = (os.environ.get("BLOG_CANONICAL_URL") or "").rstrip("/")
    # Host 白名单（逗号分隔，环境变量 BLOG_TRUSTED_HOSTS）。
    # 设置后，非白名单 Host 的请求将被拒绝（400）；留空表示不校验（仅开发便捷）。
    # 注意：配置键刻意不用 TRUSTED_HOSTS —— Flask 3.1 会原生消费该同名键，
    # 在请求上下文阶段（早于 before_request）直接拒绝，且无法为 /healthz 等
    # 容器健康探针按路径豁免。这里由应用在 before_request 自行校验。
    HOST_WHITELIST: ClassVar[list[str]] = [
        h
        for h in (
            _normalize_trusted_host(x)
            for x in (os.environ.get("BLOG_TRUSTED_HOSTS") or "").split(",")
        )
        if h
    ]

    # ── 安全响应头（app/__init__.py after_request 统一下发） ──
    # 单一事实来源：安全头随代码进版本库、有测试覆盖，与部署方式
    # （nginx/直连/Docker）无关。⚠️ 切勿再在 nginx add_header 重复配置 CSP ——
    # 浏览器对多份 CSP 取交集执行，配置稍有出入就会出现"莫名拦资源"。
    CSP_POLICY = (
        # default-src 兜底本站资源；图片/音视频放行外链
        # （媒体缺 media-src 会回退 'self'，导致文章外链音视频无法播放）
        "default-src 'self'; "
        "img-src 'self' data: https:; "
        "media-src 'self' https:; "
        # 内联样式/脚本为当前模板依赖，如需收紧可改 nonce 方案
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; "
        "frame-ancestors 'self'"
    )
    # 防盗链保护的静态路径前缀（对齐原 nginx valid_referers：空 Referer 放行、
    # 同源/白名单 Host 放行，其余 403）
    HOTLINK_PROTECTED_PREFIXES: ClassVar[tuple[str, ...]] = ("/static/banner/", "/static/uploads/")

    # ── Session / Cookie ────────────────────────────────
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # 本地明文 HTTP 调试可显式设置 BLOG_COOKIE_SECURE=false；生产默认仍为 true。
    SESSION_COOKIE_SECURE = _env_bool("BLOG_COOKIE_SECURE", "false")
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12  # 12 小时（秒）
    PERMANENT_SESSION_LIFETIME_DELTA = None  # 由 __init__.py 转 timedelta

    # ── 静态文件 ────────────────────────────────────────
    SEND_FILE_MAX_AGE_DEFAULT = int(os.environ.get("BLOG_STATIC_MAX_AGE", "0"))
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB（Flask 整体请求上限）

    # ── WTF ─────────────────────────────────────────────
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None  # 不设过期（避免长时间编辑后提交失败）
    WTF_I18N_ENABLED = False

    # ── Babel ───────────────────────────────────────────
    BABEL_DEFAULT_LOCALE = "zh_CN"
    # translations/ 位于项目根目录（config.py 所在目录），非 app/ 子目录
    BABEL_TRANSLATION_DIRECTORIES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "translations")
    BABEL_LOCALES = ("zh_CN", "en")

    # ── 初始管理员 ──────────────────────────────────────
    INIT_ADMIN_USERNAME = os.environ.get("BLOG_INIT_ADMIN_USER", "admin")
    INIT_ADMIN_PASSWORD = os.environ.get("BLOG_INIT_ADMIN_PWD", "")

    # ── 反向代理 ────────────────────────────────────────
    # 信任的反向代理层数（X-Forwarded-For / X-Forwarded-Proto）
    PROXY_FIX_X_FOR = int(os.environ.get("BLOG_PROXY_XFOR", "0"))
    PROXY_FIX_X_PROTO = int(os.environ.get("BLOG_PROXY_XPROTO", "0"))
    PROXY_FIX_X_HOST = int(os.environ.get("BLOG_PROXY_XHOST", "0"))

    # ── 邮件（找回密码） ────────────────────────────────
    MAIL_HOST = os.environ.get("BLOG_MAIL_HOST", "")
    MAIL_PORT = int(os.environ.get("BLOG_MAIL_PORT", "587") or "587")
    MAIL_USER = os.environ.get("BLOG_MAIL_USER", "")
    MAIL_PASSWORD = os.environ.get("BLOG_MAIL_PASSWORD", "")
    MAIL_FROM = os.environ.get("BLOG_MAIL_FROM", "")
    MAIL_USE_SSL = _env_bool("BLOG_MAIL_USE_SSL", "false")
    MAIL_USE_TLS = _env_bool("BLOG_MAIL_USE_TLS", "true")
    # 密码找回令牌有效期（秒）
    RESET_TOKEN_MAX_AGE = int(os.environ.get("BLOG_RESET_TOKEN_MAX_AGE", "1800"))


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "BLOG_SQLITE_PATH",
        "data/blog.db",
    ) and "sqlite:///" + os.path.abspath(os.environ.get("BLOG_SQLITE_PATH", "data/blog.db"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class ProductionConfig(Config):
    DEBUG = False
    # 生产默认强制 Secure Cookie；仅本地明文 HTTP 调试时通过环境变量显式关闭。
    SESSION_COOKIE_SECURE = _env_bool("BLOG_COOKIE_SECURE", "true")
    SQLALCHEMY_TRACK_MODIFICATIONS = False


# 在类外部预先计算并设置 SQLALCHEMY_DATABASE_URI（Flask-SQLAlchemy
# 通过 from_object 读取类属性）。
def _resolve_db_uri_for_class(cls):
    """解析数据库连接 URI。

    BLOG_DB_TYPE=mysql 时，若 host/user/db_name 等关键字段缺失则直接抛
    RuntimeError，禁止静默回退到 SQLite（避免数据写到意料之外的位置，
    导致备份/恢复走错分支、数据丢失等隐蔽故障）。
    """
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
        cls.SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{user}:{pwd}@{host}/{db_name}?charset=utf8mb4"
        cls.SQLALCHEMY_ENGINE_OPTIONS = {
            "connect_args": {
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION'",
            },
        }
        return
    path = os.environ.get("BLOG_SQLITE_PATH") or "data/blog.db"
    abs_path = os.path.abspath(path)
    # SQLite 引擎只创建库文件、不创建父目录，这里确保目录存在，
    # 避免全新部署（data/ 缺失）时首启报 unable to open database file。
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    cls.SQLALCHEMY_DATABASE_URI = "sqlite:///" + abs_path
    cls.SQLALCHEMY_ENGINE_OPTIONS = {}


_resolve_db_uri_for_class(DevelopmentConfig)
_resolve_db_uri_for_class(ProductionConfig)


class TestingConfig(Config):
    TESTING = True
    DEBUG = True
    WTF_CSRF_ENABLED = False  # 测试关闭 CSRF 方便 test_client
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # 测试环境封闭：不受开发者 .env 的 Host 白名单影响
    HOST_WHITELIST: ClassVar[list[str]] = []
    CANONICAL_URL = ""
    # 测试密钥由 tests/conftest.py 通过 BLOG_SECRET_KEY 环境变量注入,
    # 不再在代码中硬编码,避免 CI 密钥扫描误报。


# 配置字典
config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}


def get_config():
    """根据 BLOG_ENV 返回对应配置类。

    生产环境（ProductionConfig）若未显式设置 BLOG_SECRET_KEY 则直接报错，
    避免静默使用随机密钥导致登录态失效与加密字段无法解密。
    """
    env = os.environ.get("BLOG_ENV", "development").lower()
    cls = config_map.get(env, config_map["default"])
    if cls is ProductionConfig and not os.environ.get("BLOG_SECRET_KEY"):
        raise RuntimeError(
            "生产环境必须设置 BLOG_SECRET_KEY 环境变量后再启动。"
            "生成命令: python -c \"import secrets;print(secrets.token_hex(32))\""
        )
    return cls


# 模块级常量：供旧代码向后兼容（不应直接依赖）
Config.APP_VERSION = APP_VERSION
Config.PAGE_SIZE = PAGE_SIZE
Config.UPLOAD_ALLOWED_EXT = UPLOAD_ALLOWED_EXT
Config.UPLOAD_ALLOWED_MIME = UPLOAD_ALLOWED_MIME
Config.UPLOAD_MAX_SIZE = UPLOAD_MAX_SIZE
Config.UPLOAD_BASE_NAME_LEN = UPLOAD_BASE_NAME_LEN
Config.UPLOAD_MAX_WIDTH = UPLOAD_MAX_WIDTH
Config.BANNER_MAX_WIDTH = BANNER_MAX_WIDTH
Config.PIL_MAX_IMAGE_PIXELS = PIL_MAX_IMAGE_PIXELS
