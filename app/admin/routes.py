import logging
import os
import uuid
from datetime import datetime

from flask import render_template, request, redirect, url_for, flash, session, jsonify
from PIL import Image
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from app.admin import admin_bp
from app.db import get_db, DictCursor, IntegrityError
from app.extensions import (
    admin_required, get_client_ip, check_login_lock, record_login_fail,
    clear_login_fail,
)

log = logging.getLogger(__name__)

# 业务校验
CAT_NAME_MAX_LEN = 60
SITE_NAME_MAX_LEN = 100
PASSWORD_MIN_LEN = 6

# 文章图片上传相关（与 banner 保持一致的安全策略）
UPLOAD_ALLOWED_EXT = {"jpg", "jpeg", "png", "gif"}
UPLOAD_ALLOWED_MIME = {"image/jpeg", "image/png", "image/gif"}
UPLOAD_MAX_SIZE = 10 * 1024 * 1024  # 10MB
UPLOAD_BASE_NAME_LEN = 100
UPLOAD_MAX_WIDTH = 1200  # 上传图片最大宽度（像素），超过则等比缩放


# 管理员登录
@admin_bp.route('/login', methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = get_client_ip()
        user = request.form.get("username", "").strip()
        pwd = request.form.get("password", "").strip()

        if not user or not pwd:
            flash("请输入账号和密码")
            return render_template("admin/login.html")

        locked, remain = check_login_lock(ip, user)
        if locked:
            flash(f"登录失败次数过多，请 {remain} 秒后再试")
            return render_template("admin/login.html"), 429

        db = get_db()
        cur = db.cursor(DictCursor)
        cur.execute("SELECT id, username, password FROM admin WHERE username=%s", (user,))
        admin_info = cur.fetchone()
        cur.close()

        if admin_info and check_password_hash(admin_info["password"], pwd):
            session.permanent = True
            session["admin_id"] = admin_info["id"]
            session["admin_user"] = admin_info["username"]
            clear_login_fail(ip, user)
            flash("登录成功")
            return redirect(url_for("blog.index"))

        fails = record_login_fail(ip, user)
        if fails >= 5:
            flash("登录失败次数过多，请 5 分钟后再试")
        else:
            flash(f"账号或密码错误（剩余尝试 {5 - fails} 次）")
    return render_template("admin/login.html")


# 退出登录（改 POST，避免被 CSRF 强制登出）
@admin_bp.route('/logout', methods=["POST"])
def logout():
    session.clear()
    flash("已退出登录")
    return redirect(url_for("blog.index"))


# 修改密码
@admin_bp.route('/change_pwd', methods=["GET", "POST"])
@admin_required
def change_pwd():
    admin_id = session["admin_id"]
    if request.method == "POST":
        old_pwd = request.form.get("old_pwd", "").strip()
        new_pwd = request.form.get("new_pwd", "").strip()
        confirm = request.form.get("confirm_pwd", "").strip()

        if new_pwd != confirm:
            flash("两次新密码不一致")
            return render_template("admin/change_pwd.html")
        if len(new_pwd) < PASSWORD_MIN_LEN:
            flash(f"新密码至少 {PASSWORD_MIN_LEN} 位")
            return render_template("admin/change_pwd.html")

        db = get_db()
        cur = db.cursor(DictCursor)
        cur.execute("SELECT password FROM admin WHERE id=%s", (admin_id,))
        row = cur.fetchone()
        if not row or not check_password_hash(row["password"], old_pwd):
            cur.close()
            flash("原密码错误")
            return render_template("admin/change_pwd.html")

        new_hashed = generate_password_hash(new_pwd)
        try:
            cur.execute("UPDATE admin SET password=%s WHERE id=%s", (new_hashed, admin_id))
            db.commit()
        finally:
            cur.close()
        flash("密码修改成功，请重新登录")
        session.clear()
        return redirect(url_for("admin.login"))
    return render_template("admin/change_pwd.html")


# 站点设置
@admin_bp.route('/site_setting', methods=["GET", "POST"])
@admin_required
def site_setting():
    db = get_db()
    cur = db.cursor(DictCursor)
    if request.method == "POST":
        name = request.form.get("site_name", "").strip()
        if not name or len(name) > SITE_NAME_MAX_LEN:
            flash(f"站点名称不能为空且不超过 {SITE_NAME_MAX_LEN} 字符")
            cur.close()
            return render_template("admin/site_setting.html", site={"site_name": name})
        cur.execute("UPDATE site_config SET site_name=%s WHERE id=1", (name,))
        db.commit()
        flash("站点名称修改完成")
    cur.execute("SELECT site_name FROM site_config WHERE id=1")
    site = cur.fetchone()
    cur.close()
    return render_template("admin/site_setting.html", site=site)


# 添加栏目
@admin_bp.route('/category_add', methods=["POST"])
@admin_required
def add_category():
    name = request.form.get("cat_name", "").strip()
    tag = request.form.get("tag_text", "").strip()
    if not name or len(name) > CAT_NAME_MAX_LEN:
        flash(f"栏目名称不能为空且不超过 {CAT_NAME_MAX_LEN} 字符")
        return redirect(url_for("blog.index"))
    if len(tag) > CAT_NAME_MAX_LEN:
        flash(f"标签不超过 {CAT_NAME_MAX_LEN} 字符")
        return redirect(url_for("blog.index"))

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            "INSERT INTO category(cat_name,tag_text,create_time) VALUES(%s,%s,%s)",
            (name, tag, now)
        )
        db.commit()
        flash("栏目新增成功")
    except IntegrityError:
        flash("栏目名称重复")
    finally:
        cur.close()
    return redirect(url_for("blog.index"))


