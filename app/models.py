"""SQLAlchemy 数据模型 —— 对齐现有数据库 schema。

设计原则：
1. 保持与 MySQL/init.sql 与历史 SQLite schema 字段一致,确保现有数据可继续使用
2. 表名、字段类型严格对齐
3. 不引入外键约束（原 schema 也无 FK 约束）,但关系映射用 ForeignKey 仅供 ORM 查询使用
"""

from flask_login import UserMixin
from sqlalchemy import Column, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import relationship

from app.extensions import db


class Admin(db.Model, UserMixin):
    __tablename__ = "admin"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), nullable=False, unique=True)
    password = Column(String(255), nullable=False)

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
    category_id = Column(Integer, ForeignKey("category.id"))

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


class SiteConfig(db.Model):
    __tablename__ = "site_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_name = Column(String(100), nullable=False, default="我的博客")
    favicon_path = Column(String(200), default="static/favicon.ico")
    # 网站 Logo 图片 URL（导航栏显示；上传时过大自动缩放）
    logo_path = Column(String(200), default="")
    # 背景风格：bg1~bg10 / vdysjx / bg13（内置图库）或 custom（自定义）
    bg_style = Column(String(50), default="bg1")
    # 自定义背景图片 URL（bg_style=custom 时生效）
    bg_custom = Column(String(500), default="")


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
