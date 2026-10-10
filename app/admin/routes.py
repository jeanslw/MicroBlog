"""管理员蓝图 —— 登录、改密码、站点设置、图片上传。

重构要点：
- 用 Flask-Login 替代手动 session.admin_id 管理
- 用 Flask-WTF 表单 + CSRFProtect
- 登录失败计数走数据库表（多 worker 共享）
- 改密码后用 Flask-Login 的 logout + 重新登录机制
- 图片上传走 Pillow 安全流程（解压炸弹防护 + 缩放）
"""

import contextlib
import os
import re
import signal
import subprocess
import threading
import time
import zipfile
from datetime import datetime
from functools import partial
from pathlib import Path

from flask import (
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask_babel import _
from flask_login import current_user, login_required, login_user, logout_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import safe_join

from app.admin import admin_bp
from app.crypto import encrypt_secret
from app.database import (
    SCHEMA_VERSION,
    get_or_create_about_profile,
    get_or_create_mail_setting,
    get_or_create_site_setting,
    pending_schema_migrations,
    run_schema_migrations,
    schema_version_cmp,
    sync_schema_version,
)
from app.extensions import (
    admin_required,
    check_login_lock,
    clear_login_fail,
    db,
    external_url_for,
    get_client_ip,
    log,
    rate_limit,
    record_login_fail,
    safe_redirect_path,
)
from app.forms import (
    AboutForm,
    AccountForm,
    ChangePwdForm,
    ForgotForm,
    LoginForm,
    MailSettingForm,
    ResetForm,
    SetupForm,
    SiteSettingForm,
    UploadImageForm,
)
from app.mail import MailError, send_mail
from app.models import Admin
from app.utils import (
    build_safe_filename,
    process_and_resize_logo,
    process_and_save_image,
    project_root,
    remove_uploaded_file,
    upload_dir,
)


@admin_bp.before_request
def _require_setup():
    """无管理员时，除引导页/静态资源外全部跳转到首次安装引导。"""
    if request.endpoint in ("admin.setup", "admin.static"):
        return None
    try:
        count = db.session.scalar(db.select(db.func.count(Admin.id)))
    except Exception:
        # 查询失败：区分「admin 表缺失」（如恢复中断/未初始化）与「数据库不可用」。
        # 表缺失视为未安装，同样进入引导页；数据库连接失败才放行，避免启动早期异常。
        try:
            from sqlalchemy import inspect as sa_inspect

            if sa_inspect(db.engine).has_table(Admin.__tablename__):
                return None
        except Exception:
            return None
        count = 0
    if not count:
        return redirect(url_for("admin.setup"))


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    # 已登录直接进管理后台
    if current_user.is_authenticated:
        return redirect(url_for("admin.panel"))

    form = LoginForm()
    if form.validate_on_submit():
        ip = get_client_ip()
        username = form.username.data.strip()
        password = form.password.data

        locked, remain = check_login_lock(ip, username)
        if locked:
            flash(_("登录失败次数过多,请 %(sec)s 秒后再试", sec=remain), "danger")
            return render_template("admin/login.html", form=form), 429

        admin = db.session.scalar(db.select(Admin).filter_by(username=username))
        if admin and check_password_hash(admin.password, password):
            login_user(admin, remember=False)
            session.permanent = True
            clear_login_fail(ip, username)
            flash(_("登录成功"), "success")
            # 防止开放重定向:仅放行站内相对路径（含 //evil.com、/\evil.com 等绕过变体）
            next_url = safe_redirect_path(request.args.get("next")) or url_for("admin.panel")
            return redirect(next_url)

        fails = record_login_fail(ip, username)
        if fails >= 5:
            flash(_("登录失败次数过多,请 5 分钟后再试"), "danger")
        else:
            flash(_("账号或密码错误（剩余尝试 %(n)s 次）", n=5 - fails), "danger")

    return render_template("admin/login.html", form=form)


@admin_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    session.clear()
    flash(_("已退出登录"), "info")
    return redirect(url_for("blog.index"))


@admin_bp.route("/panel", methods=["GET", "POST"])
@admin_required
def panel():
    """管理后台首页：左侧菜单 + 默认展示站点设置，便于后续扩展"""
    return _site_setting_view("admin/panel.html")


@admin_bp.route("/change_pwd", methods=["GET", "POST"])
@admin_required
def change_pwd():
    form = ChangePwdForm()
    if form.validate_on_submit():
        if not check_password_hash(current_user.password, form.old_pwd.data):
            flash(_("原密码错误"), "danger")
            return render_template("admin/change_pwd.html", form=form)
        current_user.password = generate_password_hash(form.new_pwd.data)
        db.session.commit()
        # 改密码后强制重新登录,使其他设备 session 失效
        logout_user()
        session.clear()
        flash(_("密码修改成功,请重新登录"), "success")
        return redirect(url_for("admin.login"))
    return render_template("admin/change_pwd.html", form=form)


@admin_bp.route("/site_setting", methods=["GET", "POST"])
@admin_required
def site_setting():
    return _site_setting_view("admin/site_setting.html")


@admin_bp.route("/about_setting", methods=["GET", "POST"])
@admin_required
def about_setting():
    """「关于我」编辑页：头像/邮箱/GitHub/个人主页/简介,数据存 about_profile 表"""
    about = get_or_create_about_profile()
    form = AboutForm()
    # 头像输入框预填外链地址（本地上传的内部 URL 不回填,避免误改）
    if request.method == "GET" and about.about_avatar and about.about_avatar.startswith(("http://", "https://")):
        form.avatar_url.data = about.about_avatar
    if form.validate_on_submit():
        old_avatar = about.about_avatar
        # 头像：上传优先 > 外链 URL > 清除 > 保持不变
        avatar_file = form.avatar_upload.data
        if avatar_file and avatar_file.filename:
            avatar_file.stream.seek(0)
            try:
                ext = avatar_file.filename.rsplit(".", 1)[1].lower()
                final_name = build_safe_filename(
                    avatar_file.filename,
                    base_name_max_len=current_app.config.get("UPLOAD_BASE_NAME_LEN", 50),
                )
                save_path = os.path.join(upload_dir("image", "avatar"), final_name)
                process_and_resize_logo(avatar_file.stream, save_path, ext, max_edge=512)
                about.about_avatar = url_for("main.uploaded_file", category="image", filename=f"avatar/{final_name}")
            except Exception:
                log.error("头像上传失败", exc_info=True)
                flash(_("头像上传失败，请重试"), "danger")
                return render_template("admin/about_setting.html", form=form, about=about)
        elif form.avatar_url.data and form.avatar_url.data.strip():
            about.about_avatar = form.avatar_url.data.strip()
        elif form.avatar_clear.data:
            about.about_avatar = ""
        about.about_bio = (form.about_bio.data or "").strip()
        about.about_email = (form.about_email.data or "").strip().lower()
        about.about_github = (form.about_github.data or "").strip()
        about.about_homepage = (form.about_homepage.data or "").strip()
        about.about_nickname = (form.about_nickname.data or "").strip()
        db.session.commit()
        # 清理被替换的旧头像文件,避免磁盘堆积
        if old_avatar and old_avatar != about.about_avatar:
            remove_uploaded_file(old_avatar)
        flash(_("关于我信息保存完成"), "success")
        return redirect(url_for("admin.about_setting"))
    return render_template("admin/about_setting.html", form=form, about=about)


def _site_setting_view(template):
    """站点设置公共视图：panel 首页与独立站点设置页共用"""
    site = get_or_create_site_setting()
    form = SiteSettingForm(obj=site)
    if form.validate_on_submit():
        site.site_name = form.site_name.data.strip()
        # 记录旧背景/旧 Logo,换图成功后再清理磁盘
        old_bg_custom = site.bg_custom
        old_logo = site.logo_path
        # 背景：优先处理上传文件，其次自定义 URL，最后内置图库
        bg_style = form.bg_style.data or "bg1"
        if bg_style == "custom":
            upload = form.bg_upload.data
            if upload and upload.filename:
                upload.stream.seek(0)
                try:
                    ext = upload.filename.rsplit(".", 1)[1].lower()
                    final_name = build_safe_filename(
                        upload.filename,
                        base_name_max_len=current_app.config.get("UPLOAD_BASE_NAME_LEN", 50),
                    )
                    save_path = os.path.join(upload_dir("image", "backgrounds"), final_name)
                    process_and_save_image(upload.stream, save_path, ext, max_width=1920, quality=90)
                    site.bg_custom = url_for(
                        "main.uploaded_file", category="image", filename=f"backgrounds/{final_name}"
                    )
                    site.bg_style = "custom"
                except Exception:
                    log.error("背景图上传失败", exc_info=True)
                    flash(_("背景图上传失败，请重试"), "danger")
                    return render_template(template, form=form, site=site)
            elif form.bg_custom.data and form.bg_custom.data.strip():
                site.bg_custom = form.bg_custom.data.strip()
                site.bg_style = "custom"
            else:
                # 选了 custom 但既没传图也没填 URL:回退内置背景,避免页面空白
                site.bg_custom = ""
                site.bg_style = "bg1"
        else:
            site.bg_custom = ""
            site.bg_style = bg_style
        # Logo：上传即保存，过大自动缩放（长边不超过配置上限）
        logo = form.logo_upload.data
        if logo and logo.filename:
            logo.stream.seek(0)
            try:
                ext = logo.filename.rsplit(".", 1)[1].lower()
                final_name = build_safe_filename(
                    logo.filename,
                    base_name_max_len=current_app.config.get("UPLOAD_BASE_NAME_LEN", 50),
                )
                save_path = os.path.join(upload_dir("image", "logo"), final_name)
                process_and_resize_logo(
                    logo.stream,
                    save_path,
                    ext,
                    max_edge=current_app.config.get("LOGO_MAX_EDGE", 400),
                )
                site.logo_path = url_for("main.uploaded_file", category="image", filename=f"logo/{final_name}")
            except Exception:
                log.error("Logo 上传失败", exc_info=True)
                flash(_("Logo 上传失败，请重试"), "danger")
                return render_template(template, form=form, site=site)
        # 评论总开关
        site.comments_enabled = bool(form.comments_enabled.data)
        # 栏目分类样式（书本树形 / 经典简洁）
        site.sidebar_style = form.sidebar_style.data if form.sidebar_style.data in ("book", "classic") else "book"
        db.session.commit()
        # 清理被替换的旧背景/旧 Logo 文件,避免磁盘堆积
        if old_bg_custom and old_bg_custom != site.bg_custom:
            remove_uploaded_file(old_bg_custom)
        if old_logo and old_logo != site.logo_path:
            remove_uploaded_file(old_logo)
        flash(_("站点设置保存完成"), "success")
        return redirect(url_for("admin.site_setting"))
    return render_template(template, form=form, site=site)


@admin_bp.route("/upload", methods=["POST"])
@admin_required
def upload_image():
    """接收编辑器上传的图片,自动压缩/缩放后返回 JSON {url} 或 {error}"""
    form = UploadImageForm()
    if not form.validate_on_submit():
        # 收集第一条错误
        for _, errs in form.errors.items():
            for err in errs:
                return jsonify({"error": err}), 400

    img = form.image.data
    try:
        ext = img.filename.rsplit(".", 1)[1].lower()
    except (IndexError, AttributeError):
        return jsonify({"error": _("文件名缺少扩展名")}), 400

    final_name = build_safe_filename(
        img.filename,
        base_name_max_len=current_app.config.get("UPLOAD_BASE_NAME_LEN", 100),
    )
    save_dir = upload_dir("image")
    save_path = os.path.join(save_dir, final_name)

    # FileSize 验证器读取过 stream，重置到开头避免 PIL 无法识别
    img.stream.seek(0)
    try:
        process_and_save_image(
            img.stream,
            save_path,
            ext,
            max_width=current_app.config.get("UPLOAD_MAX_WIDTH", 1200),
        )
    except Exception as e:
        log.error("图片处理失败: %s", e, exc_info=True)
        return jsonify({"error": _("图片处理失败,请重试")}), 500

    return jsonify({"url": f"/uploads/image/{final_name}"}), 200


# ── 首次安装引导 ─────────────────────────────────────────
@admin_bp.route("/setup", methods=["GET", "POST"])
def setup():
    """首次安装引导：仅在 admin 表为空/缺失时可用，创建首个管理员账号。"""
    # 幂等建表：恢复中断导致 admin 表缺失时，引导页仍可访问并自动补全缺失表
    db.create_all()
    count = db.session.scalar(db.select(db.func.count(Admin.id))) or 0
    if count > 0:
        return redirect(url_for("admin.login"))
    form = SetupForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        if db.session.scalar(db.select(Admin).filter_by(username=username)):
            flash(_("该账号已存在"), "danger")
            return render_template("admin/setup.html", form=form)
        admin = Admin(
            username=username,
            password=generate_password_hash(form.password.data),
            email=(form.email.data or "").strip().lower(),
        )
        db.session.add(admin)
        try:
            db.session.commit()
        except IntegrityError:
            # 多 worker 并发安装时,其他人可能已抢先建号（username 唯一约束）。
            # 回滚复查:已有管理员则视为安装完成,引导页自动失效。
            db.session.rollback()
            if db.session.scalar(db.select(db.func.count(Admin.id))):
                flash(_("管理员已由其他进程创建,请直接登录"), "info")
                return redirect(url_for("admin.login"))
            raise
        login_user(admin, remember=False)
        session.permanent = True
        flash(_("安装完成，欢迎使用"), "success")
        return redirect(url_for("admin.panel"))
    return render_template("admin/setup.html", form=form)


# ── 邮件找回密码 ─────────────────────────────────────────
def _reset_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="password-reset")


