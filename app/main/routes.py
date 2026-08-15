"""主蓝图：语言切换、robots.txt 等通用路由。

不处理根路由 `/`,根路由由 blog.index 提供。
"""
from urllib.parse import urljoin, urlparse

from flask import Response, redirect, request, session, url_for

from app.main import main_bp


def _safe_next_url(target: str) -> str | None:
    """仅允许同源相对/绝对 URL,防开放重定向。

    target 为完整 URL 时校验 netloc 与当前 host 一致；
    为相对路径时视为同源；非法/外站链接返回 None。
    """
    if not target:
        return None
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    if test.scheme in ("http", "https") and test.netloc == ref.netloc:
        # 保留 path + query,避免丢失分页等参数
        return test.path + (f"?{test.query}" if test.query else "")
    return None


@main_bp.route("/set_lang/<lang>")
def set_lang(lang: str):
    """切换语言并存入 session"""
    if lang in ("zh_CN", "en"):
        session["lang"] = lang
    # 优先用 ?next= 显式指定,其次 referrer（均做同源校验）,最后回首页
    next_url = (
        _safe_next_url(request.args.get("next"))
        or _safe_next_url(request.referrer)
        or url_for("blog.index")
    )
    return redirect(next_url)


@main_bp.route("/robots.txt")
def robots():
    """简单的 robots.txt（默认允许）"""
    body = "User-agent: *\nAllow: /\n"
    return Response(body, mimetype="text/plain")
