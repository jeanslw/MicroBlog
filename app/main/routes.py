"""主蓝图：语言切换、robots.txt、上传文件服务等通用路由。

不处理根路由 `/`,根路由由 blog.index 提供。
"""

import os

from flask import Response, abort, jsonify, redirect, request, send_file, session, url_for
from werkzeug.utils import safe_join

from app.extensions import db, external_url_for, safe_redirect_path
from app.main import main_bp
from app.utils import UPLOAD_CATEGORIES, project_root


@main_bp.route("/uploads/<category>/<path:filename>")
def uploaded_file(category: str, filename: str):
    """上传文件服务（uploads/ 位于 static/ 之外，不走 Flask 内置 static 路由）。

    category 白名单限定为 banner / image；werkzeug 的 safe_join 显式净化
    filename（命中 ../、绝对路径等穿越时返回 None → 404，不直接拼进文件系统
    调用）。缓存策略由 after_request 与 /static/ 统一处理
    （BLOG_STATIC_MAX_AGE + immutable）。
    """
    if category not in UPLOAD_CATEGORIES:
        abort(404)
    directory = safe_join(project_root(), "uploads", category)
    if directory is None:
        abort(404)
    full_path = safe_join(directory, filename)
    if full_path is None or not os.path.isfile(full_path):
        abort(404)
    # conditional=True：支持 ETag/Range；缓存头由 after_request 按端点统一下发
    return send_file(full_path, conditional=True)


# 旧版上传 URL 兼容：目录从 static/ 迁移到 uploads/ 后，存量数据库记录
# （轮播图 img_path、文章正文 img src、站点设置等）仍指向旧地址，
# 用 301 永久跳转至新地址，避免历史内容破图。
@main_bp.route("/static/banner/<path:filename>")
def legacy_static_banner(filename: str):
    return redirect(url_for("main.uploaded_file", category="banner", filename=filename), code=301)


@main_bp.route("/static/uploads/<path:filename>")
def legacy_static_uploads(filename: str):
    return redirect(url_for("main.uploaded_file", category="image", filename=filename), code=301)


@main_bp.route("/healthz")
def healthz():
    """健康检查探针：进程存活且数据库可连通时返回 200，否则 503。

    供容器 HEALTHCHECK / 编排探针使用，在 Host 白名单校验中显式豁免
    （探针的 Host 头通常是 127.0.0.1:5000 等容器内地址，不可控）。
    """
    from sqlalchemy import text

    try:
        db.session.execute(text("SELECT 1"))
    except Exception:
        db.session.rollback()
        return jsonify(status="db unavailable"), 503
    return jsonify(status="ok"), 200


@main_bp.route("/set_lang/<lang>")
def set_lang(lang: str):
    """切换语言并存入 session"""
    if lang in ("zh_CN", "en"):
        session["lang"] = lang
    # 优先用 ?next= 显式指定,其次 referrer（均做同源校验）,最后回首页
    next_url = safe_redirect_path(request.args.get("next")) or safe_redirect_path(request.referrer) or url_for("blog.index")
    return redirect(next_url)


@main_bp.route("/robots.txt")
def robots():
    """简单的 robots.txt（默认允许）+ 站点地图声明"""
    sitemap_url = external_url_for("main.sitemap")
    body = "User-agent: *\nAllow: /\nSitemap: " + sitemap_url + "\n"
    return Response(body, mimetype="text/plain")


@main_bp.route("/sitemap.xml")
def sitemap():
    """站点地图：首页/关于我/各栏目/各已发布文章。"""
    from app.extensions import db
    from app.models import Article, Category

    pages = [
        {"loc": external_url_for("blog.index"), "lastmod": "", "priority": "1.0"},
        {"loc": external_url_for("blog.about"), "lastmod": "", "priority": "0.6"},
    ]
    for cat in db.session.scalars(db.select(Category).order_by(Category.id)).all():
        pages.append(
            {"loc": external_url_for("blog.category", cid=cat.id), "lastmod": "", "priority": "0.5"}
        )
    for art in db.session.scalars(
        db.select(Article).where(Article.status == "publish").order_by(Article.create_time.desc())
    ).all():
        pages.append(
            {
                "loc": external_url_for("blog.article_detail", aid=art.id),
                "lastmod": (art.update_time or art.create_time or "")[:10],
                "priority": "0.8",
            }
        )

    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for p in pages:
        lines.append("  <url>")
        lines.append(f"    <loc>{p['loc']}</loc>")
        if p["lastmod"]:
            lines.append(f"    <lastmod>{p['lastmod']}</lastmod>")
        lines.append(f"    <priority>{p['priority']}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return Response("\n".join(lines), mimetype="application/xml")
