from flask import render_template, request, redirect, url_for, flash, session
from datetime import datetime
from werkzeug.security import check_password_hash, generate_password_hash
from app.admin import admin_bp
from app.db import get_db, DictCursor, IntegrityError
from app.extensions import get_site_name, get_categories


# 管理员登录
@admin_bp.route('/login', methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form["username"].strip()
        pwd = request.form["password"].strip()
        db = get_db()
        cur = db.cursor(DictCursor)
        cur.execute("SELECT * FROM admin WHERE username=%s", (user,))
        admin_info = cur.fetchone()
        cur.close()
        db.close()
        if admin_info and check_password_hash(admin_info["password"], pwd):
            session["is_admin"] = True
            flash("登录成功")
            return redirect(url_for("blog.index"))
        flash("账号或密码错误")
    return render_template("admin/login.html")


# 退出登录
@admin_bp.route('/logout')
def logout():
    session.clear()
    flash("已退出登录")
    return redirect(url_for("blog.index"))


# 修改密码
@admin_bp.route('/change_pwd', methods=["GET", "POST"])
def change_pwd():
    if not session.get("is_admin"):
        flash("请登录管理员账号")
        return redirect(url_for("admin.login"))
    if request.method == "POST":
        old_pwd = request.form["old_pwd"].strip()
        new_pwd = request.form["new_pwd"].strip()
        confirm = request.form["confirm_pwd"].strip()
        if new_pwd != confirm:
            flash("两次新密码不一致")
            return render_template("admin/change_pwd.html")
        db = get_db()
        cur = db.cursor(DictCursor)
        cur.execute("SELECT password FROM admin WHERE id=1")
        row = cur.fetchone()
        if not row or not check_password_hash(row["password"], old_pwd):
            flash("原密码错误")
        else:
            new_hashed = generate_password_hash(new_pwd)
            cur.execute("UPDATE admin SET password=%s WHERE id=1", (new_hashed,))
            db.commit()
            flash("密码修改成功，请重新登录")
            session.clear()
            return redirect(url_for("admin.login"))
        cur.close()
        db.close()
    return render_template("admin/change_pwd.html")


# 站点设置
@admin_bp.route('/site_setting', methods=["GET", "POST"])
def site_setting():
    if not session.get("is_admin"):
        flash("请登录管理员账号")
        return redirect(url_for("admin.login"))
    db = get_db()
    cur = db.cursor(DictCursor)
    if request.method == "POST":
        name = request.form["site_name"].strip()
        cur.execute("UPDATE site_config SET site_name=%s WHERE id=1", (name,))
        db.commit()
        flash("站点名称修改完成")
    cur.execute("SELECT site_name FROM site_config WHERE id=1")
    site = cur.fetchone()
    cur.close()
    db.close()
    return render_template("admin/site_setting.html", site=site)


# 添加栏目
@admin_bp.route('/category_add', methods=["POST"])
def add_category():
    if not session.get("is_admin"):
        flash("请登录管理员账号")
        return redirect(url_for("admin.login"))
    name = request.form["cat_name"].strip()
    tag = request.form["tag_text"].strip()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("INSERT INTO category(cat_name,tag_text,create_time) VALUES(%s,%s,%s)", (name, tag, now))
        db.commit()
        flash("栏目新增成功")
    except IntegrityError:
        flash("栏目名称重复")
    cur.close()
    db.close()
    return redirect(url_for("blog.index"))
