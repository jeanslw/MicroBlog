"""管理员蓝图 —— 登录、改密码、站点设置、图片上传。

重构要点：
- 用 Flask-Login 替代手动 session.admin_id 管理
- 用 Flask-WTF 表单 + CSRFProtect
- 登录失败计数走数据库表（多 worker 共享）
- 改密码后用 Flask-Login 的 logout + 重新登录机制
- 图片上传走 Pillow 安全流程（解压炸弹防护 + 缩放）
"""

import os
import subprocess
import threading
import zipfile
from datetime import datetime

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
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import safe_join

from app.admin import admin_bp
from app.crypto import encrypt_secret
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
from app.models import Admin, SiteConfig
from app.utils import (
    build_safe_filename,
    process_and_resize_logo,
    process_and_save_image,
    project_root,
    remove_static_upload,
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
            next_url = request.args.get("next") or url_for("admin.panel")
            # 防止开放重定向:仅放行站内相对路径,拦截 //evil.com 与 /\evil.com（反斜杠绕过）
            from urllib.parse import urlsplit

            parts = urlsplit(next_url)
            if (
                parts.scheme
                or parts.netloc
                or not next_url.startswith("/")
                or next_url.startswith("//")
                or "\\" in next_url
            ):
                next_url = url_for("admin.panel")
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
    """「关于我」编辑页：头像/邮箱/GitHub/个人主页/简介,数据存 site_config.about_*"""
    site = db.session.get(SiteConfig, 1)
    if not site:
        site = SiteConfig(id=1, site_name="我的博客", favicon_path="static/favicon.ico")
        db.session.add(site)
        db.session.commit()
    form = AboutForm()
    # 头像输入框预填外链地址（本地上传的内部 URL 不回填,避免误改）
    if request.method == "GET" and site.about_avatar and site.about_avatar.startswith(("http://", "https://")):
        form.avatar_url.data = site.about_avatar
    if form.validate_on_submit():
        old_avatar = site.about_avatar
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
                save_path = os.path.join(upload_dir("uploads/avatar"), final_name)
                process_and_resize_logo(avatar_file.stream, save_path, ext, max_edge=512)
                site.about_avatar = url_for("static", filename=f"uploads/avatar/{final_name}")
            except Exception:
                log.error("头像上传失败", exc_info=True)
                flash(_("头像上传失败，请重试"), "danger")
                return render_template("admin/about_setting.html", form=form, site=site)
        elif form.avatar_url.data and form.avatar_url.data.strip():
            site.about_avatar = form.avatar_url.data.strip()
        elif form.avatar_clear.data:
            site.about_avatar = ""
        site.about_bio = (form.about_bio.data or "").strip()
        site.about_email = (form.about_email.data or "").strip().lower()
        site.about_github = (form.about_github.data or "").strip()
        site.about_homepage = (form.about_homepage.data or "").strip()
        site.about_nickname = (form.about_nickname.data or "").strip()
        db.session.commit()
        # 清理被替换的旧头像文件,避免磁盘堆积
        if old_avatar and old_avatar != site.about_avatar:
            remove_static_upload(old_avatar)
        flash(_("关于我信息保存完成"), "success")
        return redirect(url_for("admin.about_setting"))
    return render_template("admin/about_setting.html", form=form, site=site)


def _site_setting_view(template):
    """站点设置公共视图：panel 首页与独立站点设置页共用"""
    site = db.session.get(SiteConfig, 1)
    if not site:
        site = SiteConfig(id=1, site_name="我的博客", favicon_path="static/favicon.ico")
        db.session.add(site)
        db.session.commit()
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
                    save_path = os.path.join(upload_dir("uploads/backgrounds"), final_name)
                    process_and_save_image(upload.stream, save_path, ext, max_width=1920, quality=90)
                    site.bg_custom = url_for("static", filename=f"uploads/backgrounds/{final_name}")
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
                save_path = os.path.join(upload_dir("uploads/logo"), final_name)
                process_and_resize_logo(
                    logo.stream,
                    save_path,
                    ext,
                    max_edge=current_app.config.get("LOGO_MAX_EDGE", 400),
                )
                site.logo_path = url_for("static", filename=f"uploads/logo/{final_name}")
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
            remove_static_upload(old_bg_custom)
        if old_logo and old_logo != site.logo_path:
            remove_static_upload(old_logo)
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
    save_dir = upload_dir("uploads")
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

    return jsonify({"url": f"/static/uploads/{final_name}"}), 200


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
        db.session.commit()
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
        data = _reset_serializer().loads(
            token, max_age=current_app.config.get("RESET_TOKEN_MAX_AGE", 1800)
        )
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
    """账户邮件设置页：上半「账户邮箱」（Admin.email），下半「SMTP 邮件设置」（site_config）。

    两个表单各自提交到自己的端点（/account 与 /mail_setting），
    互不校验对方字段,避免单表单提交误触发另一表单的验证。
    """
    site = db.session.get(SiteConfig, 1)
    if not site:
        site = SiteConfig(id=1, site_name="我的博客", favicon_path="static/favicon.ico")
        db.session.add(site)
        db.session.commit()
    email_form = AccountForm()
    mail_form = MailSettingForm(obj=site)
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
    """SMTP 邮件配置：存 site_config，保存后优先于 .env 的 BLOG_MAIL_* 生效。

    GET 一律跳转到合并后的「账户邮件设置」页（兼容旧书签/旧链接）。
    """
    if request.method == "GET":
        return redirect(url_for("admin.account"))
    site = db.session.get(SiteConfig, 1)
    if not site:
        site = SiteConfig(id=1, site_name="我的博客", favicon_path="static/favicon.ico")
        db.session.add(site)
        db.session.commit()
    form = MailSettingForm(obj=site)
    if form.validate_on_submit():
        site.mail_host = (form.mail_host.data or "").strip()
        site.mail_port = form.mail_port.data or 587
        site.mail_user = (form.mail_user.data or "").strip()
        if form.mail_password.data:
            site.mail_password = encrypt_secret(form.mail_password.data.strip())
        site.mail_from = (form.mail_from.data or "").strip().lower()
        site.mail_use_ssl = bool(form.mail_use_ssl.data)
        site.mail_use_tls = bool(form.mail_use_tls.data)
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
    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if uri.startswith("sqlite:///"):
        return uri[len("sqlite:///"):]
    return os.path.join(project_root(), "data", "blog.db")


def _mysql_creds():
    return {
        "host": os.environ.get("BLOG_MYSQL_HOST") or "localhost",
        "user": os.environ.get("BLOG_MYSQL_USER") or "root",
        "pwd": os.environ.get("BLOG_MYSQL_PWD") or "",
        "db": os.environ.get("BLOG_MYSQL_DB") or "flask_blog",
    }


def _safe_backup_name(name):
    """防路径穿越：仅允许 backup_*.zip / backup_*.db / backup_*.sql 纯文件名。"""
    if not name or name != os.path.basename(name) or name.startswith("."):
        return False
    return name.startswith("backup_") and name.endswith((".zip", ".db", ".sql"))


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


def _create_backup(backup_dir, tag=""):
    """备份打包为 zip：内含 .db（SQLite）或 .sql（MySQL）单个文件。

    SQLite 使用 VACUUM INTO 生成一致性快照（而非直接拷贝活动文件,避免
    并发写入导致备份文件损坏）；MySQL 走 mysqldump。

    tag: 文件名标记。恢复前自动备份传 "_snapshot",与手动备份在列表中一眼区分。
    """
    # 文件名精确到毫秒：同一秒内的手动备份与恢复前自动备份不再重名
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S") + f"_{now.microsecond // 1000:03d}"
    zip_name = f"backup_{timestamp}{tag}.zip"
    zip_path = os.path.join(backup_dir, zip_name)
    if _db_type() == "mysql":
        c = _mysql_creds()
        env = os.environ.copy()
        env["MYSQL_PWD"] = c["pwd"]
        # --single-transaction:InnoDB 一致性快照,备份不阻塞业务
        # --skip-add-locks:dump 内不生成 LOCK TABLES,恢复端不会因元数据锁(MDL)等待挂起
        # --default-character-set=utf8mb4:避免中文数据乱码
        # 注:mysqldump 不支持 --connect-timeout（exit 7 unknown variable），
        # 连接失败由子进程 timeout=120 兜底
        cmd = [
            "mysqldump",
            "--single-transaction",
            "--skip-add-locks",
            "--default-character-set=utf8mb4",
            "-h",
            c["host"],
            "-u",
            c["user"],
            c["db"],
        ]
        inner_name = f"backup_{timestamp}.sql"
        result = subprocess.run(cmd, capture_output=True, check=True, env=env, timeout=120)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(inner_name, result.stdout)
        return zip_name
    # SQLite:用 VACUUM INTO 生成一致性快照,避免热拷贝损坏
    inner_name = f"backup_{timestamp}.db"
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


# 模块级恢复锁：防止并发恢复（双击/多标签页）导致两个 mysql 进程 DDL 交错执行、损坏库表
_restore_lock = threading.Lock()


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
        data, _kind = _backup_payload(path)
        if _db_type() == "mysql":
            # 过滤 dump 中的 LOCK/UNLOCK TABLES 语句：恢复是单连接顺序执行，表锁没有意义，
            # 旧格式备份的 LOCK TABLES 反而可能被并发请求持有的元数据锁(MDL)阻塞,
            # 造成恢复超时中断、库表处于不一致状态（如 admin 表被删后未重建）
            data = b"\n".join(
                line
                for line in data.split(b"\n")
                if not line.lstrip().startswith((b"LOCK TABLES", b"UNLOCK TABLES"))
            )
        # 恢复前先自动做一次即时备份（文件名带 _snapshot 标记），便于回滚
        _create_backup(_backup_dir(), tag="_snapshot")
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
            cmd = [
                "mysql",
                "--default-character-set=utf8mb4",
                "--connect-timeout=10",
                "-h",
                c["host"],
                "-u",
                c["user"],
                c["db"],
            ]
            # 加 timeout 避免 mysqldump/mysql 客户端因等待输入而永久挂起
            # （如密码错误进入交互提示符会卡住请求）
            result = subprocess.run(
                cmd, input=data, capture_output=True, timeout=120, env=env
            )
            if result.returncode != 0:
                # 把 mysql 的 stderr 透出,便于定位（密码错误/表不存在等）
                raise RuntimeError(
                    result.stderr.decode("utf-8", errors="replace").strip()
                    or f"mysql exited with code {result.returncode}"
                )
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
                    admin_count = conn.execute(
                        db.text("SELECT COUNT(*) FROM admin")
                    ).scalar()
            if not admin_count:
                raise RuntimeError(
                    _("恢复不完整：admin 表缺失或无数据，请直接重新执行一次恢复")
                )
        else:
            db.session.remove()
            db.engine.dispose()
            with open(_sqlite_db_path(), "wb") as f:
                f.write(data)
        flash(_("恢复成功"), "success")
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
        _restore_lock.release()
    return redirect(url_for("admin.backup"))
