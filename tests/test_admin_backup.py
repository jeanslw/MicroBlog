"""数据库备份/恢复子进程调用测试。

回归重点：mysql/mysqldump 客户端的「禁用 TLS」写法不统一——MariaDB 客户端
（镜像内 default-mysql-client）与 MySQL ≤8.0 用 ``--skip-ssl``，MySQL 8.4 客户端
已移除该写法（仅认 ``--ssl-mode=DISABLED``）。硬编码 ``--skip-ssl`` 会让 MySQL 8.4
客户端以 exit 2（unknown option）直接失败。

更关键的是**探测不可信**：``mysql --skip-ssl --version`` 会打印版本并以 0 退出
（mysql 客户端对 ``--version`` 提前返回、不再校验其余选项），于是 ``--skip-ssl``
被误判为可用，直到真正恢复时才以 exit 2 失败；而 ``mysqldump --skip-ssl --version``
却会正常报错。因此改为行为驱动：先用首选参数真跑一次，客户端报「未知选项」就换
下一个候选重试（未知选项在参数解析阶段即失败，不连库、不写库），跑通后缓存结论；
密码错误/权限不足等非参数类错误直接透出 stderr，不做重试。
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
    """跑通的参数有缓存，用例间必须清空避免串味"""
    admin_routes._tls_args_cache.clear()
    yield
    admin_routes._tls_args_cache.clear()


def _db_client(tls_args):
    """把候选参数拼成一条类似备份/恢复的命令行"""
    return ["mysqldump", *tls_args]


def test_cmd_builders_place_tls_args_and_avoid_password_on_argv():
    """命令拼装：TLS 参数夹在中间、口令不进命令行（走 MYSQL_PWD 环境变量）"""
    creds = {"host": "db", "user": "blog", "pwd": "s3cret", "db": "flask_blog"}
    dump_cmd = admin_routes._mysqldump_cmd(creds, ("--ssl-mode=DISABLED",))
    assert dump_cmd[0] == "mysqldump"
    assert "--ssl-mode=DISABLED" in dump_cmd
    assert "--single-transaction" in dump_cmd and "--no-tablespaces" in dump_cmd
    assert dump_cmd[-5:] == ["-h", "db", "-u", "blog", "flask_blog"]
    assert "s3cret" not in dump_cmd  # 口令不得出现在进程列表里
    restore_cmd = admin_routes._mysql_restore_cmd(creds, ())
    assert restore_cmd[0] == "mysql"
    assert "--connect-timeout=10" in restore_cmd
    assert "--skip-ssl" not in restore_cmd
    assert restore_cmd[-5:] == ["-h", "db", "-u", "blog", "flask_blog"]


def test_prefers_skip_ssl_when_client_accepts_it(monkeypatch):
    """MariaDB / MySQL ≤8.0 客户端：首选 --skip-ssl，一次跑通、不再试错"""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _Completed(returncode=0)

    monkeypatch.setattr(admin_routes.subprocess, "run", fake_run)
    admin_routes._run_db_client(_db_client, "mysqldump", {})
    assert calls == [["mysqldump", "--skip-ssl"]]
    assert admin_routes._tls_args_cache["mysqldump"] == ("--skip-ssl",)


def test_mysql84_client_falls_back_to_ssl_mode(monkeypatch):
    """MySQL 8.4 客户端拒绝 --skip-ssl（unknown option）时自动改用 --ssl-mode=DISABLED"""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "--skip-ssl" in cmd:
            return _Completed(returncode=2, stderr=b"mysql: [ERROR] unknown option '--skip-ssl'.")
        return _Completed(returncode=0)

    monkeypatch.setattr(admin_routes.subprocess, "run", fake_run)
    admin_routes._run_db_client(_db_client, "mysqldump", {})
    assert calls == [
        ["mysqldump", "--skip-ssl"],
        ["mysqldump", "--ssl-mode=DISABLED"],
    ]
    assert admin_routes._tls_args_cache["mysqldump"] == ("--ssl-mode=DISABLED",)


def test_no_version_probe_is_used(monkeypatch):
    """不再用 `--version` 探测（mysql 客户端会忽略未知选项并以 0 退出，结论不可信）"""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _Completed(returncode=0)

    monkeypatch.setattr(admin_routes.subprocess, "run", fake_run)
    admin_routes._run_db_client(_db_client, "mysqldump", {})
    assert all("--version" not in cmd for cmd in calls)


def test_verified_flag_is_reused_without_retry(monkeypatch):
    """跑通的写法写入缓存：后续调用直接使用，不再多跑一次注定失败的命令"""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _Completed(
            returncode=2 if "--skip-ssl" in cmd else 0,
            stderr=b"mysql: [ERROR] unknown option '--skip-ssl'.",
        )

    monkeypatch.setattr(admin_routes.subprocess, "run", fake_run)
    for _ in range(2):
        admin_routes._run_db_client(_db_client, "mysql", {})
    assert calls == [
        ["mysqldump", "--skip-ssl"],
        ["mysqldump", "--ssl-mode=DISABLED"],
        ["mysqldump", "--ssl-mode=DISABLED"],
    ]


def test_all_tls_flags_rejected_falls_back_to_client_default(monkeypatch):
    """两种写法都不被支持时去掉该参数，交回客户端默认行为（8.4 默认 ssl-mode=PREFERRED）"""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "--skip-ssl" in cmd:
            return _Completed(returncode=2, stderr=b"mysql: [ERROR] unknown option '--skip-ssl'.")
        if "--ssl-mode=DISABLED" in cmd:
            return _Completed(returncode=2, stderr=b"mysql: unknown variable 'ssl-mode=DISABLED'")
        return _Completed(returncode=0)

    monkeypatch.setattr(admin_routes.subprocess, "run", fake_run)
    admin_routes._run_db_client(_db_client, "mysql", {})
    assert calls[-1] == ["mysqldump"]
    assert admin_routes._tls_args_cache["mysql"] == ()


def test_retry_keeps_dump_payload_for_restore(monkeypatch):
    """恢复时首个候选失败会重试：dump 数据必须同样喂给重试的那次调用"""
    payloads = []
    dump = b"CREATE TABLE t (id INT);\n"

    def fake_run(cmd, **kwargs):
        payloads.append(kwargs.get("input"))
        return _Completed(
            returncode=2 if "--skip-ssl" in cmd else 0,
            stderr=b"mysql: [ERROR] unknown option '--skip-ssl'.",
        )

    monkeypatch.setattr(admin_routes.subprocess, "run", fake_run)
    admin_routes._run_db_client(_db_client, "mysql", {}, input=dump, timeout=120)
    assert payloads == [dump, dump]


def test_non_tls_failure_is_not_retried(monkeypatch):
    """密码错误/权限不足等非参数类错误不重试，stderr 原样透出"""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _Completed(returncode=1, stderr=b"mysqldump: Got error: 1045: Access denied for user")

    monkeypatch.setattr(admin_routes.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="Access denied"):
        admin_routes._run_db_client(_db_client, "mysqldump", {})
    assert len(calls) == 1


def test_run_db_client_reports_missing_binary(monkeypatch):
    """客户端缺失给出可读提示"""

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(admin_routes.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="未找到 mysqldump 客户端"):
        admin_routes._run_db_client(_db_client, "mysqldump", {})


def test_run_db_client_falls_back_to_exit_code(monkeypatch):
    """客户端异常退出但没输出 stderr 时，至少报出退出码"""

    def fake_run(cmd, **kwargs):
        return _Completed(returncode=7, stderr=b"")

    monkeypatch.setattr(admin_routes.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="exited with code 7"):
        admin_routes._run_db_client(_db_client, "mysqldump", {})


def test_create_backup_falls_back_on_mysql84_and_writes_zip(app, monkeypatch, tmp_path):
    """MySQL 8.4 客户端：备份自动从 --skip-ssl 回退，dump 内容写入 zip"""
    monkeypatch.setenv("BLOG_DB_TYPE", "mysql")
    # 显式给定凭据：避免断言受开发者本机 BLOG_MYSQL_PWD 影响
    monkeypatch.setenv("BLOG_MYSQL_PWD", "s3cret-tls-probe")
    calls = []
    envs = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        envs.append(kwargs.get("env") or {})
        if "--skip-ssl" in cmd:
            return _Completed(returncode=2, stderr=b"mysqldump: [ERROR] unknown option '--skip-ssl'.")
        return _Completed(returncode=0, stdout=b"CREATE TABLE t (id INT);\n")

    monkeypatch.setattr(admin_routes.subprocess, "run", fake_run)
    name = admin_routes._create_backup(str(tmp_path))
    assert name.startswith("mysql_backup_") and name.endswith(".zip")
    assert calls[-1][0] == "mysqldump"
    assert "--ssl-mode=DISABLED" in calls[-1]
    assert "--skip-ssl" not in calls[-1]
    assert "--single-transaction" in calls[-1] and "--no-tablespaces" in calls[-1]
    # 口令走 MYSQL_PWD 环境变量而非命令行，避免出现在进程列表里
    assert envs[-1]["MYSQL_PWD"] == "s3cret-tls-probe"
    with zipfile.ZipFile(tmp_path / name) as zf:
        assert zf.read(zf.namelist()[0]) == b"CREATE TABLE t (id INT);\n"


def test_create_backup_reports_client_stderr(app, monkeypatch, tmp_path):
    """客户端报错时把 stderr 透给用户（回归：曾经只剩 exit status 2）"""
    monkeypatch.setenv("BLOG_DB_TYPE", "mysql")

    def fake_run(cmd, **kwargs):
        return _Completed(returncode=1, stderr=b"mysqldump: Got error: 2002: Can't connect to local server")

    monkeypatch.setattr(admin_routes.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="Can't connect to local server"):
        admin_routes._create_backup(str(tmp_path))

