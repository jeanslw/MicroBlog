"""数据模型测试。"""
import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    Admin,
    Article,
    Banner,
    Category,
    Comment,
    LoginAttempt,
    Reply,
    SiteConfig,
    VoteLog,
)


def test_admin_password_hashing(db):
    """Admin 密码应使用 hash 存储"""
    from werkzeug.security import generate_password_hash
    pwd = "secret123"
    hashed = generate_password_hash(pwd)
    admin = Admin(username="tester", password=hashed)
    db.session.add(admin)
    db.session.commit()

    loaded = db.session.get(Admin, admin.id)
    assert loaded.username == "tester"
    # 哈希不是明文
    assert loaded.password != pwd
    assert loaded.password.startswith(("pbkdf2:", "scrypt:"))


def test_admin_get_id_str(app, admin_user):
    """Admin.get_id 应返回字符串"""
    assert isinstance(admin_user.get_id(), str)
    assert admin_user.get_id() == str(admin_user.id)


def test_category_unique_name(db):
    """栏目名应唯一"""
    db.session.add(Category(cat_name="重复栏目"))
    db.session.commit()
    db.session.add(Category(cat_name="重复栏目"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_article_default_status(db, category):
    """文章默认 status 应为 draft"""
    art = Article(title="x", content="y", category_id=category.id)
    db.session.add(art)
    db.session.commit()
    assert art.status == "draft"


def test_article_comment_cascade(db, article):
    """删除文章应级联删除评论"""
    c1 = Comment(article_id=article.id, username="u", content="c1",
                 create_time="2026-01-01 00:00:00")
    c2 = Comment(article_id=article.id, username="u", content="c2",
                 create_time="2026-01-01 00:00:00")
    db.session.add_all([c1, c2])
    db.session.commit()
    assert db.session.scalar(
        db.select(db.func.count(Comment.id)).where(Comment.article_id == article.id)
    ) == 2

    db.session.delete(article)
    db.session.commit()
    assert db.session.scalar(
        db.select(db.func.count(Comment.id)).where(Comment.article_id == article.id)
    ) == 0


def test_comment_reply_cascade(db, article):
    """删除评论应级联删除其回复"""
    c = Comment(article_id=article.id, username="u", content="c",
                create_time="2026-01-01 00:00:00")
    db.session.add(c)
    db.session.commit()
    r = Reply(comment_id=c.id, username="r", content="reply",
              create_time="2026-01-01 00:00:00")
    db.session.add(r)
    db.session.commit()

    db.session.delete(c)
    db.session.commit()
    assert db.session.get(Reply, r.id) is None


def test_banner_defaults(db):
    """Banner 默认值应正确"""
    b = Banner(img_path="/static/banner/x.jpg")
    db.session.add(b)
    db.session.commit()
    assert b.title == ""
    assert b.sort == 0


def test_site_config_default(db):
    """SiteConfig 默认站点名"""
    s = SiteConfig()
    db.session.add(s)
    db.session.commit()
    assert s.site_name == "我的博客"
    assert s.favicon_path == "static/favicon.ico"


def test_login_attempt_record(db):
    """LoginAttempt 记录可正常写入"""
    rec = LoginAttempt(ip="1.2.3.4", username="x", fail_count=3, lock_until=0)
    db.session.add(rec)
    db.session.commit()
    loaded = db.session.get(LoginAttempt, rec.id)
    assert loaded.fail_count == 3


def test_vote_log_record(db, article):
    """VoteLog 可写入"""
    v = VoteLog(article_id=article.id, ip="1.1.1.1",
                create_time="2026-01-01 00:00:00")
    db.session.add(v)
    db.session.commit()
    assert v.id is not None
