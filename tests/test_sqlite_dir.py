"""SQLite 库目录准备逻辑测试（config._prepare_sqlite_dir / _resolve_db_uri_for_class）。

重点覆盖 Serverless（Vercel / AWS Lambda）只读文件系统场景：函数的代码目录只读
（Vercel 为 /var/task，仅 /tmp 可写），原先在 import config 阶段直接抛
`OSError: [Errno 30] Read-only file system: '/var/task/data'`，表现为「无法导入
wsgi.py、Python 进程退出状态 1」这类看不出真实原因的启动崩溃。现在必须抛出
带修复指引的配置错误。
"""

import errno
import os

import pytest

import config as config_module


def test_prepare_sqlite_dir_creates_missing_parent(tmp_path):
    """父目录缺失时自动创建（全新部署 data/ 不存在也能首启建库）。"""
    target = os.path.abspath(os.path.join(str(tmp_path), "data", "blog.db"))
    assert config_module._prepare_sqlite_dir(target) == target
    assert os.path.isdir(os.path.dirname(target))


def test_prepare_sqlite_dir_accepts_ready_directory_and_leaves_no_probe_file(tmp_path):
    """目录已存在且可写时直接通过，写探测用的临时文件不留残留。"""
    target = os.path.abspath(os.path.join(str(tmp_path), "blog.db"))
    assert config_module._prepare_sqlite_dir(target) == target
    assert os.listdir(str(tmp_path)) == []


def test_prepare_sqlite_dir_rejects_parent_occupied_by_a_file(tmp_path):
    """父路径被同名文件占住：跨平台确定性模拟「目录不可用」，须给出配置指引。"""
    blocker = tmp_path / "data"
    blocker.write_text("not a directory", encoding="utf-8")

    with pytest.raises(RuntimeError) as excinfo:
        config_module._prepare_sqlite_dir(os.path.abspath(str(blocker / "blog.db")))

    message = str(excinfo.value)
    assert "BLOG_SQLITE_PATH" in message
    assert "BLOG_DB_TYPE=mysql" in message


def test_prepare_sqlite_dir_reports_readonly_filesystem(tmp_path, monkeypatch):
    """复现 Vercel 报错：EROFS 时提示改用 MySQL 或显式指向 /tmp，而不是裸抛 OSError。"""

    def _readonly_makedirs(path, exist_ok=False):
        raise OSError(errno.EROFS, "Read-only file system", path)

    monkeypatch.setattr(config_module.os, "makedirs", _readonly_makedirs)

    with pytest.raises(RuntimeError) as excinfo:
        config_module._prepare_sqlite_dir(os.path.abspath(os.path.join(str(tmp_path), "data", "blog.db")))

    message = str(excinfo.value)
    assert "Read-only file system" in message
    assert "/tmp/blog.db" in message


def test_resolve_db_uri_sqlite_uses_absolute_path(tmp_path, monkeypatch):
    """sqlite 分支写入绝对路径 URI，并确保父目录就绪。"""
    db_file = tmp_path / "nested" / "blog.db"
    monkeypatch.setenv("BLOG_DB_TYPE", "sqlite")
    monkeypatch.setenv("BLOG_SQLITE_PATH", str(db_file))

    class _Cfg:  # 模拟配置类（from_object 读取类属性）
        pass

    config_module._resolve_db_uri_for_class(_Cfg)

    expected_uri = "sqlite:///" + os.path.abspath(str(db_file))
    assert expected_uri == _Cfg.SQLALCHEMY_DATABASE_URI
    assert _Cfg.SQLALCHEMY_ENGINE_OPTIONS == {}
    assert os.path.isdir(str(db_file.parent))
