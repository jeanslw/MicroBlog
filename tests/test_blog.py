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


def test_del_category_success(login_admin, db, article, category):
    """删除栏目后该栏目消失,其下文章变为未分类"""
    cid = category.id
    rv = login_admin.post(f"/category/del/{cid}", follow_redirects=False)
    assert rv.status_code == 302
    assert db.session.get(Category, cid) is None
    db.session.expire(article)
    assert article.category_id is None


def test_del_category_not_found(login_admin):
    """删除不存在的栏目应提示并跳回首页"""
    rv = login_admin.post("/category/del/9999", follow_redirects=False)
    assert rv.status_code == 302


def test_del_category_requires_login(client, category):
    """未登录不能删除栏目"""
    rv = client.post(f"/category/del/{category.id}", follow_redirects=False)
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


def test_article_manage_requires_login(client):
    """撤回文章管理页需登录"""
    rv = client.get("/article/manage", follow_redirects=False)
    assert rv.status_code == 302
    assert "/login" in rv.headers.get("Location", "")


def test_article_manage_lists_published(login_admin, article, draft):
    """撤回文章页面只列出已发布文章(status=publish)"""
    rv = login_admin.get("/article/manage")
    assert rv.status_code == 200
    assert article.title.encode("utf-8") in rv.data
    # 草稿不出现
    assert draft.title.encode("utf-8") not in rv.data


def test_recall_article_moves_to_drafts(login_admin, db, article):
    """撤回文章后 status 变为 draft,文章出现在草稿箱"""
    aid = article.id
    rv = login_admin.post(f"/article/recall/{aid}", follow_redirects=False)
    assert rv.status_code == 302
    db.session.expire(article)
    assert article.status == "draft"
    rv2 = login_admin.get("/drafts")
    assert article.title.encode("utf-8") in rv2.data


def test_recall_not_found(login_admin):
    """撤回不存在的文章提示并重定向到 manage"""
    rv = login_admin.post("/article/recall/99999", follow_redirects=False)
    assert rv.status_code == 302
    assert "/article/manage" in rv.headers.get("Location", "")


def test_recall_requires_login(client, article):
    """未登录不能撤回"""
    rv = client.post(f"/article/recall/{article.id}", follow_redirects=False)
    assert rv.status_code == 302
    assert "/login" in rv.headers.get("Location", "")


# ── 站内搜索 ────────────────────────────────────────────
def test_search_matches_title(client, article):
    """按标题关键词应命中文章"""
    rv = client.get("/search", query_string={"q": "测试"})
    assert rv.status_code == 200
    assert article.title.encode("utf-8") in rv.data


def test_search_matches_content(client, article):
    """按正文关键词应命中文章"""
    rv = client.get("/search", query_string={"q": "正文"})
    assert rv.status_code == 200
    assert article.title.encode("utf-8") in rv.data


def test_search_no_result(client, article):
    """无匹配关键词应显示空态而非 500"""
    rv = client.get("/search", query_string={"q": "不存在的关键词xyz"})
    assert rv.status_code == 200
    assert article.title.encode("utf-8") not in rv.data
    assert "未找到相关文章".encode() in rv.data


def test_search_excludes_draft(client, draft):
    """搜索不应命中草稿"""
    rv = client.get("/search", query_string={"q": "草稿"})
    assert rv.status_code == 200
    assert draft.title.encode("utf-8") not in rv.data


def test_search_empty_query(client):
    """空关键词应返回 200 空态"""
    rv = client.get("/search")
    assert rv.status_code == 200
    assert "未找到相关文章".encode() in rv.data


def test_search_whitespace_query(client):
    """纯空白关键词按空查询处理"""
    rv = client.get("/search", query_string={"q": "   "})
    assert rv.status_code == 200


# ── 栏目重命名 ──────────────────────────────────────────
def test_edit_category_rename(login_admin, db, category, article):
    """重命名栏目后栏目名更新,其下文章自动跟随无需逐篇编辑"""
    cid = category.id
    rv = login_admin.post(
        f"/category/edit/{cid}",
        data={"cat_name": "改名后栏目", "tag_text": ""},
        follow_redirects=False,
    )
    assert rv.status_code == 302
    db.session.refresh(category)
    assert category.cat_name == "改名后栏目"
    db.session.refresh(article)
    assert article.category_id == cid


def test_edit_category_duplicate(login_admin, db, category):
    """重命名为其他栏目已有名称应失败并提示重复"""
    import json

    db.session.add(Category(cat_name="已占用名称", tag_text="", create_time="2026-01-01 00:00:00"))
    db.session.commit()
    rv = login_admin.post(
        f"/category/edit/{category.id}",
        data={"cat_name": "已占用名称", "tag_text": ""},
        follow_redirects=False,
    )
    assert rv.status_code == 302
    db.session.refresh(category)
    assert category.cat_name == "测试栏目"
    rv2 = login_admin.get("/")
    html = rv2.data.decode("utf-8")
    start = html.find('id="flashData">') + len('id="flashData">')
    end = html.find("</script>", start)
    flash = json.loads(html[start:end])
    assert any("栏目名称重复" in m[1] for m in flash)


def test_edit_category_empty_name(login_admin, category, db):
    """空白名称应提示不能为空且不改动原名称"""
    rv = login_admin.post(
        f"/category/edit/{category.id}",
        data={"cat_name": "   ", "tag_text": ""},
        follow_redirects=False,
    )
    assert rv.status_code == 302
    db.session.refresh(category)
    assert category.cat_name == "测试栏目"


def test_edit_category_not_found(login_admin):
    """重命名不存在的栏目应跳回首页"""
    rv = login_admin.post("/category/edit/9999", follow_redirects=False)
    assert rv.status_code == 302


def test_edit_category_requires_login(client, category):
    """未登录不能重命名栏目"""
    rv = client.post(f"/category/edit/{category.id}", follow_redirects=False)
    assert rv.status_code == 302
    assert "/login" in rv.headers.get("Location", "")