def _make_reset_token(admin):
    # payload 带当前密码哈希：重置后密码改变 → 旧 token 自动失效（单次有效）
    return _reset_serializer().dumps({"uid": admin.id, "pwh": admin.password})


@admin_bp.route("/forgot", methods=["GET", "POST"])
@rate_limit("forgot", limit=5, window_seconds=300)
def forgot():
    if current_user.is_authenticated:
        return redirect(url_for("admin.panel"))
    form = ForgotForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        email = (form.email.data or "").strip().lower()
        admin = db.session.scalar(db.select(Admin).filter_by(username=username))
        if admin and admin.email and admin.email == email:
            try:
                token = _make_reset_token(admin)
                reset_url = external_url_for("admin.reset", token=token)
                send_mail(
                    admin.email,
                    _("重置密码"),
                    _("点击以下链接重置密码（30 分钟内有效）：\n\n%(url)s", url=reset_url),
                )
            except MailError as e:
                # 发送失败也返回同一句，避免泄露账号是否存在（防账号枚举）
                log.warning("找回密码邮件发送失败: %s", e)
        # 无论是否命中都返回同一句，防止账号枚举
        flash(_("若账号存在且已绑定邮箱，找回邮件已发送"), "info")
        return redirect(url_for("admin.login"))
    return render_template("admin/forgot.html", form=form)


