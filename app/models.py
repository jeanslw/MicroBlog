"""SQLAlchemy 数据模型 —— 对齐现有数据库 schema。

设计原则：
1. 保持与 MySQL/init.sql 与历史 SQLite schema 字段一致,确保现有数据可继续使用
2. 表名、字段类型严格对齐
3. 不引入外键约束（原 schema 也无 FK 约束）,但关系映射用 ForeignKey 仅供 ORM 查询使用
"""

from flask_login import UserMixin
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import relationship

from app.extensions import db


class Admin(db.Model, UserMixin):
    __tablename__ = "admin"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), nullable=False, unique=True)
    password = Column(String(255), nullable=False)
    # 邮箱（用于找回密码，可空）
    email = Column(String(200), nullable=False, default="")

    def __repr__(self):
        return f"<Admin {self.username}>"

    def get_id(self):
        """Flask-Login 用,返回字符串 ID"""
        return str(self.id)


class Category(db.Model):
    __tablename__ = "category"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cat_name = Column(String(60), nullable=False, unique=True)
    tag_text = Column(String(60), default="")
    create_time = Column(String(50))

    articles = relationship("Article", back_populates="category")

    def __repr__(self):
        return f"<Category {self.cat_name}>"


class Article(db.Model):
    __tablename__ = "article"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False)
    # MySQL 用 MEDIUMTEXT(16MB) 支持长文,SQLite 用 TEXT（无长度限制）
    content = Column(Text().with_variant(MEDIUMTEXT(), "mysql"), nullable=False)
    status = Column(String(20), default="draft")
    create_time = Column(String(50))
    update_time = Column(String(50))
    vote_num = Column(Integer, default=0)
    is_pinned = Column(Boolean, default=False, nullable=False)
    category_id = Column(Integer, ForeignKey("category.id"))
    # SEO 元数据：描述/关键词（留空时发布自动生成）
    seo_description = Column(String(300), default="")
    seo_keywords = Column(String(300), default="")

    category = relationship("Category", back_populates="articles")
    comments = relationship("Comment", back_populates="article", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Article {self.id} {self.title!r}>"


class Comment(db.Model):
    __tablename__ = "comment"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(Integer, ForeignKey("article.id"))
    username = Column(String(50), default="游客")
    content = Column(Text, nullable=False)
    create_time = Column(String(50))

    article = relationship("Article", back_populates="comments")
    replies = relationship("Reply", back_populates="comment", cascade="all, delete-orphan")


class Reply(db.Model):
    __tablename__ = "reply"

    id = Column(Integer, primary_key=True, autoincrement=True)
    comment_id = Column(Integer, ForeignKey("comment.id"))
    username = Column(String(50), default="游客")
    content = Column(Text, nullable=False)
    create_time = Column(String(50))

    comment = relationship("Comment", back_populates="replies")


class Banner(db.Model):
    __tablename__ = "banner"

    id = Column(Integer, primary_key=True, autoincrement=True)
    img_path = Column(String(500), nullable=False)
    link_url = Column(String(500), default="")
    title = Column(String(100), default="")
    desc_text = Column(String(200), default="")
    sort = Column(Integer, default=0)
    create_time = Column(String(50))
    # 是否在首页轮播展示：True=展示中；False=已撤回（下架，保留记录可重新启用）
    is_active = Column(Boolean, nullable=False, default=True)


class SiteConfig(db.Model):
    __tablename__ = "site_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_name = Column(String(100), nullable=False, default="My Blog")
    favicon_path = Column(String(200), default="static/favicon.ico")
    # 网站 Logo 图片 URL（导航栏显示；上传时过大自动缩放）
    logo_path = Column(String(200), default="")
    # 背景风格：bg1~bg10 / vdysjx / bg13（内置图库）或 custom（自定义）
    bg_style = Column(String(50), default="bg1")
    # 自定义背景图片 URL（bg_style=custom 时生效）
    bg_custom = Column(String(500), default="")
    # 「关于我」内容：头像 URL（/static 上传或 http(s) 外链）/ 简介（纯文本,保留换行）/ 邮箱 / GitHub / 个人主页
    about_avatar = Column(String(500), default="")
    about_bio = Column(Text, default="")
    about_email = Column(String(200), default="")
    about_github = Column(String(200), default="")
    about_homepage = Column(String(200), default="")
    # 「关于我」昵称：作为作者署名显示在文章详情页与「关于我」页面
    about_nickname = Column(String(100), default="")
    # SMTP 邮件设置（后台可配置，优先于 .env 的 BLOG_MAIL_*；用于密码找回等邮件发送）
    mail_host = Column(String(200), default="")
    mail_port = Column(Integer, default=587)
    mail_user = Column(String(200), default="")
    mail_password = Column(String(200), default="")
    mail_from = Column(String(200), default="")
    mail_use_ssl = Column(Boolean, default=False, nullable=False)
    mail_use_tls = Column(Boolean, default=True, nullable=False)
    # 评论总开关：关闭后全站禁止新评论/回复（已有评论仍可查看）
    comments_enabled = Column(Boolean, default=True, nullable=False)
    # 侧边栏「栏目分类」样式：book=书本树形（可展开）/ classic=经典折叠箭头
    sidebar_style = Column(String(20), default="book", nullable=False)


class VoteLog(db.Model):
    __tablename__ = "vote_log"
    # 与 MySQL/init.sql 对齐:同一 IP 对同一文章只能点赞一次
    __table_args__ = (UniqueConstraint("article_id", "ip", name="uk_article_ip"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(Integer)
    ip = Column(String(100))
    create_time = Column(String(50))


class LoginAttempt(db.Model):
    """登录失败计数（跨 worker 共享,替代进程内字典）"""

    __tablename__ = "login_attempt"
    # 与 MySQL/init.sql 对齐:同一 IP + 用户名只有一条计数记录
    __table_args__ = (UniqueConstraint("ip", "username", name="uk_ip_username"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    ip = Column(String(100), nullable=False)
    username = Column(String(100), nullable=False)
    fail_count = Column(Integer, default=0, nullable=False)
    lock_until = Column(Integer, default=0, nullable=False)


class RateLimit(db.Model):
    """通用频率限制记录（按 IP + 动作），用于评论/回复/点赞/找回密码防刷。

    每次动作插入一条带时间戳的记录；统计窗口内的记录数判断是否超限。
    窗口外的旧记录由 check_rate_limit 惰性清理，避免表无限膨胀。
    """

    __tablename__ = "rate_limit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ip = Column(String(100), nullable=False, index=True)
    action = Column(String(50), nullable=False, index=True)
    create_time = Column(String(50), nullable=False)

