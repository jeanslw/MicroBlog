"""Banner 蓝图 —— 轮播图管理（列表/增/改/删）。

重构要点：
- Flask-WTF 表单 + 文件字段校验（FileAllowed / FileSize）
- Pillow 安全处理（解压炸弹防护 + 等比缩放）
- 删除时 try/finally 关闭游标 → ORM 自动管理,删除文件失败不阻断
- url_prefix="/banner",所以路由用相对路径
"""

import os
from datetime import datetime

from flask import current_app, flash, redirect, render_template, url_for
from flask_babel import _
from flask_login import login_required

from app.banner import banner_bp
from app.extensions import db, log, safe_url
from app.forms import BannerForm
from app.models import Banner
from app.utils import (
    build_safe_filename,
    process_and_save_image,
    project_root,
    upload_dir,
)


@banner_bp.route("/")
@login_required
def banner_list():
    banners = db.session.scalars(db.select(Banner).order_by(Banner.sort.desc())).all()
    return render_template("banner/banner_manage.html", banner_list=banners)


@banner_bp.route("/add", methods=["POST"])
@login_required
def banner_add():
    form = BannerForm()
    if not form.validate_on_submit():
        for field, errs in form.errors.items():
            for err in errs:
                flash(f"{field}: {err}", "danger")
        return redirect(url_for("banner.banner_list"))

    img = form.banner_img.data
    if not img or not img.filename:
        flash(_("请选择轮播图片"), "danger")
        return redirect(url_for("banner.banner_list"))

    try:
        ext = img.filename.rsplit(".", 1)[1].lower()
    except (IndexError, AttributeError):
        flash(_("文件名缺少扩展名"), "danger")
        return redirect(url_for("banner.banner_list"))

    final_name = build_safe_filename(
        img.filename,
        base_name_max_len=current_app.config.get("UPLOAD_BASE_NAME_LEN", 100),
    )
    save_dir = upload_dir("banner")
    save_path = os.path.join(save_dir, final_name)

    # FileSize 验证器读取过 stream，重置到开头避免 PIL 无法识别
    img.stream.seek(0)
    try:
        process_and_save_image(
            img.stream,
            save_path,
            ext,
            max_width=current_app.config.get("BANNER_MAX_WIDTH", 1920),
        )
    except Exception as e:
        log.error("Banner 图片处理失败: %s", e, exc_info=True)
        flash(_("图片处理失败,请重试"), "danger")
        return redirect(url_for("banner.banner_list"))

    img_path = f"/static/banner/{final_name}"
    link = safe_url(form.link_url.data or "")[: current_app.config.get("LINK_MAX_LEN", 500)]
    title = (form.title.data or "").strip()[:100]
    desc = (form.desc_text.data or "").strip()[:200]
    sort_num = form.sort_num.data or 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    banner = Banner(
        img_path=img_path,
        link_url=link,
        title=title,
        desc_text=desc,
        sort=sort_num,
        create_time=now,
    )
    db.session.add(banner)
    db.session.commit()
    flash(_("新增轮播成功"), "success")
    return redirect(url_for("banner.banner_list"))


@banner_bp.route("/edit/<int:bid>", methods=["POST"])
@login_required
def banner_edit(bid):
    form = BannerForm()
    if not form.validate_on_submit():
        for field, errs in form.errors.items():
            for err in errs:
                flash(f"{field}: {err}", "danger")
        return redirect(url_for("banner.banner_list"))

    banner = db.session.get(Banner, bid)
    if not banner:
        flash(_("轮播图不存在"), "warning")
        return redirect(url_for("banner.banner_list"))

    banner.link_url = safe_url(form.link_url.data or "")[: current_app.config.get("LINK_MAX_LEN", 500)]
    banner.title = (form.title.data or "").strip()[:100]
    banner.desc_text = (form.desc_text.data or "").strip()[:200]
    banner.sort = form.sort_num.data or 0

    img = form.banner_img.data
    if img and img.filename:
        try:
            ext = img.filename.rsplit(".", 1)[1].lower()
        except (IndexError, AttributeError):
            flash(_("文件名缺少扩展名"), "danger")
            return redirect(url_for("banner.banner_list"))
        final_name = build_safe_filename(
            img.filename,
            base_name_max_len=current_app.config.get("UPLOAD_BASE_NAME_LEN", 100),
        )
        save_dir = upload_dir("banner")
        save_path = os.path.join(save_dir, final_name)
        # FileSize 验证器读取过 stream，重置到开头避免 PIL 无法识别
        img.stream.seek(0)
        try:
            process_and_save_image(
                img.stream,
                save_path,
                ext,
                max_width=current_app.config.get("BANNER_MAX_WIDTH", 1920),
            )
        except Exception as e:
            log.error("Banner 图片处理失败: %s", e, exc_info=True)
            flash(_("图片处理失败,请重试"), "danger")
            return redirect(url_for("banner.banner_list"))
        # 删除旧文件（失败仅告警）
        if banner.img_path:
            old_abs = os.path.join(project_root(), banner.img_path.lstrip("/"))
            try:
                if os.path.exists(old_abs):
                    os.remove(old_abs)
            except OSError:
                log.warning("删除旧 banner 文件失败 bid=%s", bid, exc_info=True)
        banner.img_path = f"/static/banner/{final_name}"

    db.session.commit()
    flash(_("修改完成"), "success")
    return redirect(url_for("banner.banner_list"))


@banner_bp.route("/del/<int:bid>", methods=["POST"])
@login_required
def banner_del(bid):
    """删除 banner 记录 + 物理文件（文件删除失败不阻断）"""
    banner = db.session.get(Banner, bid)
    if not banner:
        flash(_("轮播图不存在"), "warning")
        return redirect(url_for("banner.banner_list"))

    # 先删除物理文件
    if banner.img_path:
        abs_path = os.path.join(project_root(), banner.img_path.lstrip("/"))
        try:
            if os.path.exists(abs_path):
                os.remove(abs_path)
        except OSError:
            log.warning("删除 banner 物理文件失败 bid=%s", bid, exc_info=True)

    db.session.delete(banner)
    db.session.commit()
    flash(_("已删除"), "success")
    return redirect(url_for("banner.banner_list"))