@admin_bp.route("/reset/<token>", methods=["GET", "POST"])
def reset(token):
    if current_user.is_authenticated:
        return redirect(url_for("admin.panel"))
    try:
        data = _reset_serializer().loads(token, max_age=current_app.config.get("RESET_TOKEN_MAX_AGE", 1800))
    except (SignatureExpired, BadSignature):
        flash(_("重置链接无效或已过期"), "danger")
        return redirect(url_for("admin.forgot"))
    admin = db.session.get(Admin, data.get("uid"))
    if not admin or admin.password != data.get("pwh"):
        flash(_("重置链接无效或已过期"), "danger")
        return redirect(url_for("admin.forgot"))
    form = ResetForm()
    if form.validate_on_submit():
        admin.password = generate_password_hash(form.new_pwd.data)
        db.session.commit()
        flash(_("密码已重置，请用新密码登录"), "success")
        return redirect(url_for("admin.login"))
    return render_template("admin/reset.html", form=form)


# ── 账户邮件设置（管理员邮箱 + SMTP 发信配置,原「邮件设置」页合并至此） ──
@admin_bp.route("/account", methods=["GET", "POST"])
@admin_required
def account():
    """账户邮件设置页：上半「账户邮箱」（Admin.email），下半「SMTP 邮件设置」（mail_setting 表）。

    两个表单各自提交到自己的端点（/account 与 /mail_setting），
    互不校验对方字段,避免单表单提交误触发另一表单的验证。
    """
    mail_cfg = get_or_create_mail_setting()
    email_form = AccountForm()
    mail_form = MailSettingForm(obj=mail_cfg)
    if request.method == "GET":
        email_form.email.data = current_user.email  # 邮箱回显
        mail_form.mail_password.data = ""  # 密码不回显，留空表示保持原值
    if email_form.validate_on_submit():
        current_user.email = (email_form.email.data or "").strip().lower()
        db.session.commit()
        flash(_("邮箱已保存"), "success")
        return redirect(url_for("admin.account"))
    return render_template("admin/account.html", form=email_form, mail_form=mail_form)


# ── SMTP 邮件设置（表单在「账户邮件设置」页内,本端点仅负责保存） ──
@admin_bp.route("/mail_setting", methods=["GET", "POST"])
@admin_required
def mail_setting():
    """SMTP 邮件配置：存 mail_setting 表，保存后优先于 app.env 的 BLOG_MAIL_* 生效。

    GET 一律跳转到合并后的「账户邮件设置」页（兼容旧书签/旧链接）。
    """
    if request.method == "GET":
        return redirect(url_for("admin.account"))
    mail_cfg = get_or_create_mail_setting()
    form = MailSettingForm(obj=mail_cfg)
    if form.validate_on_submit():
        mail_cfg.mail_host = (form.mail_host.data or "").strip()
        mail_cfg.mail_port = form.mail_port.data or 587
        mail_cfg.mail_user = (form.mail_user.data or "").strip()
        if form.mail_password.data:
            mail_cfg.mail_password = encrypt_secret(form.mail_password.data.strip())
        mail_cfg.mail_from = (form.mail_from.data or "").strip().lower()
        mail_cfg.mail_use_ssl = bool(form.mail_use_ssl.data)
        mail_cfg.mail_use_tls = bool(form.mail_use_tls.data)
        db.session.commit()
        flash(_("邮件设置已保存"), "success")
    return redirect(url_for("admin.account"))


