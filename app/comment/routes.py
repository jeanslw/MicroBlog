from flask import redirect, url_for, request, flash
from datetime import datetime
from app.comment import comment_bp
from app.db import get_db


# 点赞
@comment_bp.route('/vote/<int:aid>')
def vote(aid):
    db = get_db()
    cur = db.cursor()
    cur.execute("UPDATE article SET vote_num = vote_num + 1 WHERE id=%s", (aid,))
    db.commit()
    cur.close()
    db.close()
    flash("点赞成功！")
    return redirect(url_for("blog.article_detail", aid=aid))


# 发表评论
@comment_bp.route('/comment/add/<int:aid>', methods=["POST"])
def add_comment(aid):
    username = request.form["username"].strip() or "游客"
    content = request.form["content"].strip()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db = get_db()
    cur = db.cursor()
    cur.execute("INSERT INTO comment(article_id,username,content,create_time) VALUES(%s,%s,%s,%s)",
                (aid, username, content, now))
    db.commit()
    cur.close()
    db.close()
    flash("评论发布成功")
    return redirect(url_for("blog.article_detail", aid=aid))


# 回复评论
@comment_bp.route('/reply/add/<int:aid>/<int:cid>', methods=["POST"])
def add_reply(aid, cid):
    username = request.form["username"].strip() or "游客"
    content = request.form["content"].strip()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db = get_db()
    cur = db.cursor()
    cur.execute("INSERT INTO reply(comment_id,username,content,create_time) VALUES(%s,%s,%s,%s)",
                (cid, username, content, now))
    db.commit()
    cur.close()
    db.close()
    flash("回复成功")
    return redirect(url_for("blog.article_detail", aid=aid))
