from flask import render_template, request, redirect, url_for, flash, session
from datetime import datetime
from config import PAGE_SIZE
from app.blog import blog_bp
from app.blog.queries import get_article_list, get_article_detail
from app.db import get_db, DictCursor
from app.extensions import get_categories


@blog_bp.route('/')
def index():
    page = max(int(request.args.get("page", 1)), 1)
    offset = (page - 1) * PAGE_SIZE
    articles, total_page = get_article_list(offset, PAGE_SIZE)
    return render_template("blog/index.html", articles=articles, page=page, total_page=total_page)


@blog_bp.route('/category/<int:cid>')
def category(cid):
    page = max(int(request.args.get("page", 1)), 1)
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


@blog_bp.route('/article/new', methods=["GET", "POST"])
def article_new():
    if not session.get("is_admin"):
        flash("请先登录管理员账号")
        return redirect(url_for("admin.login"))
    db = get_db()
    if not db:
        flash("数据库连接失败，请检查数据库服务")
        return redirect(url_for("blog.index"))
    cur = db.cursor(DictCursor)
    cats, _ = get_categories()
    if request.method == "POST":
        title = request.form["title"].strip()
        content = request.form["content"]
        status = request.form["status"]
        cid = request.form.get("category_id")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("INSERT INTO article(title,content,status,category_id,create_time) VALUES(%s,%s,%s,%s,%s)",
                    (title, content, status, cid, now))
        db.commit()
        flash("文章保存成功")
        return redirect(url_for("blog.index"))
    cur.close()
    db.close()
    return render_template("blog/edit.html", article=None, categories=cats)


@blog_bp.route('/article/edit/<int:aid>', methods=["GET", "POST"])
def article_edit(aid):
    if not session.get("is_admin"):
        flash("请先登录管理员账号")
        return redirect(url_for("admin.login"))
    db = get_db()
    if not db:
        flash("数据库连接失败，请检查数据库服务")
        return redirect(url_for("blog.index"))
    cur = db.cursor(DictCursor)
    cur.execute("SELECT * FROM article WHERE id=%s", (aid,))
    art = cur.fetchone()
    if not art:
        flash("文章不存在")
        return redirect(url_for("blog.index"))
    cats, _ = get_categories()
    if request.method == "POST":
        title = request.form["title"].strip()
        content = request.form["content"]
        status = request.form["status"]
        cid = request.form.get("category_id")
        cur.execute("UPDATE article SET title=%s,content=%s,status=%s,category_id=%s WHERE id=%s",
                    (title, content, status, cid, aid))
        db.commit()
        flash("修改成功")
        return redirect(url_for("blog.article_detail", aid=aid))
    cur.close()
    db.close()
    return render_template("blog/edit.html", article=art, categories=cats)


@blog_bp.route('/article/del/<int:aid>')
def article_del(aid):
    if not session.get("is_admin"):
        flash("请先登录管理员账号")
        return redirect(url_for("admin.login"))
    db = get_db()
    if not db:
        flash("数据库连接失败，请检查数据库服务")
        return redirect(url_for("blog.index"))
    cur = db.cursor()
    cur.execute("DELETE FROM reply WHERE comment_id IN (SELECT id FROM comment WHERE article_id=%s)", (aid,))
    cur.execute("DELETE FROM comment WHERE article_id=%s", (aid,))
    cur.execute("DELETE FROM article WHERE id=%s", (aid,))
    db.commit()
    cur.close()
    db.close()
    flash("文章已删除")
    return redirect(url_for("blog.index"))


@blog_bp.route('/drafts')
def drafts():
    if not session.get("is_admin"):
        flash("请先登录管理员账号")
        return redirect(url_for("admin.login"))
    db = get_db()
    if not db:
        flash("数据库连接失败，请检查数据库服务")
        return redirect(url_for("blog.index"))
    cur = db.cursor(DictCursor)
    cur.execute("SELECT * FROM article WHERE status='draft' ORDER BY create_time DESC")
    draft_list = cur.fetchall()
    cur.close()
    db.close()
    return render_template("blog/drafts.html", drafts=draft_list)
