import os

SECRET_KEY = os.environ.get("BLOG_SECRET_KEY", "blog_2026_secure_key_xyz123")
DEBUG = os.environ.get("BLOG_DEBUG", "True").lower() == "true"

# 数据库类型: "mysql" 或 "sqlite"
DB_TYPE = os.environ.get("BLOG_DB_TYPE", "sqlite")

# MySQL 配置（DB_TYPE = "mysql" 时生效）
MYSQL_HOST = os.environ.get("BLOG_MYSQL_HOST", "localhost")
MYSQL_USER = os.environ.get("BLOG_MYSQL_USER", "root")
MYSQL_PWD = os.environ.get("BLOG_MYSQL_PWD", "")
MYSQL_DB = os.environ.get("BLOG_MYSQL_DB", "flask_blog")

# SQLite 配置（DB_TYPE = "sqlite" 时生效）
SQLITE_PATH = "data/blog.db"

# 分页数量
PAGE_SIZE = int(os.environ.get("BLOG_PAGE_SIZE", "6"))

# 静态文件缓存（生产环境建议 43200，开发环境 0）
SEND_FILE_MAX_AGE = int(os.environ.get("BLOG_STATIC_MAX_AGE", "0"))

# 文件上传大小限制（16MB）
MAX_CONTENT_LENGTH = 16 * 1024 * 1024