@admin_bp.route("/mail_test", methods=["POST"])
@admin_required
def mail_test():
    """发送测试邮件到当前管理员邮箱,验证 SMTP 配置是否生效。"""
    to = (current_user.email or "").strip()
    if not to:
        flash(_("请先在「账户邮件设置」页填写管理员邮箱"), "warning")
        return redirect(url_for("admin.account"))
    try:
        send_mail(
            to,
            _("邮件配置测试"),
            _("这是一封测试邮件。若你收到此邮件，说明 SMTP 配置正确。"),
        )
        flash(_("测试邮件已发送，请查收（收件人：%(email)s）", email=to), "success")
    except MailError as e:
        log.warning("测试邮件发送失败: %s", e)
        flash(_("测试邮件发送失败：%(err)s", err=e), "danger")
    return redirect(url_for("admin.account"))


# ── 数据库备份与恢复 ─────────────────────────────────────
def _backup_dir():
    path = os.path.join(project_root(), "backups")
    os.makedirs(path, exist_ok=True)
    return path


def _db_type():
    return (os.environ.get("BLOG_DB_TYPE") or "sqlite").strip().lower()


def _sqlite_db_path():
    """当前 SQLite 库文件绝对路径；非文件型 SQLite（内存库等）返回 None。

    以 SQLAlchemy 真正使用的 URL 为准。此前按 `SQLALCHEMY_DATABASE_URI`
    字符串手工切 `sqlite:///` 前缀：URI 带 query（?check_same_thread=false 等）
    或使用 Windows 盘符路径时会切出错误路径，恢复就会写到别的文件（真库未变、
    还多出一个垃圾文件），所以改为读引擎 URL。
    """
    url = db.engine.url
    if url.get_backend_name() != "sqlite":
        return None
    database = url.database
    if not database or database == ":memory:":
        return None
    return os.path.abspath(database)


def _mysql_creds():
    return {
        "host": os.environ.get("BLOG_MYSQL_HOST") or "localhost",
        "user": os.environ.get("BLOG_MYSQL_USER") or "root",
        "pwd": os.environ.get("BLOG_MYSQL_PWD") or "",
        "db": os.environ.get("BLOG_MYSQL_DB") or "flask_blog",
    }


# 「禁用 TLS」的写法随客户端实现不同：MariaDB 客户端（镜像内 default-mysql-client）
# 与 MySQL ≤8.0 用 --skip-ssl；MySQL 8.4 客户端（含 Laragon 自带的 8.4.3）已移除该选项，
# 仅认 --ssl-mode=DISABLED。硬编码任一写法都会让另一侧以 exit 2（unknown option）直接失败。
# 下面的候选按优先级排列，以「空参数」收尾（两种写法都不支持时交回客户端默认行为）。
_TLS_DISABLE_CANDIDATES = (("--skip-ssl",), ("--ssl-mode=DISABLED",), ())

# mysqldump 的「非 root 受限账号兼容」候选（v1.3.6）。首选 = 完整兼容参数；
# 老客户端（MySQL 8.0.21 前无 --no-tablespaces）→ 退掉它保留 GTID 参数；
# 极老客户端（不认 --set-gtid-purged）→ 全部退回默认行为。
#   --no-tablespaces:业务账号无 PROCESS 权限时 dump 表空间语句报错
#   --set-gtid-purged=OFF:恢复端非 root 无 SUPER 权限处理 GTID 语句会失败
_MYSQLDUMP_EXTRA_CANDIDATES = (
    ("--no-tablespaces", "--set-gtid-purged=OFF"),
    ("--set-gtid-purged=OFF",),
    (),
)

# binary -> 上一次真正跑通的 (tls_args, extra_args) 组合
_client_args_cache: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}

# 客户端「不认识该参数」的报错特征（MySQL: unknown option / MariaDB: unknown variable）
_UNKNOWN_OPTION_MARKERS = ("unknown option", "unknown variable", "unrecognized option")


def _is_unknown_option_error(stderr):
    """客户端是否因「不认识该参数」而失败（如 MySQL 8.4: unknown option '--skip-ssl'）"""
    low = stderr.lower()
    return any(marker in low for marker in _UNKNOWN_OPTION_MARKERS)


def _arg_identity(arg):
    """参数名归一化（去引导线、去 =值、小写），用于把报错参数匹配回候选组合。"""
    return arg.lstrip("-").split("=", 1)[0].lower()


def _unknown_option_name(stderr):
    """从客户端报错中提取「不认识」的参数名;解析不出返回 None。

    形态示例：`unknown option '--no-tablespaces'` / `unknown variable 'set-gtid-purged'`。
    """
    m = re.search(r"unknown (?:option|variable)\s+['\"]?(-?-?[A-Za-z0-9_=-]+)", stderr)
    return _arg_identity(m.group(1)) if m else None


