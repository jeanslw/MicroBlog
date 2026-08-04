import logging
from datetime import datetime

from flask import render_template, request, redirect, url_for, flash, session
from werkzeug.security import check_password_hash, generate_password_hash

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
