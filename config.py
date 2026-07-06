SECRET_KEY = "blog_2026_secure_key_xyz123"
DEBUG = True

# 数据库类型: "mysql" 或 "sqlite"
DB_TYPE = "sqlite"

# MySQL 配置（DB_TYPE = "mysql" 时生效）
MYSQL_HOST = "localhost"
MYSQL_USER = "root"
MYSQL_PWD = "123456"
MYSQL_DB = "flask_blog"

# SQLite 配置（DB_TYPE = "mysql" 时生效）
SQLITE_PATH = "data/blog.db"

PAGE_SIZE = 6