def _run_db_client(build_cmd, binary, env, extra_candidates=((),), **kwargs):
    """执行 mysql/mysqldump 子进程，返回 CompletedProcess；失败抛带客户端 stderr 的 RuntimeError。

    build_cmd(tls_args, extra_args) -> list[str]：用给定的「禁用 TLS」与「额外兼容」
    参数拼出完整命令行。

    tls 候选 × extra 候选按序试错。「unknown option」时从 stderr 提取具体参数名，
    跳过所有仍含该参数的组合（避免无谓重试）;其余错误（密码错/权限不足/连不上）
    原样透出,不重试。跑通后缓存 (tls_args, extra_args),后续调用零试错。

    为什么不能「探测」客户端支持哪种写法：`mysql --skip-ssl --version` 会**打印版本
    并以 0 退出**（mysql 客户端对 --version 提前返回，不再校验其余选项），于是
    --skip-ssl 被误判成可用，直到真正恢复时才以 exit 2 失败；而 `mysqldump --skip-ssl
    --version` 却会正常报错——同名参数在两个客户端里的校验时机不一致，探测结论不可信。
    故改为行为驱动：先用首选参数真跑一次，客户端报「未知选项」就换不含该参数的候选
    重试。未知选项在参数解析阶段即失败，不建连接、不写库、不产生任何副作用，因此
    重试是安全的（含恢复时携带的 dump 数据）。
    """
    if binary in _client_args_cache:
        combos = [_client_args_cache[binary]]
    else:
        combos = [(tls, extra) for tls in _TLS_DISABLE_CANDIDATES for extra in extra_candidates]
    i = 0
    while i < len(combos):
        tls_args, extra_args = combos[i]
        cmd = build_cmd(tls_args, extra_args)
        try:
            result = subprocess.run(cmd, capture_output=True, env=env, **kwargs)
        except FileNotFoundError:
            raise RuntimeError(f"未找到 {binary} 客户端，请先安装 MySQL/MariaDB 客户端（容器镜像已内置）") from None
        if result.returncode == 0:
            _client_args_cache[binary] = (tls_args, extra_args)
            return result
        # 不使用 check=True：CalledProcessError 只带退出码、丢掉 stderr，现场只剩
        # 「returned non-zero exit status 2」这种无从下手的报错（未知选项/密码错误/
        # 权限不足都无法区分）。
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        if _is_unknown_option_error(stderr):
            bad = _unknown_option_name(stderr)
            j = i + 1
            if bad:
                # 跳过所有仍包含该参数的候选组合
                while j < len(combos) and bad in {_arg_identity(a) for a in (*combos[j][0], *combos[j][1])}:
                    j += 1
            log.warning("%s 客户端不支持 %s，换下一个候选参数重试", binary, bad or "该参数")
            i = j
            continue
        raise RuntimeError(stderr or f"{binary} exited with code {result.returncode}")
    # 候选以「全空参数」收尾，理论上必有一个组合不含任何会触发 unknown option 的参数,
    # 故此处理论不可达；保留兜底，避免将来调整候选列表时静默返回 None。
    raise RuntimeError(f"未找到 {binary} 可用的参数组合，请检查客户端版本")


def _safe_backup_name(name):
    """防路径穿越：仅允许 mysql_backup_*/sqlite_backup_*/backup_* 纯文件名。

    兼容旧版 backup_*.zip/.db/.sql；新版带数据库类型前缀，便于区分备份来源。
    """
    if not name or name != os.path.basename(name) or name.startswith("."):
        return False
    return name.startswith(("backup_", "mysql_backup_", "sqlite_backup_")) and name.endswith((".zip", ".db", ".sql"))


def _resolved_backup_path(name):
    """把备份文件名安全解析为 backups 目录内的绝对路径；非法名称返回 None。

    双重防护：先 _safe_backup_name 白名单校验，再 safe_join 确保结果仍落在
    backups 目录内（safe_join 会阻断 ../ 等路径穿越），CodeQL 亦能识别该净化点。
    """
    if not _safe_backup_name(name):
        return None
    return safe_join(_backup_dir(), name)


