"""Pytest 公共 fixtures。

测试使用 TestingConfig（内存 SQLite + 关闭 CSRF），可重复运行互不影响。
"""
import os
import tempfile

import pytest

# 在导入 app 之前设定测试环境变量
os.environ.setdefault("BLOG_ENV", "testing")
os.environ.setdefault("BLOG_INIT_ADMIN_USER", "admin")
os.environ.setdefault("BLOG_INIT_ADMIN_PWD", "admin123456")
# 测试用固定 SECRET_KEY，避免不同进程随机生成
os.environ.setdefault("BLOG_SECRET_KEY", "testing-secret-key-do-not-use-in-prod")


@pytest.fixture(scope="session")
def _tmp_uploads_dir():
    """会话级临时上传目录，测试结束自动清理"""
    tmp = tempfile.mkdtemp(prefix="blog_test_uploads_")
    return tmp


@pytest.fixture()
def app(_tmp_uploads_dir):
    """每个测试函数创建全新 app + 内存数据库"""
    from app import create_app
    from app.extensions import db as _db

    a = create_app("testing")
    # 指向临时目录避免污染 static/uploads
    a.config["UPLOAD_FOLDER"] = _tmp_uploads_dir

    with a.app_context():
        _db.create_all()
        # 初始化站点配置 + 管理员
        from app.database import ensure_admin_exists, ensure_site_config
        ensure_site_config()
        ensure_admin_exists()
        yield a
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def db(app):
    """数据库 session（绑定到 app）"""
    from app.extensions import db as _db
    return _db


@pytest.fixture()
def client(app):
    """Flask 测试客户端"""
    return app.test_client()


@pytest.fixture()
def runner(app):
    """Flask CLI runner"""
    return app.test_cli_runner()


@pytest.fixture()
def admin_user(db):
    """返回已创建的管理员对象"""
    from app.models import Admin
    return db.session.scalar(db.select(Admin).filter_by(username="admin"))


@pytest.fixture()
def login_admin(client, admin_user):
    """以管理员身份登录 client，返回 client"""
    rv = client.post("/admin/login", data={
        "username": "admin",
        "password": "admin123456",
    }, follow_redirects=False)
    assert rv.status_code in (302, 200), f"登录失败: {rv.status_code}"
    return client


@pytest.fixture()
def category(db):
    """创建一个示例栏目"""
    from app.models import Category
    cat = Category(cat_name="测试栏目", tag_text="test", create_time="2026-01-01 00:00:00")
    db.session.add(cat)
    db.session.commit()
    return cat


@pytest.fixture()
def article(db, category):
    """创建一篇已发布文章"""
    from app.models import Article
    art = Article(
        title="测试文章标题",
        content="<p>这是测试文章的 <strong>正文</strong> 内容。</p>",
        status="publish",
        category_id=category.id,
        create_time="2026-01-01 00:00:00",
        update_time="2026-01-01 00:00:00",
        vote_num=0,
    )
    db.session.add(art)
    db.session.commit()
    return art


@pytest.fixture()
def draft(db, category):
    """创建一篇草稿"""
    from app.models import Article
    art = Article(
        title="草稿文章",
        content="<p>草稿正文</p>",
        status="draft",
        category_id=category.id,
        create_time="2026-01-01 00:00:00",
        update_time="2026-01-01 00:00:00",
        vote_num=0,
    )
    db.session.add(art)
    db.session.commit()
    return art
