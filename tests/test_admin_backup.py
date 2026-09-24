"""数据库备份/恢复子进程调用测试。

回归重点：mysql/mysqldump 客户端的「禁用 TLS」参数名不统一——
MariaDB 客户端（镜像内 default-mysql-client）与 MySQL ≤8.0 用 ``--skip-ssl``，
MySQL 8.4 客户端已移除该选项（仅认 ``--ssl-mode=DISABLED``）。硬编码 ``--skip-ssl``
会让 MySQL 8.4 客户端以 exit 2（unknown option）直接失败，且 check=True 只抛出
「returned non-zero exit status 2」，丢掉客户端 stderr 无从定位。
"""

import zipfile

import pytest

from app.admin import routes as admin_routes


class _Completed:
    """subprocess.CompletedProcess 的最小替身"""

    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture(autouse=True)
def _clear_tls_cache():
    """探测结果有缓存，用例间必须清空避免串味"""
    admin_routes._mysql_client_tls_args_cache.clear()
    yield
    admin_routes._mysql_client_tls_args_cache.clear()


def test_tls_args_prefers_skip_ssl_when_supported(monkeypatch):
    """MariaDB / MySQL ≤8.0 客户端支持 --skip-ssl"""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _Completed(returncode=0)

    monkeypatch.setattr(admin_routes.subprocess, "run", fake_run)
    assert admin_routes._mysql_client_tls_args("mysqldump") == ["--skip-ssl"]
    # --version 只做参数解析与打印版本，不建立数据库连接
    assert calls == [["mysqldump", "--skip-ssl", "--version"]]


def test_tls_args_falls_back_to_ssl_mode_on_mysql84(monkeypatch):
    """MySQL 8.4 客户端：--skip-ssl 报 unknown option，回退 --ssl-mode=DISABLED"""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1] == "--skip-ssl":
            return _Completed(returncode=2, stderr=b"mysqldump: [ERROR] unknown option '--skip-ssl'.")
        return _Completed(returncode=0)

    monkeypatch.setattr(admin_routes.subprocess, "run", fake_run)
    assert admin_routes._mysql_client_tls_args("mysqldump") == ["--ssl-mode=DISABLED"]
    assert [c[1] for c in calls] == ["--skip-ssl", "--ssl-mode=DISABLED"]


def test_tls_args_empty_when_both_unsupported(monkeypatch):
    """两种写法都不支持时返回空，交回客户端默认行为"""
    monkeypatch.setattr(admin_routes.subprocess, "run", lambda cmd, **kw: _Completed(returncode=2))
    assert admin_routes._mysql_client_tls_args("mysql") == []


def test_tls_args_probe_is_cached(monkeypatch):
    """同一二进制只探测一次"""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _Completed(returncode=0)

    monkeypatch.setattr(admin_routes.subprocess, "run", fake_run)
    admin_routes._mysql_client_tls_args("mysqldump")
    admin_routes._mysql_client_tls_args("mysqldump")
    assert len(calls) == 1


def test_tls_args_survives_missing_binary(monkeypatch):
    """二进制不存在（OSError）时不在此处抛异常，由实际调用报错"""

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(admin_routes.subprocess, "run", fake_run)
    assert admin_routes._mysql_client_tls_args("mysqldump") == []


def test_run_db_client_surfaces_stderr(monkeypatch):
    """失败时报错必须带客户端 stderr，而不是只有退出码"""

    def fake_run(cmd, **kwargs):
        return _Completed(returncode=2, stderr=b"mysqldump: [ERROR] unknown option '--skip-ssl'.\n")

    monkeypatch.setattr(admin_routes.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="unknown option '--skip-ssl'"):
        admin_routes._run_db_client(["mysqldump"], "mysqldump", {})


def test_run_db_client_reports_missing_binary(monkeypatch):
    """客户端缺失给出可读提示"""

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(admin_routes.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="未找到 mysqldump 客户端"):
        admin_routes._run_db_client(["mysqldump"], "mysqldump", {})


def test_create_backup_uses_detected_tls_flag(app, monkeypatch, tmp_path):
    """MySQL 备份用探测到的禁用 TLS 参数（8.4 客户端不再收到 --skip-ssl），并把 dump 写进 zip"""
    monkeypatch.setenv("BLOG_DB_TYPE", "mysql")
    # 显式给定凭据：避免断言受开发者本机 BLOG_MYSQL_PWD 影响
    monkeypatch.setenv("BLOG_MYSQL_PWD", "s3cret-tls-probe")
    captured = {}

    def fake_run(cmd, **kwargs):
        if "--version" in cmd:
            return _Completed(returncode=2 if "--skip-ssl" in cmd else 0)
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env") or {}
        return _Completed(returncode=0, stdout=b"CREATE TABLE t (id INT);\n")

    monkeypatch.setattr(admin_routes.subprocess, "run", fake_run)
    name = admin_routes._create_backup(str(tmp_path))
    assert "--ssl-mode=DISABLED" in captured["cmd"]
    assert "--skip-ssl" not in captured["cmd"]
    # 口令走 MYSQL_PWD 环境变量而非命令行，避免出现在进程列表里
    assert captured["env"]["MYSQL_PWD"] == "s3cret-tls-probe"
    with zipfile.ZipFile(tmp_path / name) as zf:
        assert zf.read(zf.namelist()[0]) == b"CREATE TABLE t (id INT);\n"


def test_create_backup_reports_client_stderr(app, monkeypatch, tmp_path):
    """客户端报错时把 stderr 透给用户（回归：曾经只剩 exit status 2）"""
    monkeypatch.setenv("BLOG_DB_TYPE", "mysql")

    def fake_run(cmd, **kwargs):
        if "--version" in cmd:
            return _Completed(returncode=2)
        return _Completed(returncode=2, stderr=b"mysqldump: [ERROR] unknown option '--skip-ssl'.")

    monkeypatch.setattr(admin_routes.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="unknown option '--skip-ssl'"):
        admin_routes._create_backup(str(tmp_path))
