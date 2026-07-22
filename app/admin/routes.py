from flask import render_template, request, redirect, url_for, flash, session
import time
from datetime import datetime
from werkzeug.security import check_password_hash, generate_password_hash
from app.admin import admin_bp
from app.db import get_db, DictCursor, IntegrityError
from app.extensions import get_site_name, get_categories, admin_required

# 登录防爆破
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 300  # 5 分钟锁定


def _is_login_locked():
    """检查是否被锁定"""
    attempts = session.get("_login_attempts", 0)
    lock_until = session.get("_login_lock_until", 0)
    if attempts >= MAX_LOGIN_ATTEMPTS and time.time() < lock_until:
        return True, int(lock_until - time.time())
    # 锁定期过了，重置
    if attempts >= MAX_LOGIN_ATTEMPTS and time.time() >= lock_until:
        session.pop("_login_attempts", None)
        session.pop("_login_lock_until", None)
    return False, 0


# 管理员登录
@admin_bp.route('/login', methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # 防爆破检查
        locked, remain = _is_login_locked()
        if locked:
            flash(f"登录失败次数过多，请 {remain} 秒后再试")
            return render_template("admin/login.html")

        user = request.form["username"].strip()
        pwd = request.form["password"].strip()
        db = get_db()
        cur = db.cursor(DictCursor)
        cur.execute("SELECT * FROM admin WHERE username=%s", (user,))
        admin_info = cur.fetchone()
        cur.close()
        if admin_info and check_password_hash(admin_info["password"], pwd):
            session["is_admin"] = True
            session.pop("_login_attempts", None)
            session.pop("_login_lock_until", None)
            flash("登录成功")
            return redirect(url_for("blog.index"))
        # 记录失败次数
        attempts = session.get("_login_attempts", 0) + 1
        session["_login_attempts"] = attempts
        if attempts >= MAX_LOGIN_ATTEMPTS:
            session["_login_lock_until"] = int(time.time() + LOGIN_LOCKOUT_SECONDS)
            flash(f"登录失败次数过多，请 {LOGIN_LOCKOUT_SECONDS // 60} 分钟后再试")
        else:
            flash(f"账号或密码错误（剩余尝试 {MAX_LOGIN_ATTEMPTS - attempts} 次）")
    return render_template("admin/login.html")


# 退出登录
@admin_bp.route('/logout')
def logout():
    session.clear()
    flash("已退出登录")
    return redirect(url_for("blog.index"))


# 修改密码
@admin_bp.route('/change_pwd', methods=["GET", "POST"])
@admin_required
def change_pwd():
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
    return render_template("admin/change_pwd.html")


# 站点设置
@admin_bp.route('/site_setting', methods=["GET", "POST"])
@admin_required
def site_setting():
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
    return render_template("admin/site_setting.html", site=site)


# 添加栏目
@admin_bp.route('/category_add', methods=["POST"])
@admin_required
def add_category():
    name = request.form["cat_name"].strip()
    tag = request.form.get("tag_text", "").strip()
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
    return redirect(url_for("blog.index"))
