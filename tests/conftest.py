"""Pytest 公共 fixtures。

测试使用 TestingConfig（内存 SQLite + 关闭 CSRF），可重复运行互不影响。
"""

import logging
import os
import shutil
import tempfile

import pytest

# 在导入 app 之前设定测试环境变量
os.environ.setdefault("BLOG_ENV", "testing")
os.environ.setdefault("BLOG_INIT_ADMIN_USER", "admin")
os.environ.setdefault("BLOG_INIT_ADMIN_PWD", "admin123456")
# 测试用固定 SECRET_KEY，避免不同进程随机生成
os.environ.setdefault("BLOG_SECRET_KEY", "testing-secret-key-do-not-use-in-prod")

# 日志目录也必须在 config 导入前重定向：LOG_DIR 在 config.py 按绝对路径
# 计算，不随 project_root 重定向。不隔离的话每次跑全套测试，几百次
# create_app 产生的"初始管理员账号已创建"/http_request 会写进真实 logs/app.log。
_TEST_LOG_DIR = tempfile.mkdtemp(prefix="blog_test_logs_")
os.environ.setdefault("BLOG_LOG_DIR", _TEST_LOG_DIR)


@pytest.fixture(scope="session")
def _tmp_project_root():
    """会话级临时项目根：所有 uploads/backups 落盘重定向到这里，结束后清理。

    必须在 create_app 之前替换 app.utils.project_root —— 启动时的
    migrate_legacy_upload_dirs() 与请求中的 upload_dir() 都经它定位目录，
    否则测试上传的小图会写进仓库真实 uploads/（历史污染问题）。
    """
    tmp = tempfile.mkdtemp(prefix="blog_test_root_")
    yield tmp
    # 先关闭测试 app 挂在全局 logger 上的文件 handler：Windows 下句柄
    # 不释放，临时日志目录里的 app.log 会被锁定导致 rmtree 静默失败、
    # TEMP 中目录逐次堆积。
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

    # 全局重定向 project_root：upload_dir / 备份目录 / 上传文件存在性检查
    # 全部落到临时目录。各测试内更细粒度的 monkeypatch 会临时覆盖并自动还原。
    monkeypatch.setattr(utils, "project_root", lambda: _tmp_project_root)

    a = create_app("testing")

    with a.app_context():
        _db.create_all()
        # 初始化三张单行配置表 + 管理员
        from app.database import ensure_admin_exists, ensure_default_settings

        ensure_default_settings()
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
