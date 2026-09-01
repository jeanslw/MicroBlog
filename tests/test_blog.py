"""博客文章与栏目功能测试。"""

from app.models import Article, Category


def test_index_empty(client):
    """无文章时首页应展示空状态"""
    rv = client.get("/")
    assert rv.status_code == 200
    assert "暂无公开文章".encode() in rv.data


def test_index_shows_article(client, article):
    """首页应展示已发布文章"""
    rv = client.get("/")
    assert rv.status_code == 200
    assert article.title.encode("utf-8") in rv.data


def test_article_detail(client, article):
    """文章详情页应可访问"""
    rv = client.get(f"/article/{article.id}")
    assert rv.status_code == 200
    assert article.title.encode("utf-8") in rv.data


def test_article_detail_not_found(client, db):
    """不存在的文章应重定向首页并 flash 提示"""
    rv = client.get("/article/99999", follow_redirects=False)
    assert rv.status_code == 302


def test_category_filter(client, article, category):
    """栏目筛选应只展示对应文章"""
    rv = client.get(f"/category/{category.id}")
    assert rv.status_code == 200
    assert article.title.encode("utf-8") in rv.data


def test_category_invalid_id(client):
    """非整数栏目 ID 应返回 404（路由 <int:cid> 不匹配）"""
    rv = client.get("/category/abc")
    assert rv.status_code == 404


def test_pagination_param(client, article):
    """page 参数异常值应容错"""
    for p in ["0", "-1", "abc", "9999"]:
        rv = client.get(f"/?page={p}")
        assert rv.status_code == 200


def test_drafts_requires_login(client):
    """草稿箱需登录"""
    rv = client.get("/drafts", follow_redirects=False)
    assert rv.status_code == 302


def test_drafts_shows_drafts(login_admin, draft, article):
    """草稿箱只展示 draft 文章"""
    rv = login_admin.get("/drafts")
    assert rv.status_code == 200
    assert draft.title.encode("utf-8") in rv.data


def test_article_new_form(login_admin, category):
    """新建文章表单可访问，且提供 Markdown 文件上传入口"""
    rv = login_admin.get("/article/new")
    assert rv.status_code == 200
    assert "新建文章".encode() in rv.data
    assert b"upload_md_btn" in rv.data
    assert b'accept=".md,.markdown,text/markdown,text/x-markdown,text/plain"' in rv.data


def test_article_new_publish(login_admin, db, category):
    """发布公开文章后应出现在首页"""
    rv = login_admin.post(
        "/article/new",
        data={
            "title": "发布测试文章",
            "content": "<p>正文内容</p>",
            "status": "publish",
            "category_id": category.id,
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302

    # 应出现在首页
    rv = login_admin.get("/")
    assert "发布测试文章".encode() in rv.data


def test_article_new_draft(login_admin, db, category):
    """存草稿不应出现在首页"""
    rv = login_admin.post(
        "/article/new",
        data={
            "title": "草稿隐藏测试",
            "content": "<p>草稿</p>",
            "status": "draft",
            "category_id": 0,
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302

    # 不应出现在首页
    rv = login_admin.get("/")
    assert "草稿隐藏测试".encode() not in rv.data


def test_article_new_requires_login(client):
    """未登录不能新建文章"""
    rv = client.post(
        "/article/new",
        data={
            "title": "x",
            "content": "y",
            "status": "publish",
            "category_id": 0,
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302
    assert "/login" in rv.headers.get("Location", "")


def test_article_new_missing_title(login_admin):
    """缺少标题应校验失败"""
    rv = login_admin.post(
        "/article/new",
        data={
            "title": "",
            "content": "正文",
            "status": "draft",
            "category_id": 0,
        },
        follow_redirects=False,
    )
    # 校验失败留在表单页
    assert rv.status_code == 200


def test_article_edit(login_admin, article, category):
    """编辑文章表单可访问"""
    rv = login_admin.get(f"/article/edit/{article.id}")
    assert rv.status_code == 200
    assert article.title.encode("utf-8") in rv.data


def test_article_edit_not_found(login_admin):
    """编辑不存在的文章应重定向"""
    rv = login_admin.get("/article/edit/99999", follow_redirects=False)
    assert rv.status_code == 302


def test_article_edit_save(login_admin, article, category, db):
    """编辑后内容应更新"""
    rv = login_admin.post(
        f"/article/edit/{article.id}",
        data={
            "title": "已修改标题",
            "content": "<p>新内容</p>",
            "status": "publish",
            "category_id": category.id,
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302

    db.session.refresh(article)
    assert article.title == "已修改标题"


def test_article_del(login_admin, article, db):
    """删除文章后应从列表消失"""
    aid = article.id
    rv = login_admin.post(f"/article/del/{aid}", follow_redirects=False)
    assert rv.status_code == 302
    assert db.session.get(Article, aid) is None


def test_article_del_not_found(login_admin):
    """删除不存在的文章应重定向"""
    rv = login_admin.post("/article/del/99999", follow_redirects=False)
    assert rv.status_code == 302


def test_article_del_requires_login(client, article):
    """未登录不能删除文章"""
    rv = client.post(f"/article/del/{article.id}", follow_redirects=False)
    assert rv.status_code == 302
    assert "/login" in rv.headers.get("Location", "")


def test_add_category_success(login_admin, db):
    """新增栏目应成功"""
    rv = login_admin.post(
        "/category/add",
        data={
            "cat_name": "新栏目",
            "tag_text": "tag",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302
    cat = db.session.scalar(db.select(Category).filter_by(cat_name="新栏目"))
    assert cat is not None


def test_add_category_duplicate(login_admin, category):
    """重复栏目名应失败提示"""
    rv = login_admin.post(
        "/category/add",
        data={
            "cat_name": category.cat_name,
            "tag_text": "",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302
    # 应 flash 提示重复
    rv2 = login_admin.get("/")
    assert "栏目名称重复".encode() in rv2.data or rv.status_code == 302


def test_add_category_empty_name(login_admin):
    """空栏目名应校验失败"""
    rv = login_admin.post(
        "/category/add",
        data={
            "cat_name": "",
            "tag_text": "",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302


def test_add_category_requires_login(client):
    """未登录不能新增栏目"""
    rv = client.post(
        "/category/add",
        data={
            "cat_name": "x",
            "tag_text": "",
        },
        follow_redirects=False,
    )
    assert rv.status_code == 302
    assert "/login" in rv.headers.get("Location", "")


def test_draft_detail_requires_login(client, draft):
    """匿名访问草稿详情应重定向（草稿仅后台可见）"""
    rv = client.get(f"/article/{draft.id}", follow_redirects=False)
    assert rv.status_code == 302


def test_draft_detail_visible_to_admin(login_admin, draft):
    """登录管理员可访问草稿详情"""
    rv = login_admin.get(f"/article/{draft.id}")
    assert rv.status_code == 200
    assert draft.title.encode("utf-8") in rv.data
