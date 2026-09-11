"""博客蓝图 —— 文章浏览、发布、编辑、删除。

重构要点：
- 使用 Flask-WTF 表单校验 + 自动 CSRF
- 使用 Flask-SQLAlchemy ORM
- 删除文章用事务,异常时显式 rollback
- 文章正文保存原文，读取展示时经 nh3 白名单净化防存储型 XSS
"""

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Response, current_app, flash, redirect, render_template, request, url_for
from flask_babel import _
from flask_login import current_user
from sqlalchemy import func, update

from app.blog import blog_bp
from app.blog.queries import (
    get_article_detail,
    get_article_list,
    get_recent_articles,
    get_sidebar_tree,
    search_articles,
)
from app.extensions import admin_required, db, flash_form_errors, log
from app.forms import ArticleForm, CategoryForm
from app.models import Admin, Article, Category, SiteConfig
from app.utils import collect_static_upload_urls, remove_static_upload, strip_html

TITLE_MAX_LEN = 500


def _safe_int(value, default=1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _estimate_reading_stats(content: str):
    """计算字数和预计阅读时长，避免对存储字段做额外数据库迁移。

    统计规则：
    - 中文字符按 1 字计数
    - 英文/数字按单词计数
    - 过滤空白和标点
    - 采用全文文本，不使用摘要截断值，避免 220 字截断导致统计错误
    """
    text = strip_html(content or "", max_len=None)
    if not text:
        return {"word_count": 0, "reading_minutes": 1}

    words = re.findall(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?|[\u4e00-\u9fff]", text)
    word_count = len(words)
    reading_minutes = max(1, (word_count + 299) // 300)
    return {"word_count": word_count, "reading_minutes": reading_minutes}


def _extract_toc(content: str):
    """从正文提取 h1-h3 标题生成目录，并给标题注入 id 锚点用于跳读。

    返回 (content, items)：content 为注入 id 后的正文 HTML，items 为目录条目。
    """
    items = []
    seen = set()
    counter = 0

    def _inject(match):
        nonlocal counter
        level = int(match.group(1))
        attrs = match.group(2) or ""
        inner = match.group(3)
        title = re.sub(r"\s+", " ", strip_html(inner)).strip()
        if not title:
            return match.group(0)
        existing = re.search(r'id\s*=\s*"([^"]+)"', attrs, flags=re.IGNORECASE)
        if existing:
            slug = existing.group(1)
        else:
            slug = re.sub(r"[^\w\- ]+", "", title.lower())
            slug = re.sub(r"\s+", "-", slug).strip("-")
            if not slug:
                counter += 1
                slug = f"section-{counter}"
            if slug in seen:
                counter += 1
                slug = f"{slug}-{counter}"
            attrs = attrs + ' id="' + slug + '"'
        seen.add(slug)
        items.append({"id": slug, "title": title, "level": level})
        return "<h" + str(level) + attrs + ">" + inner + "</h" + str(level) + ">"

    new_content = re.sub(
        r"<h([1-3])([^>]*)>(.*?)</h[1-3]>",
        _inject,
        content or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    return new_content, items


def _auto_seo(content, title, category):
    """生成 SEO 描述与关键词（编辑页留空时自动填充）。

    - 描述：正文纯文本截断 160 字
    - 关键词：优先栏目标签 tag_text，否则标题去标点分词；与标题拼接、逗号分隔、截断 300
    """
    description = strip_html(content or "").strip()
    if len(description) > 160:
        description = description[:160]

    parts = []
    if category and getattr(category, "tag_text", ""):
        parts.append(category.tag_text.strip())
    if title:
        tokens = [t for t in re.split(r"[\s,，、;；/|｜·]+", title.strip()) if t]
        parts.extend(tokens)
    keywords = ", ".join(dict.fromkeys(parts))
    if len(keywords) > 300:
        keywords = keywords[:300]
    return description, keywords


@blog_bp.route("/")
def index():
    page_size = current_app.config.get("PAGE_SIZE", 6)
    page = max(_safe_int(request.args.get("page", 1), 1), 1)
    offset = (page - 1) * page_size
    articles, total_page = get_article_list(offset, page_size)
    category_map, archive = get_sidebar_tree()
    return render_template(
        "blog/index.html",
        articles=articles,
        page=page,
        total_page=total_page,
        category_map=category_map,
        archive=archive,
    )


@blog_bp.route("/category/<int:cid>")
def category(cid):
    page_size = current_app.config.get("PAGE_SIZE", 6)
    page = max(_safe_int(request.args.get("page", 1), 1), 1)
    offset = (page - 1) * page_size
    articles, total_page = get_article_list(offset, page_size, cid)
    category_map, archive = get_sidebar_tree()
    return render_template(
        "blog/index.html",
        articles=articles,
        page=page,
        total_page=total_page,
        category_map=category_map,
        archive=archive,
    )


@blog_bp.route("/article/<int:aid>")
def article_detail(aid):
    article, comments = get_article_detail(aid)
    if not article:
        flash(_("文章不存在"), "warning")
        return redirect(url_for("blog.index"))
    # 草稿/非发布文章仅登录管理员可访问,匿名访问视为不存在
    if article.status != "publish" and not current_user.is_authenticated:
        flash(_("文章不存在"), "warning")
        return redirect(url_for("blog.index"))
    reading_stats = _estimate_reading_stats(article.content)
    article.word_count = reading_stats["word_count"]
    article.reading_time = reading_stats["reading_minutes"]
    # 从净化后的 safe_content 提取 TOC,结果存到非映射属性 rendered_content,
    # 不修改 mapped 的 content 列（否则每次访问都会触发一条无谓 UPDATE）
    article.rendered_content, article.toc = _extract_toc(article.safe_content)
    # 正文首图，供 Open Graph og:image 使用
    article.og_image = ""
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', article.rendered_content or "")
    if m:
        article.og_image = m.group(1)
    # 作者署名：昵称未设置时回退为管理员用户名
    author_name = db.session.scalar(db.select(SiteConfig.about_nickname)) or ""
    if not author_name:
        author_name = db.session.scalar(db.select(Admin.username).order_by(Admin.id).limit(1)) or ""
    category_map, archive = get_sidebar_tree()
    return render_template(
        "blog/detail.html",
        article=article,
        comments=comments,
        author_name=author_name,
        category_map=category_map,
        archive=archive,
    )


@blog_bp.route("/article/new", methods=["GET", "POST"])
@admin_required
def article_new():
    form = ArticleForm()
    # 栏目下拉
    form.category_id.choices = [(0, _("不选择栏目"))] + [
        (c.id, c.cat_name) for c in db.session.scalars(db.select(Category).order_by(Category.id.desc())).all()
    ]
    if form.validate_on_submit():
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cid = form.category_id.data or None
        if cid == 0:
            cid = None
        category = db.session.get(Category, cid) if cid else None
        seo_desc = (form.seo_description.data or "").strip()
        seo_kw = (form.seo_keywords.data or "").strip()
        if not seo_desc or not seo_kw:
            auto_desc, auto_kw = _auto_seo(form.content.data, form.title.data, category)
            seo_desc = seo_desc or auto_desc
            seo_kw = seo_kw or auto_kw
        article = Article(
            title=form.title.data.strip(),
            content=form.content.data,  # 保存原文,展示时净化
            status=form.status.data,
            category_id=cid,
            seo_description=seo_desc,
            seo_keywords=seo_kw,
            create_time=now,
            update_time=now,
        )
        db.session.add(article)
        db.session.commit()
        flash(_("文章保存成功"), "success")
        return redirect(url_for("blog.index"))
    return render_template("blog/edit.html", form=form, article=None)


@blog_bp.route("/article/edit/<int:aid>", methods=["GET", "POST"])
@admin_required
def article_edit(aid):
    article = db.session.get(Article, aid)
    if not article:
        flash(_("文章不存在"), "warning")
        return redirect(url_for("blog.index"))
    form = ArticleForm(obj=article)
    form.category_id.choices = [(0, _("不选择栏目"))] + [
        (c.id, c.cat_name) for c in db.session.scalars(db.select(Category).order_by(Category.id.desc())).all()
    ]
    if form.validate_on_submit():
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cid = form.category_id.data or None
        if cid == 0:
            cid = None
        category = db.session.get(Category, cid) if cid else None
        seo_desc = (form.seo_description.data or "").strip()
        seo_kw = (form.seo_keywords.data or "").strip()
        if not seo_desc or not seo_kw:
            auto_desc, auto_kw = _auto_seo(form.content.data, form.title.data, category)
            seo_desc = seo_desc or auto_desc
            seo_kw = seo_kw or auto_kw
        article.title = form.title.data.strip()
        article.content = form.content.data
        article.status = form.status.data
        article.category_id = cid
        article.seo_description = seo_desc
        article.seo_keywords = seo_kw
        article.update_time = now
        db.session.commit()
        flash(_("修改成功"), "success")
        return redirect(url_for("blog.article_detail", aid=aid))
    return render_template("blog/edit.html", form=form, article=article)


@blog_bp.route("/article/pin/<int:aid>", methods=["POST"])
@admin_required
def article_pin(aid):
    article = db.session.get(Article, aid)
    if not article:
        flash(_("文章不存在"), "warning")
        return redirect(url_for("blog.index"))
    article.is_pinned = not article.is_pinned
    article.update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        db.session.commit()
        flash(_("文章置顶状态已更新"), "success")
    except Exception:
        db.session.rollback()
        log.error("切换文章置顶失败 aid=%s", aid, exc_info=True)
        flash(_("操作失败,请稍后重试"), "danger")
    return redirect(url_for("blog.article_detail", aid=aid))


@blog_bp.route("/article/del/<int:aid>", methods=["POST"])
@admin_required
def article_del(aid):
    """删除文章 + 关联评论/回复/点赞,事务化避免半删"""
    try:
        article = db.session.get(Article, aid)
        if not article:
            flash(_("文章不存在"), "warning")
            return redirect(url_for("blog.index"))
        # ORM 级联删除（评论 → 回复 通过 cascade="all, delete-orphan"）
        # 点赞记录手动删除
        db.session.execute(
            db.text("DELETE FROM vote_log WHERE article_id=:aid"),
            {"aid": aid},
        )
        # 收集文章内引用的上传图片（删除前）
        old_urls = collect_static_upload_urls(article.content)
        db.session.delete(article)
        db.session.commit()
        # 清理不再被任何文章引用的图片,避免磁盘堆积
        for u in old_urls:
            still_used = db.session.scalar(db.select(func.count(Article.id)).where(Article.content.contains(u)))
            if not still_used:
                remove_static_upload(u)
        flash(_("文章已删除"), "success")
    except Exception:
        db.session.rollback()
        log.error("删除文章失败 aid=%s", aid, exc_info=True)
        flash(_("删除失败,请稍后重试"), "danger")
    return redirect(url_for("blog.index"))


@blog_bp.route("/article/manage")
@admin_required
def article_manage():
    """已发布文章管理：列出 status="publish" 的文章，每条提供「撤回(→草稿)」与删除按钮。"""
    articles = db.session.scalars(
        db.select(Article).where(Article.status == "publish").order_by(Article.update_time.desc())
    ).all()
    for art in articles:
        art.brief = strip_html(art.content)
    return render_template("blog/manage_articles.html", articles=articles)


@blog_bp.route("/article/recall/<int:aid>", methods=["POST"])
@admin_required
def article_recall(aid):
    """撤回已发布文章：status 改回 "draft"，文章进入草稿箱。"""
    article = db.session.get(Article, aid)
    if not article:
        flash(_("文章不存在"), "warning")
        return redirect(url_for("blog.article_manage"))
    article.status = "draft"
    article.update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        db.session.commit()
        flash(_("已撤回至草稿箱"), "success")
    except Exception:
        db.session.rollback()
        log.error("撤回文章失败 aid=%s", aid, exc_info=True)
        flash(_("撤回失败,请稍后重试"), "danger")
    return redirect(url_for("blog.article_manage"))


@blog_bp.route("/drafts")
@admin_required
def drafts():
    draft_list = db.session.scalars(
        db.select(Article).where(Article.status == "draft").order_by(Article.create_time.desc())
    ).all()
    for art in draft_list:
        art.brief = strip_html(art.content)  # 草稿列表显示纯文本摘要,而非 HTML 源码
    return render_template("blog/drafts.html", drafts=draft_list)


@blog_bp.route("/category/add", methods=["POST"])
@admin_required
def add_category():
    form = CategoryForm()
    if form.validate_on_submit():
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cat = Category(
            cat_name=form.cat_name.data.strip(),
            tag_text=(form.tag_text.data or "").strip(),
            create_time=now,
        )
        db.session.add(cat)
        try:
            db.session.commit()
            flash(_("栏目新增成功"), "success")
        except Exception:
            db.session.rollback()
            flash(_("栏目名称重复"), "danger")
    else:
        flash_form_errors(form)
    return redirect(url_for("blog.index"))


@blog_bp.route("/category/del/<int:cid>", methods=["POST"])
@admin_required
def del_category(cid):
    """删除栏目（含其标签）：该栏目下文章恢复为未分类。"""
    cat = db.session.get(Category, cid)
    if cat is None:
        flash(_("栏目不存在"), "warning")
        return redirect(url_for("blog.index"))
    # 先解除文章归属,避免外键约束失败
    db.session.execute(
        update(Article).where(Article.category_id == cid).values(category_id=None)
    )
    db.session.delete(cat)
    try:
        db.session.commit()
        flash(_("栏目删除成功"), "success")
    except Exception:
        db.session.rollback()
        flash(_("栏目删除失败"), "danger")
    return redirect(url_for("blog.index"))


@blog_bp.route("/category/edit/<int:cid>", methods=["POST"])
@admin_required
def edit_category(cid):
    """重命名栏目：文章通过 category_id 关联，改名后自动跟随，无需逐篇重新归类。"""
    cat = db.session.get(Category, cid)
    if cat is None:
        flash(_("栏目不存在"), "warning")
        return redirect(url_for("blog.index"))
    form = CategoryForm()
    if form.validate_on_submit():
        new_name = (form.cat_name.data or "").strip()
        if not new_name:
            flash(_("栏目名称不能为空"), "danger")
            return redirect(url_for("blog.index"))
        cat.cat_name = new_name
        try:
            db.session.commit()
            flash(_("栏目重命名成功"), "success")
        except Exception:
            db.session.rollback()
            flash(_("栏目名称重复"), "danger")
    else:
        flash_form_errors(form)
    return redirect(url_for("blog.index"))


# ── 关于我 ──────────────────────────────────────────────
@blog_bp.route("/about")
def about():
    """「关于我」公开页面：展示后台站点设置里填写的头像/简介/邮箱/GitHub/个人主页"""
    site = db.session.get(SiteConfig, 1)
    avatar = (site.about_avatar or "") if site else ""
    bio = (site.about_bio or "").strip() if site else ""
    email = (site.about_email or "").strip() if site else ""
    github = (site.about_github or "").strip() if site else ""
    homepage = (site.about_homepage or "").strip() if site else ""
    github_href = github if github.startswith(("http://", "https://")) else f"https://{github}"
    github_display = github.split("://", 1)[-1].rstrip("/") if github else ""
    homepage_href = homepage if homepage.startswith(("http://", "https://")) else f"https://{homepage}"
    homepage_display = homepage.split("://", 1)[-1].rstrip("/") if homepage else ""
    return render_template(
        "blog/about.html",
        about={
            "avatar": avatar,
            "bio": bio,
            "email": email,
            "github": github,
            "github_href": github_href if github else "",
            "github_display": github_display,
            "homepage": homepage,
            "homepage_href": homepage_href if homepage else "",
            "homepage_display": homepage_display,
        },
    )


# ── 站内搜索 ────────────────────────────────────────────
@blog_bp.route("/search")
def search():
    """按关键词搜索已发布文章（标题/正文模糊匹配），支持分页"""
    q = (request.args.get("q") or "").strip()
    page = max(_safe_int(request.args.get("page", 1), 1), 1)
    if not q:
        return render_template("blog/search.html", articles=[], page=1, total_page=1, q="", total=0)
    page_size = current_app.config.get("PAGE_SIZE", 6)
    offset = (page - 1) * page_size
    articles, total_page, total = search_articles(q, offset, page_size)
    return render_template(
        "blog/search.html", articles=articles, page=page, total_page=total_page, q=q, total=total
    )


# ── RSS/Atom 订阅源 ─────────────────────────────────────
try:
    _CN_TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    # Windows / 精简容器镜像缺少 IANA 时区数据库时,退化为固定 UTC+8（与上海时区等价）
    _CN_TZ = timezone(timedelta(hours=8))


def _parse_feed_time(value: str) -> datetime | None:
    """将 "YYYY-MM-DD HH:MM:SS" 转为带时区的 datetime，解析失败返回 None"""
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_CN_TZ)
    except (TypeError, ValueError):
        return None


def _build_feed():
    """构建订阅源对象（Atom/RSS 共用同一份数据）。

    feedgen 延迟导入：该依赖仅订阅源路由需要，避免影响其他功能启动。
    """
    from feedgen.feed import FeedGenerator

    articles = get_recent_articles()
    site_name = db.session.scalar(db.select(SiteConfig.site_name)) or "博客"
    # 优先使用配置的 CANONICAL_URL,避免 Host 头注入导致订阅源链接被投毒
    base_url = (current_app.config.get("CANONICAL_URL") or request.host_url).rstrip("/")
    feed = FeedGenerator()
    feed.id(base_url)
    feed.title(site_name)
    feed.author({"name": site_name})
    feed.link(href=base_url, rel="alternate")
    feed.link(href=f"{base_url}/feed", rel="self")
    feed.language("zh-CN")
    feed.description(_("本站订阅"))
    feed.subtitle(_("本站订阅"))
    for art in articles:
        entry = feed.add_entry()
        entry.id(f"{base_url}/article/{art.id}")
        entry.title(art.title)
        entry.link(href=f"{base_url}/article/{art.id}")
        entry.summary(strip_html(art.content))
        published = _parse_feed_time(art.create_time)
        if published:
            entry.published(published)
        updated = _parse_feed_time(art.update_time)
        if updated:
            entry.updated(updated)
    return feed


@blog_bp.route("/feed")
def feed_atom():
    """Atom 订阅源"""
    return Response(_build_feed().atom_str(pretty=True), mimetype="application/atom+xml")


@blog_bp.route("/rss")
def feed_rss():
    """RSS 2.0 订阅源"""
    return Response(_build_feed().rss_str(pretty=True), mimetype="application/rss+xml")
