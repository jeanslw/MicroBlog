"""应用侧配置文件加载行为测试：app.env 优先，旧版 .env 兼容回退。

实现方式：把真实 config.py 复制到临时目录后以子进程导入——路径由
`os.path.dirname(__file__)` 推导，因此副本会读取临时目录里的 env 文件，
既覆盖真实加载逻辑，又不会影响开发者本机的 app.env / .env。
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# 导入 config 会触发 load_dotenv()，故在同一个进程里捕获其告警
_PROBE = (
    "import os, warnings\n"
    "with warnings.catch_warnings(record=True) as caught:\n"
    "    warnings.simplefilter('always')\n"
    "    import config\n"
    "print('DB_TYPE=' + str(os.environ.get('BLOG_DB_TYPE')))\n"
    "print('PAGE_SIZE=' + str(os.environ.get('BLOG_PAGE_SIZE')))\n"
    "print('WARN=' + '|'.join(str(w.message) for w in caught))\n"
)


def _import_config_with(tmp_path: Path, **files: str) -> dict[str, str]:
    """在临时目录中放入指定的 env 文件并导入 config.py，返回探针结果。"""
    shutil.copy(REPO_ROOT / "config.py", tmp_path / "config.py")
    for name, content in files.items():
        (tmp_path / name.replace("__", ".")).write_text(content, encoding="utf-8")

    # 清掉外部注入的 BLOG_*，确保观测到的值只来自 env 文件
    env = {k: v for k, v in os.environ.items() if not k.startswith("BLOG_")}
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr

    result = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            result[key] = value
    return result


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        # app.env 是唯一正式的应用侧配置文件
        ({"app__env": "BLOG_DB_TYPE=sqlite\nBLOG_PAGE_SIZE=11\n"}, ("sqlite", "11")),
        # 兼容期：app.env 与旧版 .env 同时存在时以 app.env 为准
        (
            {"app__env": "BLOG_DB_TYPE=sqlite\nBLOG_PAGE_SIZE=11\n", ".env": "BLOG_DB_TYPE=mysql\n"},
            ("sqlite", "11"),
        ),
    ],
)
def test_app_env_is_loaded_and_wins_over_legacy_env(tmp_path, files, expected):
    result = _import_config_with(tmp_path, **files)
    assert (result["DB_TYPE"], result["PAGE_SIZE"]) == expected
    assert result["WARN"] == "", "使用 app.env 时不应产生迁移告警"


def test_legacy_env_is_read_as_fallback_with_warning(tmp_path):
    """app.env 缺失时回退读取旧版 .env，并提示迁移（避免老用户配置静默失效）。"""
    result = _import_config_with(tmp_path, **{".env": "BLOG_DB_TYPE=sqlite\n"})
    assert result["DB_TYPE"] == "sqlite"
    assert "app.env" in result["WARN"]


def test_no_config_file_is_silent(tmp_path):
    """两个文件都不存在时保持安静（不产生误导性告警）。"""
    result = _import_config_with(tmp_path)
    assert result["DB_TYPE"] == "None"
    assert result["WARN"] == ""


def test_repo_root_has_no_committed_runtime_env_file():
    """运行时配置文件不入库：仓库里只允许 *.example 模板与编排侧 .env.docker.example。"""
    tracked = subprocess.run(
        ["git", "ls-files", ".env", "app.env", ".env.docker", "app.env.example", ".env.docker.example"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert set(tracked) == {"app.env.example", ".env.docker.example"}, tracked
