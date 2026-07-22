from flask import render_template, request, redirect, url_for, flash, session
import os
from werkzeug.utils import secure_filename
from datetime import datetime
from app.banner import banner_bp
from app.db import get_db, DictCursor
from app.extensions import admin_required


ALLOWED_EXT = {"jpg", "jpeg", "png", "gif"}
UPLOAD_DIR = "static/banner"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def check_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def fix_link(url):
    url = url.strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        return "https://" + url
    return url


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
    link = fix_link(request.form.get("link_url", ""))
    title = request.form.get("title", "").strip()
    desc = request.form.get("desc_text", "").strip()
    sort = int(request.form.get("sort_num", 0))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not img or not img.filename:
        flash("请选择轮播图片")
        return redirect(url_for("banner.banner_list"))

    if not check_file(img.filename):
        flash("不支持的文件类型，仅允许 jpg/png/gif")
        return redirect(url_for("banner.banner_list"))

    # 检查文件大小
    img.seek(0, os.SEEK_END)
    file_size = img.tell()
    img.seek(0)
    if file_size > MAX_FILE_SIZE:
        flash("文件大小不能超过 10MB")
        return redirect(url_for("banner.banner_list"))

    if not os.path.exists(UPLOAD_DIR):
        os.makedirs(UPLOAD_DIR)

    fn = secure_filename(img.filename)
    save_path = os.path.join(UPLOAD_DIR, fn)
    img.save(save_path)
    img_path = f"static/banner/{fn}"

    db = get_db()
    cur = db.cursor()
    cur.execute(
        "INSERT INTO banner(img_path,link_url,title,desc_text,sort,create_time) VALUES(%s,%s,%s,%s,%s,%s)",
        (img_path, link, title, desc, sort, now)
    )
    db.commit()
    cur.close()
    flash("新增轮播成功")
    return redirect(url_for("banner.banner_list"))


@banner_bp.route("/banner/edit/<int:bid>", methods=["POST"])
@admin_required
def banner_edit(bid):
    link = fix_link(request.form.get("link_url", ""))
    title = request.form.get("title", "").strip()
    desc = request.form.get("desc_text", "").strip()
    sort = int(request.form.get("sort_num", 0))
    img = request.files.get("banner_img")

    db = get_db()
    cur = db.cursor()
    sql = "UPDATE banner SET link_url=%s,title=%s,desc_text=%s,sort=%s WHERE id=%s"
    params = [link, title, desc, sort, bid]

    if img and img.filename and check_file(img.filename):
        img.seek(0, os.SEEK_END)
        file_size = img.tell()
        img.seek(0)
        if file_size > MAX_FILE_SIZE:
            flash("文件大小不能超过 10MB")
            return redirect(url_for("banner.banner_list"))

        if not os.path.exists(UPLOAD_DIR):
            os.makedirs(UPLOAD_DIR)
        fn = secure_filename(img.filename)
        save_path = os.path.join(UPLOAD_DIR, fn)
        img.save(save_path)
        img_path = f"static/banner/{fn}"
        sql = "UPDATE banner SET img_path=%s,link_url=%s,title=%s,desc_text=%s,sort=%s WHERE id=%s"
        params = [img_path, link, title, desc, sort, bid]

    cur.execute(sql, params)
    db.commit()
    cur.close()
    flash("修改完成")
    return redirect(url_for("banner.banner_list"))


@banner_bp.route("/banner/del/<int:bid>")
@admin_required
def banner_del(bid):
    db = get_db()
    cur = db.cursor(DictCursor)
    cur.execute("SELECT img_path FROM banner WHERE id=%s", (bid,))
    row = cur.fetchone()
    try:
        if row and row["img_path"] and os.path.exists(row["img_path"]):
            os.remove(row["img_path"])
    except Exception:
        pass
    cur.execute("DELETE FROM banner WHERE id=%s", (bid,))
    db.commit()
    cur.close()
    flash("已删除")
    return redirect(url_for("banner.banner_list"))
