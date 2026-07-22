from flask import redirect, url_for, request, flash
from datetime import datetime
from app.comment import comment_bp
from app.db import get_db, DictCursor

# 输入验证限制
USERNAME_MAX_LEN = 50
COMMENT_MAX_LEN = 2000
REPLY_MAX_LEN = 2000


# 点赞（防刷：IP + 文章 ID 去重）
@comment_bp.route('/vote/<int:aid>')
def vote(aid):
    ip = request.remote_addr or "unknown"
    db = get_db()
    cur = db.cursor(DictCursor)
    # 检查是否已点赞
    cur.execute("SELECT id FROM vote_log WHERE article_id=%s AND ip=%s", (aid, ip))
    if cur.fetchone():
        flash("您已经点过赞了")
        cur.close()
        return redirect(url_for("blog.article_detail", aid=aid))
    # 记录点赞 + 增加点赞数
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO vote_log(article_id,ip,create_time) VALUES(%s,%s,%s)", (aid, ip, now))
    cur.execute("UPDATE article SET vote_num = vote_num + 1 WHERE id=%s", (aid,))
    db.commit()
    cur.close()
    flash("点赞成功！")
    return redirect(url_for("blog.article_detail", aid=aid))


# 发表评论
@comment_bp.route('/comment/add/<int:aid>', methods=["POST"])
def add_comment(aid):
    username = request.form["username"].strip()[:USERNAME_MAX_LEN] or "游客"
    content = request.form["content"].strip()
    if not content:
        flash("评论内容不能为空")
        return redirect(url_for("blog.article_detail", aid=aid))
    if len(content) > COMMENT_MAX_LEN:
        content = content[:COMMENT_MAX_LEN]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db = get_db()
    cur = db.cursor()
    cur.execute("INSERT INTO comment(article_id,username,content,create_time) VALUES(%s,%s,%s,%s)",
                (aid, username, content, now))
    db.commit()
    cur.close()
    flash("评论发布成功")
    return redirect(url_for("blog.article_detail", aid=aid))


# 回复评论
@comment_bp.route('/reply/add/<int:aid>/<int:cid>', methods=["POST"])
def add_reply(aid, cid):
    username = request.form["username"].strip()[:USERNAME_MAX_LEN] or "游客"
    content = request.form["content"].strip()
    if not content:
        flash("回复内容不能为空")
        return redirect(url_for("blog.article_detail", aid=aid))
    if len(content) > REPLY_MAX_LEN:
        content = content[:REPLY_MAX_LEN]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db = get_db()
    cur = db.cursor()
    cur.execute("INSERT INTO reply(comment_id,username,content,create_time) VALUES(%s,%s,%s,%s)",
                (cid, username, content, now))
    db.commit()
    cur.close()
    flash("回复成功")
    return redirect(url_for("blog.article_detail", aid=aid))
