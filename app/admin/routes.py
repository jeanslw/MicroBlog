"""管理员蓝图 —— 登录、改密码、站点设置、图片上传。

重构要点：
- 用 Flask-Login 替代手动 session.admin_id 管理
- 用 Flask-WTF 表单 + CSRFProtect
- 登录失败计数走数据库表（多 worker 共享）
- 改密码后用 Flask-Login 的 logout + 重新登录机制
- 图片上传走 Pillow 安全流程（解压炸弹防护 + 缩放）
"""

import os

from flask import current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_babel import _
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from app.admin import admin_bp
from app.extensions import (
    check_login_lock,
    clear_login_fail,
    db,
    get_client_ip,
    log,
    record_login_fail,
)
from app.forms import ChangePwdForm, LoginForm, SiteSettingForm, UploadImageForm
from app.models import Admin, SiteConfig
from app.utils import (
    build_safe_filename,
    process_and_resize_logo,
    process_and_save_image,
    remove_static_upload,
    upload_dir,
)


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    # 已登录直接跳首页
    if current_user.is_authenticated:
        return redirect(url_for("blog.index"))

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
            next_url = request.args.get("next") or url_for("blog.index")
            # 防止开放重定向（//evil.com 也不能放行）
            if not next_url.startswith("/") or next_url.startswith("//"):
                next_url = url_for("blog.index")
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


@admin_bp.route("/change_pwd", methods=["GET", "POST"])
@login_required
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
@login_required
def site_setting():
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
                    return render_template("admin/site_setting.html", form=form, site=site)
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
                return render_template("admin/site_setting.html", form=form, site=site)
        db.session.commit()
        # 清理被替换的旧背景/旧 Logo 文件,避免磁盘堆积
        if old_bg_custom and old_bg_custom != site.bg_custom:
            remove_static_upload(old_bg_custom)
        if old_logo and old_logo != site.logo_path:
            remove_static_upload(old_logo)
        flash(_("站点设置保存完成"), "success")
        return redirect(url_for("admin.site_setting"))
    return render_template("admin/site_setting.html", form=form, site=site)


@admin_bp.route("/upload", methods=["POST"])
@login_required
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
