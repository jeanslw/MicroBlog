"""评论蓝图 —— 点赞、发表评论、回复评论。

重构要点：
- Flask-WTF 表单校验
- 评论内容长度限制 + 模板自动转义（不存原始 HTML 也不需要 sanitize）
- 点赞需校验文章存在且已发布
- 防刷：IP + 文章 ID 去重（接受 NAT 局限,生产可换 Redis）
"""

from datetime import datetime

from flask import flash, redirect, url_for
from flask_babel import _
from sqlalchemy.exc import IntegrityError

from app.comment import comment_bp
from app.extensions import db, get_client_ip
from app.forms import CommentForm, ReplyForm
from app.models import Article, Comment, Reply, VoteLog

USERNAME_MAX_LEN = 50
COMMENT_MAX_LEN = 2000
REPLY_MAX_LEN = 2000


def _normalize_username(raw: str) -> str:
    """规范化用户名：strip + 截断 + 空则默认游客"""
    if not raw:
        return "游客"
    return (raw.strip() or "游客")[:USERNAME_MAX_LEN]


@comment_bp.route("/vote/<int:aid>", methods=["POST"])
def vote(aid):
    """点赞文章：校验文章存在且已发布,IP+文章去重防刷"""
    article = db.session.get(Article, aid)
    if not article or article.status != "publish":
        flash(_("文章不存在或未发布"), "warning")
        return redirect(url_for("blog.article_detail", aid=aid))

    ip = get_client_ip()
    existing = db.session.scalar(db.select(VoteLog).where(VoteLog.article_id == aid, VoteLog.ip == ip))
    if existing:
        flash(_("您已经点过赞了"), "info")
        return redirect(url_for("blog.article_detail", aid=aid))

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        db.session.add(VoteLog(article_id=aid, ip=ip, create_time=now))
        # 原子 UPDATE:数据库端自增,避免读-改-写并发丢计数
        db.session.execute(
            db.text("UPDATE article SET vote_num = COALESCE(vote_num, 0) + 1 WHERE id = :aid"),
            {"aid": aid},
        )
        db.session.commit()
    except IntegrityError:
        # 并发请求同时插入,触发 UNIQUE(article_id, ip) 冲突
        db.session.rollback()
        flash(_("您已经点过赞了"), "info")
        return redirect(url_for("blog.article_detail", aid=aid))
    flash(_("点赞成功"), "success")
    return redirect(url_for("blog.article_detail", aid=aid))


@comment_bp.route("/comment/add/<int:aid>", methods=["POST"])
def add_comment(aid):
    article = db.session.get(Article, aid)
    if not article or article.status != "publish":
        flash(_("文章不存在或未发布"), "warning")
        return redirect(url_for("blog.index"))

    form = CommentForm()
    if not form.validate_on_submit():
        for field, errs in form.errors.items():
            for err in errs:
                flash(f"{field}: {err}", "danger")
        return redirect(url_for("blog.article_detail", aid=aid))

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    comment = Comment(
        article_id=aid,
        username=_normalize_username(form.username.data),
        content=form.content.data[:COMMENT_MAX_LEN],
        create_time=now,
    )
    db.session.add(comment)
    db.session.commit()
    flash(_("评论发布成功"), "success")
    return redirect(url_for("blog.article_detail", aid=aid))


@comment_bp.route("/reply/add/<int:aid>/<int:cid>", methods=["POST"])
def add_reply(aid, cid):
    """回复评论：校验文章已发布 + 评论存在且关联"""
    article = db.session.get(Article, aid)
    if not article or article.status != "publish":
        flash(_("文章不存在或未发布"), "warning")
        return redirect(url_for("blog.index"))

    comment = db.session.get(Comment, cid)
    if not comment or comment.article_id != aid:
        flash(_("评论不存在"), "warning")
        return redirect(url_for("blog.article_detail", aid=aid))

    form = ReplyForm()
    if not form.validate_on_submit():
        for field, errs in form.errors.items():
            for err in errs:
                flash(f"{field}: {err}", "danger")
        return redirect(url_for("blog.article_detail", aid=aid))

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reply = Reply(
        comment_id=cid,
        username=_normalize_username(form.username.data),
        content=form.content.data[:REPLY_MAX_LEN],
        create_time=now,
    )
    db.session.add(reply)
    db.session.commit()
    flash(_("回复成功"), "success")
    return redirect(url_for("blog.article_detail", aid=aid))
