from flask import render_template, request, redirect, url_for, flash, session
import os
from werkzeug.utils import secure_filename
from datetime import datetime
from app.banner import banner_bp
from app.db import get_db, DictCursor


ALLOWED_EXT = {"jpg", "jpeg", "png", "gif"}
UPLOAD_DIR = "static/banner"


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
def banner_list():
    if not session.get("is_admin"):
        flash("请登录管理员账号")
        return redirect(url_for("admin.login"))
    db = get_db()
    if not db:
        flash("数据库连接失败，请检查数据库服务")
        return render_template("banner/banner_manage.html", banner_list=[])
    cur = db.cursor(DictCursor)
    cur.execute("SELECT * FROM banner ORDER BY sort DESC")
    data = cur.fetchall()
    cur.close()
    db.close()
    return render_template("banner/banner_manage.html", banner_list=data)


@banner_bp.route("/banner/add", methods=["POST"])
def banner_add():
    if not session.get("is_admin"):
        flash("请登录管理员账号")
        return redirect(url_for("admin.login"))
    img = request.files["banner_img"]
    link = fix_link(request.form["link_url"])
    title = request.form["title"].strip()
    desc = request.form["desc_text"].strip()
    sort = int(request.form["sort_num"])
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not os.path.exists(UPLOAD_DIR):
        os.makedirs(UPLOAD_DIR)
    img_path = ""
    if img and check_file(img.filename):
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
    db.close()
    flash("新增轮播成功")
    return redirect(url_for("banner.banner_list"))


@banner_bp.route("/banner/edit/<int:bid>", methods=["POST"])
def banner_edit(bid):
    if not session.get("is_admin"):
        flash("请登录管理员账号")
        return redirect(url_for("admin.login"))
    link = fix_link(request.form["link_url"])
    title = request.form["title"].strip()
    desc = request.form["desc_text"].strip()
    sort = int(request.form["sort_num"])
    img = request.files.get("banner_img")

    db = get_db()
    if not db:
        flash("数据库连接失败，请检查数据库服务")
        return redirect(url_for("banner.banner_list"))
    cur = db.cursor()
    sql = "UPDATE banner SET link_url=%s,title=%s,desc_text=%s,sort=%s WHERE id=%s"
    params = [link, title, desc, sort, bid]

    if img and check_file(img.filename):
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
    db.close()
    flash("修改完成")
    return redirect(url_for("banner.banner_list"))


@banner_bp.route("/banner/del/<int:bid>")
def banner_del(bid):
    if not session.get("is_admin"):
        flash("请登录管理员账号")
        return redirect(url_for("admin.login"))
    db = get_db()
    cur = db.cursor(DictCursor)
    cur.execute("SELECT img_path FROM banner WHERE id=%s", (bid,))
    row = cur.fetchone()
    try:
        if row and os.path.exists(row["img_path"]):
            os.remove(row["img_path"])
    except Exception:
        pass
    cur.execute("DELETE FROM banner WHERE id=%s", (bid,))
    db.commit()
    cur.close()
    db.close()
    flash("已删除")
    return redirect(url_for("banner.banner_list"))
