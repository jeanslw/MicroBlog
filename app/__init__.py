import logging
import os
import secrets
import traceback
from datetime import timedelta, date

from flask import Flask, session, request, abort

from config import (
    DEBUG, SECRET_KEY, SEND_FILE_MAX_AGE, MAX_CONTENT_LENGTH,
    SESSION_COOKIE_HTTPONLY, SESSION_COOKIE_SAMESITE, SESSION_COOKIE_SECURE,
    PERMANENT_SESSION_LIFETIME,
)
from app.db import close_db
from app.extensions import get_categories, get_site_name
from app.blog import blog_bp
from app.comment import comment_bp
from app.admin import admin_bp
from app.banner import banner_bp
from app.banner.queries import get_all_banner


def _setup_logging(app):
    """统一日志格式，避免 print 散落"""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
    ))
    if not app.logger.handlers:
        app.logger.addHandler(handler)
    app.logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)


def create_app():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    template_dir = os.path.join(root_dir, 'templates')
    static_dir = os.path.join(root_dir, 'static')
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    app.secret_key = SECRET_KEY

    # Session 安全
    app.config['SESSION_COOKIE_HTTPONLY'] = SESSION_COOKIE_HTTPONLY
    app.config['SESSION_COOKIE_SAMESITE'] = SESSION_COOKIE_SAMESITE
    app.config['SESSION_COOKIE_SECURE'] = SESSION_COOKIE_SECURE
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(seconds=PERMANENT_SESSION_LIFETIME)

    # 模板自动重载跟随 DEBUG
    app.config['TEMPLATES_AUTO_RELOAD'] = DEBUG
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = SEND_FILE_MAX_AGE
    app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
    app.config['DEBUG'] = DEBUG

    _setup_logging(app)

    # 请求结束时自动关闭数据库连接
    app.teardown_appcontext(close_db)

    # CSRF 保护：仅对写操作校验，GET 不验证（避免 logout/del/vote 通过 GET 触发）
    @app.before_request
    def csrf_protect():
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_hex(32)
        if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            submitted = (
                request.form.get('csrf_token')
                or request.headers.get('X-CSRF-Token')
                or request.args.get('csrf_token')
            )
            if not submitted or not secrets.compare_digest(
                session.get('csrf_token', ''), submitted
            ):
                abort(400, 'CSRF 验证失败，请刷新页面后重试')

    @app.errorhandler(Exception)
    def all_err_handler(e):
        app.logger.error("未捕获异常: %s", e)
        app.logger.error(traceback.format_exc())
        if DEBUG:
            # 开发环境返回堆栈，便于排查
            return traceback.format_exc(), 500
        return "服务器内部错误，请联系管理员", 500

    @app.errorhandler(400)
    def bad_request(e):
        return str(e), 400

    @app.errorhandler(404)
    def not_found(e):
        return "页面不存在", 404

    app.register_blueprint(blog_bp, url_prefix="/")
    app.register_blueprint(comment_bp, url_prefix="/")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(banner_bp, url_prefix="/")

    @app.context_processor
    def global_vars():
        try:
            cats, total_art = get_categories()
            banner_list = get_all_banner()
            site_name = get_site_name()
        except Exception:
            app.logger.error("全局模板上下文数据库报错:\n%s", traceback.format_exc())
            cats = []
            total_art = 0
            banner_list = []
            site_name = "博客"
        return {
            "categories": cats,
            "all_article_count": total_art,
            "site_name": site_name,
            "banner_list": banner_list,
            "csrf_token": session.get('csrf_token', ''),
            "now_year": date.today().year,
        }

    return app
