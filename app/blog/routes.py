import logging
from datetime import datetime

from flask import render_template, request, redirect, url_for, flash

from config import PAGE_SIZE
from app.blog import blog_bp
from app.blog.queries import get_article_list, get_article_detail, strip_html
from app.db import get_db, DictCursor
from app.extensions import get_categories, admin_required

log = logging.getLogger(__name__)

TITLE_MAX_LEN = 500


def _safe_int(value, default=1):
    """安全的 int 转换，非法值返回 default"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@blog_bp.route('/')
def index():
    page = max(_safe_int(request.args.get("page", 1), 1), 1)
    offset = (page - 1) * PAGE_SIZE
    articles, total_page = get_article_list(offset, PAGE_SIZE)
    return render_template("blog/index.html", articles=articles, page=page, total_page=total_page)


@blog_bp.route('/category/<int:cid>')
def category(cid):
    page = max(_safe_int(request.args.get("page", 1), 1), 1)
    offset = (page - 1) * PAGE_SIZE
    articles, total_page = get_article_list(offset, PAGE_SIZE, cid)
    return render_template("blog/index.html", articles=articles, page=page, total_page=total_page)


@blog_bp.route('/article/<int:aid>')
def article_detail(aid):
    article, comments = get_article_detail(aid)
    if not article:
        flash("文章不存在")
        return redirect(url_for("blog.index"))
    return render_template("blog/detail.html", article=article, comments=comments)


def _validate_article_form():
    """校验文章表单，返回 (title, content, status, cid, err_msg)"""
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    status = request.form.get("status", "draft")
    cid_raw = request.form.get("category_id", "").strip()

    if not title:
        return None, None, None, None, "文章标题不能为空"
    if len(title) > TITLE_MAX_LEN:
        return None, None, None, None, f"标题不能超过 {TITLE_MAX_LEN} 字符"
    if not content:
        return None, None, None, None, "正文不能为空"
    if status not in ("draft", "publish"):
        return None, None, None, None, "状态值非法"

    cid = _safe_int(cid_raw, None) if cid_raw else None
    return title, content, status, cid, None


@blog_bp.route('/article/new', methods=["GET", "POST"])
@admin_required
def article_new():
    cats, _ = get_categories()
    if request.method == "POST":
        title, content, status, cid, err = _validate_article_form()
        if err:
            flash(err)
            return render_template("blog/edit.html", article=None, categories=cats)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db = get_db()
        cur = db.cursor()
        try:
            cur.execute(
                "INSERT INTO article(title,content,status,category_id,create_time,update_time) "
                "VALUES(%s,%s,%s,%s,%s,%s)",
                (title, content, status, cid, now, now)
            )
            db.commit()
            flash("文章保存成功")
            return redirect(url_for("blog.index"))
        finally:
            cur.close()
    return render_template("blog/edit.html", article=None, categories=cats)


@blog_bp.route('/article/edit/<int:aid>', methods=["GET", "POST"])
@admin_required
def article_edit(aid):
    db = get_db()
    cur = db.cursor(DictCursor)
    cur.execute("SELECT * FROM article WHERE id=%s", (aid,))
    art = cur.fetchone()
    cur.close()
    if not art:
        flash("文章不存在")
        return redirect(url_for("blog.index"))
    cats, _ = get_categories()
    if request.method == "POST":
        title, content, status, cid, err = _validate_article_form()
        if err:
            flash(err)
            return render_template("blog/edit.html", article=art, categories=cats)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db = get_db()
        cur = db.cursor()
        try:
            cur.execute(
                "UPDATE article SET title=%s,content=%s,status=%s,category_id=%s,update_time=%s "
                "WHERE id=%s",
                (title, content, status, cid, now, aid)
            )
            db.commit()
            flash("修改成功")
            return redirect(url_for("blog.article_detail", aid=aid))
        finally:
            cur.close()
    return render_template("blog/edit.html", article=art, categories=cats)


# 删除文章改为 POST，避免 GET 被 CSRF 利用
@blog_bp.route('/article/del/<int:aid>', methods=["POST"])
@admin_required
def article_del(aid):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            "DELETE FROM reply WHERE comment_id IN "
            "(SELECT id FROM comment WHERE article_id=%s)", (aid,)
        )
        cur.execute("DELETE FROM comment WHERE article_id=%s", (aid,))
        cur.execute("DELETE FROM vote_log WHERE article_id=%s", (aid,))
        cur.execute("DELETE FROM article WHERE id=%s", (aid,))
        db.commit()
        flash("文章已删除")
    except Exception:
        log.error("删除文章失败 aid=%s", aid, exc_info=True)
        flash("删除失败，请稍后重试")
    finally:
        cur.close()
    return redirect(url_for("blog.index"))


@blog_bp.route('/drafts')
@admin_required
def drafts():
    db = get_db()
    cur = db.cursor(DictCursor)
    cur.execute("SELECT * FROM article WHERE status='draft' ORDER BY create_time DESC")
    draft_list = cur.fetchall()
    cur.close()
    for art in draft_list:
        art["brief"] = strip_html(art["content"])
    return render_template("blog/drafts.html", drafts=draft_list)
