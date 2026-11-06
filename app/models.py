"""SQLAlchemy 数据模型 -- 与 MySQL/init.sql 建出的结构一致.

字段类型与默认值、索引、唯一约束、表选项都由本模块定义;init.sql 是同一结构的
手动建表脚本.已有库缺失的索引由 database.py 启动时按模型补齐.
"""

from flask_login import UserMixin
from sqlalchemy import Boolean, Column, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import relationship
from sqlalchemy.sql.schema import DefaultClause

from app.extensions import db
from app.timeutil import DEFAULT_TIMEZONE

MYSQL_TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


class Admin(db.Model, UserMixin):
    __tablename__ = "admin"
    __table_args__ = (UniqueConstraint("username", name="uk_username"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), nullable=False)
    password = Column(String(255), nullable=False)
    email = Column(String(200), nullable=False, default="")
    token_version = Column(Integer, nullable=False, default=0)

    def __repr__(self):
        return f"<Admin {self.username}>"

    def get_id(self):
        """Flask-Login 用:ID + 令牌版本号;改密/重置密码后旧会话自动失效."""
        return f"{self.id}:{self.token_version}"


class Category(db.Model):
    __tablename__ = "category"
    __table_args__ = (UniqueConstraint("cat_name", name="uk_cat_name"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    cat_name = Column(String(60), nullable=False)
    tag_text = Column(String(60), default="")
    create_time = Column(String(50))

    articles = relationship(
        "Article",
        back_populates="category",
        primaryjoin="Category.id == Article.category_id",
        foreign_keys="[Article.category_id]",
    )

    def __repr__(self):
        return f"<Category {self.cat_name!r}>"


class Article(db.Model):
    __tablename__ = "article"
    __table_args__ = (
        Index("idx_status", "status"),
        Index("idx_category_id", "category_id"),
        Index("idx_create_time", "create_time"),
        Index("idx_status_cat_time", "status", "category_id", "create_time"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False)
    # MySQL 用 MEDIUMTEXT(16MB) 支持长文,SQLite 用 TEXT(无长度限制)
    content = Column(Text().with_variant(MEDIUMTEXT(), "mysql"), nullable=False)
    status = Column(String(20), default="draft")
    create_time = Column(String(50))
    update_time = Column(String(50))
    vote_num = Column(Integer, default=0)
    is_pinned = Column(Boolean, default=False, nullable=False)
    category_id = Column(Integer)
    seo_description = Column(String(300), nullable=False, default="")
    seo_keywords = Column(String(300), nullable=False, default="")

    category = relationship(
        "Category",
        back_populates="articles",
        primaryjoin="Article.category_id == Category.id",
        foreign_keys="[Article.category_id]",
    )
    comments = relationship(
        "Comment",
        back_populates="article",
        primaryjoin="Article.id == Comment.article_id",
        foreign_keys="[Comment.article_id]",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<Article {self.id} {self.title!r}>"


class Comment(db.Model):
    __tablename__ = "comment"
    __table_args__ = (Index("idx_article_id", "article_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(Integer)
    username = Column(String(50), default="游客")
    content = Column(Text, nullable=False)
    create_time = Column(String(50))

    article = relationship(
        "Article",
        back_populates="comments",
        primaryjoin="Comment.article_id == Article.id",
        foreign_keys="[Comment.article_id]",
    )
    replies = relationship(
        "Reply",
        back_populates="comment",
        primaryjoin="Comment.id == Reply.comment_id",
        foreign_keys="[Reply.comment_id]",
        cascade="all, delete-orphan",
    )


class Reply(db.Model):
    __tablename__ = "reply"
    __table_args__ = (Index("idx_comment_id", "comment_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    comment_id = Column(Integer)
    username = Column(String(50), default="游客")
    content = Column(Text, nullable=False)
    create_time = Column(String(50))

    comment = relationship(
        "Comment",
        back_populates="replies",
        primaryjoin="Reply.comment_id == Comment.id",
        foreign_keys="[Reply.comment_id]",
    )


class Banner(db.Model):
    __tablename__ = "banner"

    id = Column(Integer, primary_key=True, autoincrement=True)
    img_path = Column(String(500), nullable=False)
    link_url = Column(String(500), default="")
    title = Column(String(100), default="")
    desc_text = Column(String(200), default="")
    sort = Column(Integer, default=0)
    create_time = Column(String(50))
    update_time = Column(String(50))
    is_active = Column(Boolean, nullable=False, default=True)


class SiteSetting(db.Model):
    """站点设置:站点名/图标/Logo/背景/侧边栏/评论开关/订阅源开关."""

    __tablename__ = "site_setting"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_name = Column(String(100), nullable=False, default="My Blog")
    favicon_path = Column(String(200), default="static/favicon.ico")
    logo_path = Column(String(200), default="")
    bg_style = Column(String(50), default="bg1")
    bg_custom = Column(String(500), default="")
    comments_enabled = Column(Boolean, default=True, nullable=False)
    rss_enabled = Column(Boolean, default=True, nullable=False)
    atom_enabled = Column(Boolean, default=True, nullable=False)
    sidebar_style = Column(String(20), default="book", nullable=False)


class MailSetting(db.Model):
    """SMTP 邮件设置:保留兼容旧库;当前 SMTP 配置由 system_settings 表提供."""

    __tablename__ = "mail_setting"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mail_host = Column(String(200), default="")
    mail_port = Column(Integer, default=587)
    mail_user = Column(String(200), default="")
    mail_password = Column(String(200), default="")
    mail_from = Column(String(200), default="")
    mail_use_ssl = Column(Boolean, default=False, nullable=False)
    mail_use_tls = Column(Boolean, default=True, nullable=False)


class SystemSetting(db.Model):
    """系统设置:时区、运行时参数与 SMTP 邮件配置.

    未配置的运行时项回退到环境变量,Email 配置只从本表读取.
    """

    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timezone = Column(String(100), nullable=False, default=DEFAULT_TIMEZONE)
    follow_browser_tz = Column(Boolean, nullable=False, default=True)
    page_size = Column(Integer)
    log_level = Column(String(20), default="")
    log_format = Column(String(20), default="")
    slow_request_ms = Column(Integer)
    slow_query_ms = Column(Integer)
    static_max_age = Column(Integer)
    session_lifetime = Column(Integer)
    reset_token_max_age = Column(Integer)
    auto_schema_migrate = Column(Boolean)
    allow_schema_ahead = Column(Boolean)
    cookie_secure = Column(Boolean)
    mail_host = Column(String(200), default="")
    mail_port = Column(Integer, default=587)
    mail_user = Column(String(200), default="")
    mail_password = Column(String(200), default="")
    mail_from = Column(String(200), default="")
    mail_use_ssl = Column(Boolean, default=False, nullable=False)
    mail_use_tls = Column(Boolean, default=True, nullable=False)


class AboutProfile(db.Model):
    """「关于我」博主资料:前台关于页 + 文章署名."""

    __tablename__ = "about_profile"

    id = Column(Integer, primary_key=True, autoincrement=True)
    about_avatar = Column(String(500), default="")
    about_bio = Column(Text, default="")
    about_email = Column(String(200), default="")
    about_github = Column(String(200), default="")
    about_homepage = Column(String(200), default="")
    about_nickname = Column(String(100), default="")


class VoteLog(db.Model):
    __tablename__ = "vote_log"
    __table_args__ = (UniqueConstraint("article_id", "ip", name="uk_article_ip"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(Integer)
    ip = Column(String(100))
    create_time = Column(String(50))


class LoginAttempt(db.Model):
    """登录失败计数(跨 worker 共享,替代进程内字典)"""

    __tablename__ = "login_attempt"
    __table_args__ = (UniqueConstraint("ip", "username", name="uk_ip_username"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    ip = Column(String(100), nullable=False)
    username = Column(String(100), nullable=False)
    fail_count = Column(Integer, default=0, nullable=False)
    lock_until = Column(Integer, default=0, nullable=False)
    update_time = Column(String(50))


class RateLimit(db.Model):
    """通用频率限制记录(按 IP + 动作),用于评论/回复/点赞/找回密码防刷."""

    __tablename__ = "rate_limit"
    __table_args__ = (
        Index("idx_ip_action", "ip", "action"),
        Index("idx_action_time", "action", "create_time"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ip = Column(String(100), nullable=False)
    action = Column(String(50), nullable=False)
    create_time = Column(String(50), nullable=False)


class SchemaVersion(db.Model):
    """数据库 schema 版本履历(每行一次戳记,version 为真实发布号主键)."""

    __tablename__ = "schema_version"

    version = Column(String(20), primary_key=True)
    applied_time = Column(String(50))
    note = Column(String(255), nullable=False, default="")


def _align_schema():
    """把列的 Python 默认值写入数据库默认值，并统一 MySQL 表选项。"""
    for table in db.metadata.tables.values():
        table.kwargs.update(MYSQL_TABLE_OPTIONS)
        for column in table.columns:
            if column.server_default is not None or column.default is None:
                continue
            if isinstance(column.type, Text):
                continue
            value = column.default.arg
            if isinstance(value, bool):
                literal = "1" if value else "0"
            elif isinstance(value, int):
                literal = str(value)
            elif isinstance(value, str):
                literal = "'" + value.replace("'", "''") + "'"
            else:
                continue
            column.server_default = DefaultClause(text(literal))


_align_schema()
