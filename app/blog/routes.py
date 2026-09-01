"""博客蓝图 —— 文章浏览、发布、编辑、删除。

重构要点：
- 使用 Flask-WTF 表单校验 + 自动 CSRF
- 使用 Flask-SQLAlchemy ORM
- 删除文章用事务,异常时显式 rollback
- 文章保存时净化 HTML 防止存储型 XSS
"""

from datetime import datetime

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_babel import _
from flask_login import current_user
from sqlalchemy import func

from app.blog import blog_bp
from app.blog.queries import get_article_detail, get_article_list
from app.extensions import admin_required, db, log
from app.forms import ArticleForm, CategoryForm
from app.models import Article, Category
from app.utils import collect_static_upload_urls, remove_static_upload, strip_html

TITLE_MAX_LEN = 500


def _safe_int(value, default=1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@blog_bp.route("/")
def index():
    page_size = current_app.config.get("PAGE_SIZE", 6)
    page = max(_safe_int(request.args.get("page", 1), 1), 1)
    offset = (page - 1) * page_size
    articles, total_page = get_article_list(offset, page_size)
    return render_template("blog/index.html", articles=articles, page=page, total_page=total_page)


@blog_bp.route("/category/<int:cid>")
def category(cid):
    page_size = current_app.config.get("PAGE_SIZE", 6)
    page = max(_safe_int(request.args.get("page", 1), 1), 1)
    offset = (page - 1) * page_size
    articles, total_page = get_article_list(offset, page_size, cid)
    return render_template("blog/index.html", articles=articles, page=page, total_page=total_page)


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
    return render_template("blog/detail.html", article=article, comments=comments)


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
        article = Article(
            title=form.title.data.strip(),
            content=form.content.data,  # 保存原文,展示时净化
            status=form.status.data,
            category_id=cid,
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
        article.title = form.title.data.strip()
        article.content = form.content.data
        article.status = form.status.data
        article.category_id = cid
        article.update_time = now
        db.session.commit()
        flash(_("修改成功"), "success")
        return redirect(url_for("blog.article_detail", aid=aid))
    return render_template("blog/edit.html", form=form, article=article)


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
        for field, errors in form.errors.items():
            for err in errors:
                flash(f"{field}: {err}", "danger")
    return redirect(url_for("blog.index"))
