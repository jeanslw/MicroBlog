import os

# 优先加载项目根目录 .env 文件（若存在），不强制依赖 python-dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # 未安装 python-dotenv 时静默跳过，仍可使用系统环境变量
    pass

# ── 安全配置 ────────────────────────────────────────────────
# SECRET_KEY 必须由环境变量提供，未设置时仅开发模式放行（生产环境强制中止）
_SECRET_ENV = os.environ.get("BLOG_SECRET_KEY")
if _SECRET_ENV:
    SECRET_KEY = _SECRET_ENV
else:
    if os.environ.get("BLOG_ENV") == "production":
        raise RuntimeError("生产环境 (BLOG_ENV=production) 必须设置 BLOG_SECRET_KEY 环境变量")
    # 开发模式回退：每次启动随机生成（重启后 session 失效，仅本地使用）
    import secrets as _secrets
    SECRET_KEY = _secrets.token_hex(32)

# DEBUG 默认关闭，避免 Werkzeug 调试器在生产环境暴露
DEBUG = os.environ.get("BLOG_DEBUG", "False").lower() == "true"

# ── 数据库 ─────────────────────────────────────────────────
# 数据库类型: "mysql" 或 "sqlite"
DB_TYPE = os.environ.get("BLOG_DB_TYPE", "sqlite")

# MySQL 配置（DB_TYPE = "mysql" 时生效）
MYSQL_HOST = os.environ.get("BLOG_MYSQL_HOST", "localhost")
MYSQL_USER = os.environ.get("BLOG_MYSQL_USER", "root")
MYSQL_PWD = os.environ.get("BLOG_MYSQL_PWD", "")
MYSQL_DB = os.environ.get("BLOG_MYSQL_DB", "flask_blog")

# SQLite 配置（DB_TYPE = "sqlite" 时生效）
SQLITE_PATH = os.environ.get("BLOG_SQLITE_PATH", "data/blog.db")

# ── 业务参数 ───────────────────────────────────────────────
# 分页数量
PAGE_SIZE = int(os.environ.get("BLOG_PAGE_SIZE", "6"))

# 静态文件缓存（生产环境建议 43200，开发环境 0）
SEND_FILE_MAX_AGE = int(os.environ.get("BLOG_STATIC_MAX_AGE", "0"))

# 文件上传大小限制（16MB）
MAX_CONTENT_LENGTH = 16 * 1024 * 1024

# ── Session 安全 ───────────────────────────────────────────
# 生产环境 (BLOG_ENV=production) 强制 Secure/SameSite
_IS_PROD = os.environ.get("BLOG_ENV") == "production"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = _IS_PROD
PERMANENT_SESSION_LIFETIME = 60 * 60 * 12  # 12 小时

# ── 初始管理员（仅 SQLite 首次建表写入） ───────────────────
INIT_ADMIN_USERNAME = os.environ.get("BLOG_INIT_ADMIN_USER", "admin")
INIT_ADMIN_PASSWORD = os.environ.get("BLOG_INIT_ADMIN_PWD", "")
