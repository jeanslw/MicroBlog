"""轻量迁移失败进维护、孤儿行/单行配置表清理、GIF 帧数上限、文章编辑图片清理."""

import io
import os

import pytest
from PIL import Image
from sqlalchemy import func

import app.database as database_mod
from app.utils import ImageProcessError, process_and_save_image, upload_dir


def test_init_db_returns_failed_steps(app, db, monkeypatch):
    """轻量迁移失败时 init_db 返回失败步骤名列表"""

    def boom():
        raise RuntimeError("alter failed")

    monkeypatch.setattr(database_mod, "_migrate_admin", boom)
    assert database_mod.init_db() == ["boom"]


def test_light_failure_enters_maintenance(monkeypatch):
    """启动时轻量迁移失败:站点进入维护模式,业务请求 503"""

    def boom():
        raise RuntimeError("alter failed")

    monkeypatch.setattr(database_mod, "_migrate_admin", boom)
    from app import create_app

    a = create_app("testing")
    assert a.config["SCHEMA_UPGRADE_PENDING"] is True
    assert a.config["LIGHT_MIGRATE_FAILED"] is True
    client = a.test_client()
    assert client.get("/").status_code == 503


def test_light_failure_gate_does_not_auto_clear(monkeypatch):
    """轻量迁移失败的维护状态不得因无待迁移版本而自动解除"""

    def boom():
        raise RuntimeError("alter failed")

    monkeypatch.setattr(database_mod, "_migrate_admin", boom)
    from app import create_app

    a = create_app("testing")
    client = a.test_client()
    for _ in range(2):
        assert client.get("/").status_code == 503
    assert a.config["LIGHT_MIGRATE_FAILED"] is True


def test_migrate_post_clears_light_failure(app, db, monkeypatch, login_admin):
    """迁移页重跑成功后解除维护标志"""
    app.config["SCHEMA_UPGRADE_PENDING"] = True
    app.config["LIGHT_MIGRATE_FAILED"] = True

    rv = login_admin.post("/admin/migrate", follow_redirects=False)

    assert rv.status_code == 302
    assert app.config["LIGHT_MIGRATE_FAILED"] is False
    assert app.config["SCHEMA_UPGRADE_PENDING"] is False


def test_migrate_post_keeps_pending_on_light_failure(app, db, monkeypatch, login_admin):
    """迁移页重跑仍失败时维持维护标志并提示失败步骤"""

    def boom():
        raise RuntimeError("alter failed")

    monkeypatch.setattr(database_mod, "_migrate_admin", boom)
    app.config["SCHEMA_UPGRADE_PENDING"] = True
    app.config["LIGHT_MIGRATE_FAILED"] = True

    rv = login_admin.post("/admin/migrate", follow_redirects=True)

    assert rv.status_code == 200
    assert app.config["LIGHT_MIGRATE_FAILED"] is True
    assert app.config["SCHEMA_UPGRADE_PENDING"] is True


def test_orphan_rows_cleaned(app, db):
    """悬挂的评论/回复/点赞行启动时清理"""
    from app.models import Article, Comment, Reply, VoteLog
    from app.timeutil import utc_now_str

    art = Article(title="t", content="c", status="publish", create_time=utc_now_str())
    db.session.add(art)
    db.session.commit()
    db.session.add(Comment(article_id=art.id, content="ok", create_time=utc_now_str()))
    db.session.add(Comment(article_id=99999, content="orphan", create_time=utc_now_str()))
    db.session.add(Reply(comment_id=99999, content="orphan", create_time=utc_now_str()))
    db.session.add(VoteLog(article_id=99999, ip="1.1.1.1", create_time=utc_now_str()))
    db.session.commit()

    assert database_mod.init_db() == []
    assert db.session.scalar(db.select(func.count(Comment.id))) == 1
    assert db.session.scalar(db.select(func.count(Reply.id))) == 0
    assert db.session.scalar(db.select(func.count(VoteLog.id))) == 0


def test_single_row_dedupe(app, db):
    """单行配置表多余行清理,保留最小 id 行"""
    from app.models import SiteSetting

    db.session.add(SiteSetting(id=5, site_name="ghost"))
    db.session.commit()
    assert db.session.scalar(db.select(func.count(SiteSetting.id))) == 2

    assert database_mod.init_db() == []
    rows = db.session.scalars(db.select(SiteSetting)).all()
    assert len(rows) == 1
    assert rows[0].id == 1


def _gif_bytes(n_frames: int) -> io.BytesIO:
    frames = [Image.new("RGB", (20, 20), (i * 80, 10, 10)) for i in range(n_frames)]
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    buf.seek(0)
    return buf


def test_gif_frame_limit_rejects(app, tmp_path):
    """GIF 帧数超上限时拒绝处理"""
    with pytest.raises(ImageProcessError):
        process_and_save_image(_gif_bytes(3), str(tmp_path / "a.gif"), "gif", gif_max_frames=2)


def test_gif_within_limit_keeps_frames(app, tmp_path):
    """未超上限的 GIF 正常保存且帧数完整"""
    out = tmp_path / "a.gif"
    process_and_save_image(_gif_bytes(3), str(out), "gif", gif_max_frames=200)
    with Image.open(out) as im:
        assert getattr(im, "n_frames", 1) == 3


def test_article_edit_cleans_removed_image(app, db, login_admin):
    """编辑文章移除图片后,不再被引用的文件被清理"""
    save_dir = upload_dir("image")
    os.makedirs(save_dir, exist_ok=True)
    name = "edit_clean_test.jpg"
    path = os.path.join(save_dir, name)
    with open(path, "wb") as f:
        f.write(b"fake")
    from app.models import Article
    from app.timeutil import utc_now_str

    art = Article(
        title="t",
        content=f'<p><img src="/uploads/image/{name}"></p>',
        status="publish",
        create_time=utc_now_str(),
    )
    db.session.add(art)
    db.session.commit()

    rv = login_admin.post(
        f"/article/edit/{art.id}",
        data={"title": "t2", "content": "<p>no image</p>", "status": "publish", "category_id": 0},
        follow_redirects=True,
    )

    assert rv.status_code == 200
    assert not os.path.exists(path)


def test_article_edit_keeps_image_still_referenced(app, db, login_admin):
    """图片仍被其他文章引用时不清理"""
    save_dir = upload_dir("image")
    os.makedirs(save_dir, exist_ok=True)
    name = "edit_keep_test.jpg"
    path = os.path.join(save_dir, name)
    with open(path, "wb") as f:
        f.write(b"fake")
    from app.models import Article
    from app.timeutil import utc_now_str

    content = f'<p><img src="/uploads/image/{name}"></p>'
    art = Article(title="b", content=content, status="publish", create_time=utc_now_str())
    db.session.add(Article(title="a", content=content, status="publish", create_time=utc_now_str()))
    db.session.add(art)
    db.session.commit()

    rv = login_admin.post(
        f"/article/edit/{art.id}",
        data={"title": "b2", "content": "<p>no image</p>", "status": "publish", "category_id": 0},
        follow_redirects=True,
    )

    assert rv.status_code == 200
    assert os.path.exists(path)
