"""站点配置行的读写一致性（P1 回归：后台改了配置前台不生效）。

全站只有一行站点配置。历史实现前台各模块用「取第一行」（SELECT ... LIMIT 1）
读取，后台（站点设置/关于我/邮件设置）用 ``db.session.get(SiteConfig, 1)`` 读取：
当库里唯一一行的主键不是 1（早期版本写入、人工导入的数据）时，两者读到的不是
同一行 —— 后台提示「保存成功」，前台却一直显示旧值。

现在读写都统一走 ``app.database.get_site_config()`` / ``get_or_create_site_config()``。
"""

from app.database import get_or_create_site_config, get_site_config
from app.extensions import fetch_global_context
from app.models import SiteConfig


def _replace_with_single_row(db, **fields):
    """清空 site_config，只插入一行主键非 1 的配置（模拟历史库）。"""
    fields.setdefault("favicon_path", "static/favicon.ico")
    db.session.execute(db.delete(SiteConfig))
    row = SiteConfig(**fields)
    db.session.add(row)
    db.session.commit()
    return row


def test_row_with_non_default_id_is_read_by_global_context(app, db):
    row = _replace_with_single_row(db, id=42, site_name="唯一一行", bg_style="bg7")

    assert get_site_config().id == row.id
    ctx = fetch_global_context()
    assert ctx["site_name"] == "唯一一行"
    assert ctx["site_bg_style"] == "bg7"


def test_public_pages_show_the_same_row(client, db, article):
    _replace_with_single_row(db, id=7, site_name="同源站点", about_nickname="昵称X")

    # 首页站点名（fetch_global_context）、文章详情页作者署名、订阅源站点名
    assert "同源站点" in client.get("/").get_data(as_text=True)
    assert "昵称X" in client.get(f"/article/{article.id}").get_data(as_text=True)
    assert "同源站点" in client.get("/feed").get_data(as_text=True)


def test_admin_site_setting_reads_and_updates_that_row(login_admin, db):
    _replace_with_single_row(db, id=9, site_name="后台目标行")

    html = login_admin.get("/admin/site_setting").get_data(as_text=True)
    assert "后台目标行" in html

    rv = login_admin.post("/admin/site_setting", data={"site_name": "改后名称"}, follow_redirects=False)
    assert rv.status_code == 302
    # 写回的必须是同一行，而不是新建的 id=1
    row = db.session.get(SiteConfig, 9)
    assert row.site_name == "改后名称"
    assert db.session.scalar(db.select(db.func.count(SiteConfig.id))) == 1


def test_get_or_create_never_creates_a_second_row(app, db):
    row = _replace_with_single_row(db, id=13, site_name="既有行")

    assert get_or_create_site_config().id == row.id
    assert db.session.scalar(db.select(db.func.count(SiteConfig.id))) == 1


def test_get_or_create_creates_default_row_when_missing(app, db):
    db.session.execute(db.delete(SiteConfig))
    db.session.commit()

    row = get_or_create_site_config()
    assert row.id == 1
    assert row.site_name == "My Blog"