# 文章图片上传（供 EasyMDE 编辑器调用）
@admin_bp.route('/upload', methods=["POST"])
@admin_required
def upload_image():
    """接收编辑器上传的图片，自动压缩/缩放后返回 JSON {url} 或 {error}"""
    img = request.files.get("image")
    if not img or not img.filename:
        return jsonify({"error": "请选择图片"}), 400

    # 扩展名校验
    if "." not in img.filename or img.filename.rsplit(".", 1)[1].lower() not in UPLOAD_ALLOWED_EXT:
        return jsonify({"error": "仅支持 jpg/jpeg/png/gif"}), 400
    # MIME 校验
    if (img.mimetype or "").lower() not in UPLOAD_ALLOWED_MIME:
        return jsonify({"error": "文件类型不合法"}), 400
    # 大小校验
    img.seek(0, os.SEEK_END)
    size = img.tell()
    img.seek(0)
    if size > UPLOAD_MAX_SIZE:
        return jsonify({"error": "文件大小不能超过 10MB"}), 400
    if size == 0:
        return jsonify({"error": "文件为空"}), 400

    # 生成安全文件名
    base = secure_filename(img.filename)
    ext = img.filename.rsplit(".", 1)[1].lower()
    if base:
        base = os.path.splitext(base)[0]
    if not base:
        base = uuid.uuid4().hex
    if len(base) > UPLOAD_BASE_NAME_LEN:
        base = base[:UPLOAD_BASE_NAME_LEN]
    final_name = f"{uuid.uuid4().hex}_{base}.{ext}"

    # 保存到项目根目录的 static/uploads/
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    upload_dir = os.path.join(root, "static", "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    save_path = os.path.join(upload_dir, final_name)

    # 使用 Pillow 处理图片：自动缩放 + 压缩
    try:
        image = Image.open(img.stream)

        # 如果图片宽度超过限制，等比缩放
        if image.width > UPLOAD_MAX_WIDTH:
            ratio = UPLOAD_MAX_WIDTH / image.width
            new_height = int(image.height * ratio)
            image = image.resize((UPLOAD_MAX_WIDTH, new_height), Image.LANCZOS)
            log.info(f"图片已缩放：{image.width}x{image.height}")

        # 根据格式保存
        if ext in ('jpg', 'jpeg'):
            # JPEG 格式：转换为 RGB（去除透明通道）+ 压缩质量
            if image.mode in ('RGBA', 'P'):
                image = image.convert('RGB')
            image.save(save_path, 'JPEG', quality=85, optimize=True)
        elif ext == 'png':
            # PNG 格式：保留透明通道，压缩
            image.save(save_path, 'PNG', optimize=True)
        elif ext == 'gif':
            # GIF 格式：直接保存（不压缩动画）
            image.save(save_path, 'GIF')
        else:
            image.save(save_path)

    except Exception as e:
        log.error(f"图片处理失败: {str(e)}")
        return jsonify({"error": "图片处理失败，请重试"}), 500

    return jsonify({"url": f"/static/uploads/{final_name}"}), 200
