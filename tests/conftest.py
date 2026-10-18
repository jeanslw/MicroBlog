"""Pytest 公共 fixtures：使用 TestingConfig（内存 SQLite + 关闭 CSRF），各用例互不影响。"""

import logging
import os
import shutil
import tempfile

import pytest

# 在导入 app 之前设定测试环境变量
os.environ.setdefault("BLOG_ENV", "testing")
os.environ.setdefault("BLOG_INIT_ADMIN_USER", "admin")
os.environ.setdefault("BLOG_INIT_ADMIN_PWD", "admin123456")
# 测试用固定 SECRET_KEY，避免各进程随机生成
os.environ.setdefault("BLOG_SECRET_KEY", "testing-secret-key-do-not-use-in-prod")

# 强制覆盖会改变测试语义的开关；需要手动模式的用例在用例内自行改 app.config
os.environ["BLOG_AUTO_MIGRATE"] = "true"
os.environ["BLOG_ALLOW_SCHEMA_AHEAD"] = "false"

# LOG_DIR 不随 project_root 重定向，须在 config 导入前隔离
_TEST_LOG_DIR = tempfile.mkdtemp(prefix="blog_test_logs_")
os.environ.setdefault("BLOG_LOG_DIR", _TEST_LOG_DIR)


@pytest.fixture(scope="session")
def _tmp_project_root():
    """会话级临时项目根：所有 uploads / backups 写入重定向到此处，结束后清理。

    必须在 create_app 之前替换 app.utils.project_root，否则测试上传会写入仓库真实 uploads/。
    """
    tmp = tempfile.mkdtemp(prefix="blog_test_root_")
    yield tmp
    # 先关闭文件 handler，否则 Windows 下句柄未释放会让 rmtree 失败
    for logger_name in ("blog", "app", "blog.slowsql"):
        lg = logging.getLogger(logger_name)
        for h in list(lg.handlers):
            if getattr(h, "_blog_log_handler", False):
                h.close()
                lg.removeHandler(h)
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(_TEST_LOG_DIR, ignore_errors=True)


@pytest.fixture()
def app(_tmp_project_root, monkeypatch):
    """每个测试函数创建全新 app + 内存数据库"""
    import app.utils as utils
    from app import create_app
    from app.extensions import db as _db

    # 重定向 project_root，使上传 / 备份 / 资源检查全部落到临时目录
    monkeypatch.setattr(utils, "project_root", lambda: _tmp_project_root)

    a = create_app("testing")

    with a.app_context():
        _db.create_all()
        from app.database import ensure_admin_exists, ensure_default_settings, run_schema_migrations

        run_schema_migrations()
        ensure_default_settings()
        ensure_admin_exists()
        yield a
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def db(app):
    """数据库 session(绑定到 app)"""
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
    """以管理员身份登录 client,返回 client"""
    rv = client.post(
        "/admin/login",
        data={
            "username": "admin",
            "password": "admin123456",
        },
        follow_redirects=False,
    )
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
