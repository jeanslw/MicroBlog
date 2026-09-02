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

# 优先加载项目根目录 .env（若存在），不强制依赖 python-dotenv
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _env_bool(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


# ── 业务常量（不随环境变化，直接定义供模块导入） ───────────
# 应用版本（SemVer）。发布新版本时更新，须与 Git Tag 保持一致。
APP_VERSION = "1.3.0"

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

    # ── Session / Cookie ────────────────────────────────
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
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


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "BLOG_SQLITE_PATH",
        "data/blog.db",
    ) and "sqlite:///" + os.path.abspath(os.environ.get("BLOG_SQLITE_PATH", "data/blog.db"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True  # 生产强制 Secure Cookie
    SQLALCHEMY_TRACK_MODIFICATIONS = False


# 在类外部预先计算并设置 SQLALCHEMY_DATABASE_URI（Flask-SQLAlchemy
# 通过 from_object 读取类属性）。
def _resolve_db_uri_for_class(cls):
    db_type = os.environ.get("BLOG_DB_TYPE", "sqlite")
    if db_type == "mysql":
        host = os.environ.get("BLOG_MYSQL_HOST", "localhost")
        user = os.environ.get("BLOG_MYSQL_USER", "root")
        pwd = os.environ.get("BLOG_MYSQL_PWD", "")
        db = os.environ.get("BLOG_MYSQL_DB", "flask_blog")
        cls.SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{user}:{pwd}@{host}/{db}?charset=utf8mb4"
        # MySQL 连接建立时显式启用严格模式,确保部署到外部 MySQL（非 Docker,
        # 服务端可能未设 sql-mode）时也按严格模式运行,避免静默截断/隐式转换。
        # 仅在 MySQL 方言下注入 connect_args,SQLite 不受影响。
        cls.SQLALCHEMY_ENGINE_OPTIONS = {
            "connect_args": {
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION'",
            },
        }
    else:
        path = os.environ.get("BLOG_SQLITE_PATH", "data/blog.db")
        cls.SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.abspath(path)


_resolve_db_uri_for_class(DevelopmentConfig)
_resolve_db_uri_for_class(ProductionConfig)


class TestingConfig(Config):
    TESTING = True
    DEBUG = True
    WTF_CSRF_ENABLED = False  # 测试关闭 CSRF 方便 test_client
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
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
    """根据 BLOG_ENV 返回对应配置类"""
    env = os.environ.get("BLOG_ENV", "development").lower()
    return config_map.get(env, config_map["default"])


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
