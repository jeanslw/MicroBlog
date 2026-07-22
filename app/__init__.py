import os
import secrets
from flask import Flask, session, request, abort
import traceback
from config import SECRET_KEY, SEND_FILE_MAX_AGE, MAX_CONTENT_LENGTH
from app.db import close_db
from app.extensions import get_categories, get_site_name
from app.blog import blog_bp
from app.comment import comment_bp
from app.admin import admin_bp
from app.banner import banner_bp
from app.banner.queries import get_all_banner


def create_app():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    template_dir = os.path.join(root_dir, 'templates')
    static_dir = os.path.join(root_dir, 'static')
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    app.secret_key = SECRET_KEY
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = SEND_FILE_MAX_AGE
    app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

    # 请求结束时自动关闭数据库连接
    app.teardown_appcontext(close_db)

    # CSRF 保护
    @app.before_request
    def csrf_protect():
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_hex(32)
        if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            submitted = request.form.get('csrf_token')
            if not submitted or not secrets.compare_digest(session['csrf_token'], submitted):
                abort(400, 'CSRF 验证失败，请刷新页面后重试')

    @app.errorhandler(Exception)
    def all_err_handler(e):
        print("=====请求全局异常完整堆栈=====")
        traceback.print_exc()
        return "500 服务器内部错误，请查看控制台日志", 500

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
            print("=====全局模板上下文数据库报错=====")
            traceback.print_exc()
            cats = []
            total_art = 0
            banner_list = []
            site_name = "博客"
        return {
            "categories": cats,
            "all_article_count": total_art,
            "site_name": site_name,
            "banner_list": banner_list,
            "csrf_token": session.get('csrf_token', '')
        }

    return app