def _list_backups(backup_dir):
    files = []
    for name in os.listdir(backup_dir):
        if not _safe_backup_name(name):
            continue
        p = os.path.join(backup_dir, name)
        if os.path.isfile(p):
            st = os.stat(p)
            files.append(
                {
                    "name": name,
                    "size": st.st_size,
                    "mtime_str": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
    files.sort(key=lambda x: x["name"], reverse=True)
    return files


def _mysqldump_cmd(creds, tls_args, extra_args=()):
    """拼 mysqldump 命令行；tls_args/extra_args 由 _run_db_client 试错决定。

    固定参数:
    --single-transaction:InnoDB 一致性快照,备份不阻塞业务;同时避免默认
      --lock-tables 对非 root 账号（无 LOCK TABLES 权限）的依赖
    --skip-add-locks:dump 内不生成 LOCK TABLES,恢复端不会因元数据锁(MDL)等待挂起
    --default-character-set=utf8mb4:避免中文数据乱码
    extra_args 候选（非 root 兼容,见 _MYSQLDUMP_EXTRA_CANDIDATES）:
      --no-tablespaces / --set-gtid-purged=OFF
    注:mysqldump 不支持 --connect-timeout（exit 7 unknown variable），
    连接失败由子进程 timeout=120 兜底；口令走 MYSQL_PWD 环境变量，不进命令行
    """
    return [
        "mysqldump",
        "--single-transaction",
        "--skip-add-locks",
        "--default-character-set=utf8mb4",
        *tls_args,
        *extra_args,
        "-h",
        creds["host"],
        "-u",
        creds["user"],
        creds["db"],
    ]


def _mysql_restore_cmd(creds, tls_args, extra_args=()):
    """拼 mysql 恢复命令行（dump 内容从 stdin 喂入）；tls_args 语义同 _mysqldump_cmd。"""
    return [
        "mysql",
        "--default-character-set=utf8mb4",
        "--connect-timeout=10",
        *tls_args,
        "-h",
        creds["host"],
        "-u",
        creds["user"],
        creds["db"],
    ]


def _create_backup(backup_dir, tag=""):
    """备份打包为 zip：内含 .db（SQLite）或 .sql（MySQL）单个文件。

    SQLite 使用 VACUUM INTO 生成一致性快照（而非直接拷贝活动文件,避免
    并发写入导致备份文件损坏）；MySQL 走 mysqldump。

    tag: 文件名标记。恢复前自动备份传 "_snapshot",与手动备份在列表中一眼区分。
    """
    # 文件名精确到毫秒：同一秒内的手动备份与恢复前自动备份不再重名
    # 带数据库类型前缀（mysql_/sqlite_）：混用两种数据库模式时备份来源一眼可辨，
    # 防止误把 MySQL 备份恢复到 SQLite（反之亦然，恢复端另有类型校验兜底）
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S") + f"_{now.microsecond // 1000:03d}"
    db_prefix = "mysql" if _db_type() == "mysql" else "sqlite"
    zip_name = f"{db_prefix}_backup_{timestamp}{tag}.zip"
    zip_path = os.path.join(backup_dir, zip_name)
    if _db_type() == "mysql":
        c = _mysql_creds()
        env = os.environ.copy()
        env["MYSQL_PWD"] = c["pwd"]
        # 固定参数说明见 _mysqldump_cmd;「禁用 TLS」与「非 root 兼容」参数均由
        # _run_db_client 按客户端实际行为自适应试错（内网链路无需 TLS;业务账号
        # 可能无 PROCESS/SUPER 权限）,跑通后缓存复用,备份与恢复两条路径共享。
        inner_name = f"{db_prefix}_backup_{timestamp}.sql"
        result = _run_db_client(
            partial(_mysqldump_cmd, c),
            "mysqldump",
            env,
            extra_candidates=_MYSQLDUMP_EXTRA_CANDIDATES,
            timeout=120,
        )
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(inner_name, result.stdout)
        return zip_name
    # SQLite:用 VACUUM INTO 生成一致性快照,避免热拷贝损坏
    inner_name = f"{db_prefix}_backup_{timestamp}.db"
    snapshot_path = os.path.join(backup_dir, f".snapshot_{timestamp}.db")
    try:
        with db.engine.begin() as conn:
            conn.execute(db.text("VACUUM INTO :path"), {"path": snapshot_path})
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(snapshot_path, arcname=inner_name)
    finally:
        # 清理临时快照文件
        try:
            if os.path.exists(snapshot_path):
                os.remove(snapshot_path)
        except OSError:
            pass
    return zip_name


def _backup_payload(path):
    """读取备份内容为 (bytes, kind)，kind ∈ {"db", "sql"}。兼容 .zip 与旧版 .db/.sql。

    path 必须为 _resolved_backup_path() 解析出的安全绝对路径。
    """
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            for n in zf.namelist():
                if n.endswith(".db"):
                    return zf.read(n), "db"
                if n.endswith(".sql"):
                    return zf.read(n), "sql"
        raise ValueError("zip 内未找到数据库文件")
    if path.endswith(".db"):
        with open(path, "rb") as f:
            return f.read(), "db"
    with open(path, "rb") as f:
        return f.read(), "sql"


@admin_bp.route("/backup", methods=["GET", "POST"])
@admin_required
def backup():
    backup_dir = _backup_dir()
    if request.method == "POST":
        try:
            filename = _create_backup(backup_dir)
            flash(_("备份成功：%(name)s", name=filename), "success")
        except Exception as e:
            log.error("备份失败: %s", e, exc_info=True)
            flash(_("备份失败：%(err)s", err=e), "danger")
        return redirect(url_for("admin.backup"))
    return render_template("admin/backup.html", backups=_list_backups(backup_dir), db_type=_db_type())


@admin_bp.route("/backup/download/<name>")
@admin_required
def backup_download(name):
    if not _safe_backup_name(name):
        abort(404)
    return send_from_directory(_backup_dir(), name, as_attachment=True)


@admin_bp.route("/backup/delete/<name>", methods=["POST"])
@admin_required
def backup_delete(name):
    path = _resolved_backup_path(name)
    if not path:
        abort(404)
    try:
        os.remove(path)
        flash(_("备份已删除"), "success")
    except OSError:
        flash(_("删除失败"), "danger")
    return redirect(url_for("admin.backup"))


# ── 数据库 schema 迁移（版本化迁移框架的后台入口） ──────────
@admin_bp.route("/migrate", methods=["GET", "POST"])
@admin_required
def migrate_db():
    """数据库 schema 迁移页：展示当前/目标版本与待应用迁移,支持手动触发。

    迁移由 schema_version 驱动:程序版本 > 数据库版本时启动也会自动执行,
    本页用于升级后确认状态或排查时手动重放,与启动共用 run_schema_migrations。
    """
    if request.method == "POST":
        try:
            applied = run_schema_migrations()
        except Exception as e:
            log.error("数据库迁移失败", exc_info=True)
            flash(_("数据库迁移失败：%(err)s", err=e), "danger")
            return redirect(url_for("admin.migrate_db"))
        if applied:
            names = "、".join(f"v{v}（{desc}）" for v, desc in applied)
            flash(_("迁移完成：%(names)s", names=names), "success")
        else:
            flash(_("数据库已是最新 schema 版本，无需迁移"), "info")
        return redirect(url_for("admin.migrate_db"))

    current = sync_schema_version()
    pending = pending_schema_migrations(current)
    ahead = current is not None and schema_version_cmp(current, SCHEMA_VERSION) > 0
    return render_template(
        "admin/migrate_db.html",
        current_version=current,
        target_version=SCHEMA_VERSION,
        pending=pending,
        up_to_date=current is not None and not pending and not ahead,
        ahead=ahead,
    )


# ── 恢复互斥：进程内锁 + 跨进程文件锁 ─────────────────────
# 并发恢复（双击/多标签页/两个 worker）会让两个 mysql 进程 DDL 交错执行，
# 或让两个进程同时改写同一个 SQLite 文件，直接损坏库表。
# 模块级 threading.Lock 只在单个进程内有效，gunicorn -w 4 时每个 worker
# 各有一份，两个请求落到不同 worker 就完全挡不住 —— 因此必须再加跨进程锁。
_restore_lock = threading.Lock()
# 锁文件超过该秒数视为残留（持锁进程被 kill -9 时不会执行释放逻辑）
_RESTORE_LOCK_STALE_SECONDS = 3600
# 本进程持有的锁文件句柄：(fd, path)；未持有时为 None
_restore_lock_file = None


def _acquire_restore_file_lock() -> bool:
    """获取跨进程恢复锁（backups/.restore.lock，O_CREAT|O_EXCL 独占创建）。

    返回 False 表示已有恢复在进行。目录不可写等异常下退化为「放行」：
    进程内锁仍然生效，且宁可允许恢复也不能把功能彻底锁死。
    """
    global _restore_lock_file
    path = os.path.join(_backup_dir(), ".restore.lock")
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            stale = time.time() - os.path.getmtime(path) > _RESTORE_LOCK_STALE_SECONDS
            if not stale:
                return False
            log.warning("发现残留恢复锁（超过 %ss），接管: %s", _RESTORE_LOCK_STALE_SECONDS, path)
            os.remove(path)
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError:
            return False
    except OSError as e:
        log.warning("创建恢复锁文件失败，退化为进程内锁: %s", e)
        _restore_lock_file = None
        return True
    with contextlib.suppress(OSError):
        os.write(fd, str(os.getpid()).encode("ascii"))
    _restore_lock_file = (fd, path)
    return True


def _release_restore_file_lock():
    """释放跨进程恢复锁（关闭句柄并删除锁文件）"""
    global _restore_lock_file
    if not _restore_lock_file:
        return
    fd, path = _restore_lock_file
    _restore_lock_file = None
    with contextlib.suppress(OSError):
        os.close(fd)
    with contextlib.suppress(OSError):
        os.remove(path)


def _request_worker_recycle() -> bool:
    """请求 gunicorn 平滑重启（SIGHUP 给 master），让所有 worker 重新打开数据库。

    恢复等于「换库文件 / 重建所有表」，但恢复请求只能归还自己 worker 的连接
    （db.session.remove + engine.dispose）：其它 worker 仍持有指向旧库的连接，
    会继续返回恢复前的数据，甚至把旧内容再写回去。
    gunicorn master 收到 SIGHUP 会平滑重启全部 worker（在途请求先处理完），
    新 worker 重新建连即可看到恢复后的数据；waitress/开发服务器是单进程，
    父进程不是 gunicorn 时不做任何事。
    """
    if os.name != "posix":
        return False
    try:
        with open(f"/proc/{os.getppid()}/cmdline", "rb") as f:
            cmdline = f.read().decode("utf-8", "replace")
    except OSError:
        return False
    if "gunicorn" not in cmdline:
        return False
    sighup = getattr(signal, "SIGHUP", None)  # Windows 无 SIGHUP；posix 守卫已拦截，此处为类型检查与双保险
    if sighup is None:
        return False
    try:
        os.kill(os.getppid(), sighup)
    except OSError as e:
        log.warning("向 gunicorn 发送 SIGHUP 失败，请手动重启服务: %s", e)
        return False
    log.info("已请求 gunicorn 平滑重启，确保所有 worker 重新打开恢复后的数据库")
    return True


def _verify_sqlite_backup_file(path: str):
    """校验待恢复的 SQLite 备份文件：结构完好 + admin 表存在且有数据。

    在「替换线上库之前」对临时文件校验：损坏或空白的备份绝不允许覆盖线上库，
    否则会出现「提示恢复成功，但从此无法登录后台、只能靠快照回滚」的最坏结果。
    使用独立引擎（不复用应用连接池），校验过程完全不碰线上库。
    """
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{Path(path).as_posix()}")
    try:
        try:
            with engine.connect() as conn:
                status = conn.execute(db.text("PRAGMA integrity_check")).scalar()
                if str(status).strip().lower() != "ok":
                    raise RuntimeError(
                        _("恢复失败：备份文件已损坏（SQLite integrity_check: %(status)s）", status=status)
                    )
                tables = {row[0] for row in conn.execute(db.text("SELECT name FROM sqlite_master WHERE type='table'"))}
                if "admin" not in tables:
                    raise RuntimeError(_("恢复不完整：备份中缺少 admin 表，请确认该文件是本博客的数据库备份"))
                admin_count = conn.execute(db.text("SELECT COUNT(*) FROM admin")).scalar()
            if not admin_count:
                raise RuntimeError(_("恢复不完整：admin 表为空，恢复后无法登录后台，请重新执行恢复"))
        except RuntimeError:
            raise
        except Exception as e:
            # 例如把 .sql / 文本文件当 .db 恢复：SQLite 报 "file is not a database"
            raise RuntimeError(_("恢复失败：备份文件不是有效的 SQLite 数据库（%(err)s）", err=e)) from e
    finally:
        engine.dispose()


def _restore_sqlite_database(data: bytes) -> bool:
    """用备份内容替换当前 SQLite 库文件；返回是否需要人工重启服务。

    步骤：写临时文件 → 校验该临时文件 → os.replace 原子替换 → 请求 worker 回收。
    - 原子替换：其它 worker 若正在读旧库，看到的仍是替换前完整的旧 inode
      （数据稍旧但一致），绝不会读到写了一半的文件 —— 旧实现以 "wb" 直接覆盖
      活动库文件，多 worker 下极易产生 "database disk image is malformed"。
    - 先校验后替换：损坏/空白的备份不会碰到线上库。
    - 仅 Windows 上库文件被独占打开、无法原子替换时才退化为就地覆盖，此时如又
      无法触发 worker 回收，就必须提示人工重启（返回 True）。
    """
    path = _sqlite_db_path()
    if not path:
        raise RuntimeError(
            _(
                "当前数据库不是文件型 SQLite（如内存库），无法从备份恢复；"
                "请改用 MySQL，或设置 BLOG_SQLITE_PATH 指向库文件后重试"
            )
        )
    # 先归还本请求持有的连接并清空连接池：否则 Windows 上文件被占用无法替换
    db.session.remove()
    db.engine.dispose()
    tmp_path = f"{path}.restore-{os.getpid()}.tmp"
    try:
        with open(tmp_path, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        _verify_sqlite_backup_file(tmp_path)
        atomic = True
        try:
            os.replace(tmp_path, path)
        except OSError as e:
            atomic = False
            log.warning("原子替换 SQLite 库失败（%s），退化为就地覆盖: %s", e, path)
            with open(path, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
    # 丢弃恢复前的连接缓存，让后续请求读到新文件
    db.engine.dispose()
    recycled = _request_worker_recycle()
    if not atomic:
        log.warning("SQLite 恢复使用了非原子覆盖，如站点异常请重启服务")
    return (not atomic) and not recycled


@admin_bp.route("/backup/restore/<name>", methods=["POST"])
@admin_required
def backup_restore(name):
    path = _resolved_backup_path(name)
    if not path:
        abort(404)
    if not os.path.isfile(path):
        flash(_("备份文件不存在"), "danger")
        return redirect(url_for("admin.backup"))
    if not _restore_lock.acquire(blocking=False):
        flash(_("已有恢复任务进行中，请勿重复提交"), "warning")
        return redirect(url_for("admin.backup"))
    try:
        # 跨进程锁：模块级 Lock 只覆盖单个 worker（见 _acquire_restore_file_lock）
        if not _acquire_restore_file_lock():
            flash(_("已有恢复任务进行中（可能来自其他进程或标签页），请稍后重试"), "warning")
            return redirect(url_for("admin.backup"))
        data, _kind = _backup_payload(path)
        # ── 备份类型校验：按 zip 内实际内容（.sql/.db）判断，与文件名无关 ──
        # 防止跨类型误恢复（MySQL 备份恢复到 SQLite 或反之）破坏当前数据库
        if _db_type() == "mysql" and _kind != "sql":
            flash(
                _("恢复失败：该备份为 SQLite（.db）格式，无法恢复到 MySQL 数据库；如需迁移数据请手动处理"),
                "danger",
            )
            return redirect(url_for("admin.backup"))
        if _db_type() == "sqlite" and _kind != "db":
            flash(
                _("恢复失败：该备份为 MySQL（.sql）格式，无法恢复到 SQLite 数据库；如需迁移数据请手动处理"),
                "danger",
            )
            return redirect(url_for("admin.backup"))
        if _db_type() == "mysql":
            # 过滤 dump 中的 LOCK/UNLOCK TABLES 语句：恢复是单连接顺序执行，表锁没有意义，
            # 旧格式备份的 LOCK TABLES 反而可能被并发请求持有的元数据锁(MDL)阻塞,
            # 造成恢复超时中断、库表处于不一致状态（如 admin 表被删后未重建）
            data = b"\n".join(
                line for line in data.split(b"\n") if not line.lstrip().startswith((b"LOCK TABLES", b"UNLOCK TABLES"))
            )
        # 恢复前先自动做一次即时备份（文件名带 _snapshot 标记），便于回滚
        _create_backup(_backup_dir(), tag="_snapshot")
        # SQLite 分支据其返回值判断是否需要提示人工重启（见 _restore_sqlite_database）
        restart_needed = False
        if _db_type() == "mysql":
            c = _mysql_creds()
            env = os.environ.copy()
            env["MYSQL_PWD"] = c["pwd"]
            # 关键：先归还当前请求的数据库连接并清空连接池。
            # 本请求在 @admin_required/current_user 阶段已执行过 SELECT admin,
            # 其事务持有的连接持有 admin 表元数据锁(MDL),会让恢复端
            # DROP TABLE 永久阻塞直至 120s 超时 —— 且此时 DROP 可能刚好完成,
            # mysql 被杀后 dump 其余部分(CREATE/INSERT)不再执行,留下残库。
            # session.remove() 归还请求自身占用的连接,dispose() 清空池中其余连接。
            db.session.remove()
            db.engine.dispose()
            # 「禁用 TLS」参数与上方备份命令共用同一套自适应逻辑（见 _run_db_client）
            # 加 timeout 避免 mysql 客户端因等待输入而永久挂起
            # （如密码错误进入交互提示符会卡住请求）；失败时内部透出客户端 stderr
            _run_db_client(partial(_mysql_restore_cmd, c), "mysql", env, input=data, timeout=120)
            # 丢弃恢复前留下的旧连接缓存，确保后续请求读到恢复后的数据
            db.engine.dispose()
            # 恢复完整性校验：admin 表是 dump 中首张建表且必含 INSERT,
            # 若表缺失或无数据,说明恢复被中断、库表处于不一致状态
            with db.engine.connect() as conn:
                admin_count = conn.execute(
                    db.text(
                        "SELECT COUNT(*) FROM information_schema.tables "
                        "WHERE table_schema = :db AND table_name = 'admin'"
                    ),
                    {"db": c["db"]},
                ).scalar()
                if admin_count:
                    admin_count = conn.execute(db.text("SELECT COUNT(*) FROM admin")).scalar()
            if not admin_count:
                raise RuntimeError(_("恢复不完整：admin 表缺失或无数据，请直接重新执行一次恢复"))
            # 其它 worker 的连接池在恢复期间未归还，仍指向旧的库/表结构：
            # 请求 gunicorn 平滑重启，让它们重新建连（单进程部署下为空操作）
            _request_worker_recycle()
        else:
            # SQLite：原子替换库文件 + integrity_check/admin 表校验，
            # 返回值表示是否必须人工重启服务（非原子覆盖且未能触发平滑重启）
            restart_needed = _restore_sqlite_database(data)
        flash(_("恢复成功"), "success")
        if restart_needed:
            flash(
                _(
                    "提示：本次恢复无法自动重载（未使用原子替换且未能触发服务平滑重启），"
                    "请重启一次服务（gunicorn/容器）后再使用，否则其它进程可能仍读到旧数据"
                ),
                "warning",
            )
    except subprocess.TimeoutExpired:
        log.error("MySQL 恢复超时", exc_info=True)
        flash(
            _("恢复失败：MySQL 命令执行超时，请检查连接配置；如页面异常请重新执行一次恢复"),
            "danger",
        )
    except Exception as e:
        log.error("恢复失败: %s", e, exc_info=True)
        flash(_("恢复失败：%(err)s", err=e), "danger")
    finally:
        _release_restore_file_lock()
        _restore_lock.release()
    return redirect(url_for("admin.backup"))
