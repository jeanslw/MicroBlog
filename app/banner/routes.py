import logging
import os
import uuid
from datetime import datetime

from flask import render_template, request, redirect, url_for, flash
from PIL import Image
from werkzeug.utils import secure_filename

from app.banner import banner_bp
from app.db import get_db, DictCursor
from app.extensions import admin_required

log = logging.getLogger(__name__)

# 上传相关
ALLOWED_EXT = {"jpg", "jpeg", "png", "gif"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
# 允许的 MIME 前缀（与扩展名配合校验）
ALLOWED_MIME = {"image/jpeg", "image/png", "image/gif"}
# 文件名 base 部分最大长度（不含扩展名），防止最终路径超 VARCHAR(500)
MAX_BASE_NAME_LEN = 100
# Banner 图片最大宽度（像素）
BANNER_MAX_WIDTH = 1920

# 字段长度（与数据库 VARCHAR 对齐）
TITLE_MAX_LEN = 100
DESC_MAX_LEN = 200
LINK_MAX_LEN = 500


def _upload_dir():
    """返回上传目录的绝对路径（避免相对路径在不同 cwd 下失效）"""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "static", "banner")


def _check_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def _check_mime(mimetype):
    return (mimetype or "").lower() in ALLOWED_MIME


def _fix_link(url):
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        return "https://" + url
    return url[:LINK_MAX_LEN]


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _save_upload(img):
    """
    校验并保存上传图片，自动压缩/缩放后返回 (relative_url_path, err_msg)。
    relative_url_path 形如 '/static/banner/xxxx.jpg'，可直接用于模板/前端访问。
    """
    if not img or not img.filename:
        return None, "请选择轮播图片"
    if not _check_file(img.filename):
        return None, "不支持的文件类型，仅允许 jpg/png/gif"
    if not _check_mime(img.mimetype):
        return None, "文件类型不合法（仅允许图片）"

    img.seek(0, os.SEEK_END)
    file_size = img.tell()
    img.seek(0)
    if file_size > MAX_FILE_SIZE:
        return None, "文件大小不能超过 10MB"
    if file_size == 0:
        return None, "文件为空"

    # secure_filename 处理中文/特殊字符可能返回空字符串，用 uuid 兜底
    base = secure_filename(img.filename)
    ext = img.filename.rsplit(".", 1)[1].lower()
    # secure_filename 保留扩展名，去掉避免双扩展名（xxx.png.png）
    if base:
        base = os.path.splitext(base)[0]
    if not base:
        base = uuid.uuid4().hex
    # 截断 base 防止 final_name 过长（uuid_32 + _ + base + . + ext ≤ 138）
    if len(base) > MAX_BASE_NAME_LEN:
        base = base[:MAX_BASE_NAME_LEN]
    # 加 uuid 前缀防同名覆盖
    final_name = f"{uuid.uuid4().hex}_{base}.{ext}"
    upload_dir = _upload_dir()
    os.makedirs(upload_dir, exist_ok=True)
    save_path = os.path.join(upload_dir, final_name)

    # 使用 Pillow 处理图片：自动缩放 + 压缩
    try:
        image = Image.open(img.stream)

        # 如果图片宽度超过限制，等比缩放
        if image.width > BANNER_MAX_WIDTH:
            ratio = BANNER_MAX_WIDTH / image.width
            new_height = int(image.height * ratio)
            image = image.resize((BANNER_MAX_WIDTH, new_height), Image.LANCZOS)
            log.info(f"Banner图片已缩放：{image.width}x{image.height}")

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
        log.error(f"Banner图片处理失败: {str(e)}")
        return None, "图片处理失败，请重试"

    # 返回带前导 / 的相对 URL，避免在 /banner 子路径下被浏览器解析成相对路径
    return f"/static/banner/{final_name}", None


@banner_bp.route("/banner")
@admin_required
def banner_list():
    db = get_db()
    cur = db.cursor(DictCursor)
    cur.execute("SELECT * FROM banner ORDER BY sort DESC")
    data = cur.fetchall()
    cur.close()
    return render_template("banner/banner_manage.html", banner_list=data)


@banner_bp.route("/banner/add", methods=["POST"])
@admin_required
def banner_add():
    img = request.files.get("banner_img")
    img_path, err = _save_upload(img)
    if err:
        flash(err)
        return redirect(url_for("banner.banner_list"))

    link = _fix_link(request.form.get("link_url", ""))
    title = request.form.get("title", "").strip()[:TITLE_MAX_LEN]
    desc = request.form.get("desc_text", "").strip()[:DESC_MAX_LEN]
    sort = _safe_int(request.form.get("sort_num", 0), 0)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            "INSERT INTO banner(img_path,link_url,title,desc_text,sort,create_time) "
            "VALUES(%s,%s,%s,%s,%s,%s)",
            (img_path, link, title, desc, sort, now)
        )
        db.commit()
        flash("新增轮播成功")
    finally:
        cur.close()
    return redirect(url_for("banner.banner_list"))


@banner_bp.route("/banner/edit/<int:bid>", methods=["POST"])
@admin_required
def banner_edit(bid):
    link = _fix_link(request.form.get("link_url", ""))
    title = request.form.get("title", "").strip()[:TITLE_MAX_LEN]
    desc = request.form.get("desc_text", "").strip()[:DESC_MAX_LEN]
    sort = _safe_int(request.form.get("sort_num", 0), 0)
    img = request.files.get("banner_img")

    db = get_db()
    cur = db.cursor()
    try:
        if img and img.filename:
            img_path, err = _save_upload(img)
            if err:
                flash(err)
                return redirect(url_for("banner.banner_list"))
            cur.execute(
                "UPDATE banner SET img_path=%s,link_url=%s,title=%s,desc_text=%s,sort=%s "
                "WHERE id=%s",
                (img_path, link, title, desc, sort, bid)
            )
        else:
            cur.execute(
                "UPDATE banner SET link_url=%s,title=%s,desc_text=%s,sort=%s WHERE id=%s",
                (link, title, desc, sort, bid)
            )
        db.commit()
        flash("修改完成")
    finally:
        cur.close()
    return redirect(url_for("banner.banner_list"))


# 删除改为 POST，避免 GET 被 CSRF 利用
@banner_bp.route("/banner/del/<int:bid>", methods=["POST"])
@admin_required
def banner_del(bid):
    db = get_db()
    cur = db.cursor(DictCursor)
    cur.execute("SELECT img_path FROM banner WHERE id=%s", (bid,))
    row = cur.fetchone()
    try:
        if row and row["img_path"]:
            # img_path 形如 /static/banner/xxx.jpg，转成绝对路径删除
            root = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            abs_path = os.path.join(root, row["img_path"].lstrip("/"))
            if os.path.exists(abs_path):
                os.remove(abs_path)
    except Exception:
        log.warning("删除 banner 物理文件失败 bid=%s", bid, exc_info=True)
    cur.execute("DELETE FROM banner WHERE id=%s", (bid,))
    db.commit()
    cur.close()
    flash("已删除")
    return redirect(url_for("banner.banner_list"))
