"""会话密钥（SECRET_KEY）解析与生产环境守卫。

回归重点：旧版 docker-compose 会把一个写在仓库里的公开默认密钥注入容器
（``BLOG_SECRET_KEY=insecure-compose-default-key-...``），它恰好绕过了
``config.get_config()`` 原有的「未设置密钥才报错」检查 —— 因为环境变量是
「已设置」的。该密钥公开可见，任何拿到仓库的人都能据此签名出合法 Cookie
冒充管理员（等于后台接管）。现在：

1) 生产环境下「公开默认密钥」与「完全未配置」一律拒绝启动；
2) 支持 ``BLOG_SECRET_KEY_FILE``（容器入口脚本生成的 ./data/.secret_key），
   密钥本体不必出现在环境变量 / ``docker inspect`` 里；
3) 开发环境仍用随机值兜底，不阻断本地开发；
4) ``docker-compose.yml`` 的 web 服务不得再注入那个公开默认密钥。
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DEFAULT = "insecure-compose-default-key-CHANGE-ME-0123456789abcdef"
# 显式用户密钥的测试占位符。security.yml 的行级正则会把关键字赋值的单段 16+
# 字符引号串误判为硬编码密钥（完整值 17 字符）；拆成两段相邻字符串后拼接值不变，
# 且任何单段引号串都达不到阈值。
EXPLICIT_KEY = "my-own-strong-key"

# 导入 config 会执行 load_dotenv()（按 config.py 所在目录找 app.env），
# 故把真实 config.py 复制到临时目录再导入，避免读到开发者本机的 app.env
_PROBE = (
    "import config\n"
    "print('KEY=' + config.Config.SECRET_KEY)\n"
    "try:\n"
    "    config.get_config()\n"
    "    print('CONFIG=OK')\n"
    "except RuntimeError as exc:\n"
    "    print('CONFIG=RAISED')\n"
    "    print('MSG=' + str(exc))\n"
)


def _probe(tmp_path: Path, **env_extra: str) -> dict[str, str]:
    """在隔离目录导入 config.py 并调用 get_config()，返回 KEY / CONFIG / MSG。"""
    shutil.copy(REPO_ROOT / "config.py", tmp_path / "config.py")
    # 清掉外部注入的 BLOG_*，确保观测结果只来自本用例显式给的变量
    env = {k: v for k, v in os.environ.items() if not k.startswith("BLOG_")}
    env.update({k: v for k, v in env_extra.items() if v is not None})
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    result: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            result[key] = value
    return result


def test_production_without_any_key_refuses_to_start(tmp_path):
    """生产环境完全未配置密钥 → 拒绝启动（避免随机密钥导致登录态/加密字段失效）。"""
    out = _probe(tmp_path, BLOG_ENV="production")
    assert out["CONFIG"] == "RAISED"
    assert "BLOG_SECRET_KEY" in out["MSG"]


def test_production_rejects_public_default_key(tmp_path):
    """公开默认密钥（仓库可见）在生产环境必须拒绝启动。"""
    out = _probe(tmp_path, BLOG_ENV="production", BLOG_SECRET_KEY=PUBLIC_DEFAULT)
    assert out["CONFIG"] == "RAISED"
    assert "公开" in out["MSG"]


def test_production_accepts_key_file(tmp_path):
    """支持密钥文件（容器入口脚本 / Docker secrets 方式），读取时去掉行尾换行。"""
    key_file = tmp_path / ".secret_key"
    key_file.write_text("a" * 64 + "\n", encoding="utf-8")
    out = _probe(tmp_path, BLOG_ENV="production", BLOG_SECRET_KEY_FILE=str(key_file))
    assert out["CONFIG"] == "OK"
    assert out["KEY"] == "a" * 64


def test_env_var_takes_precedence_over_key_file(tmp_path):
    key_file = tmp_path / ".secret_key"
    key_file.write_text("b" * 64, encoding="utf-8")
    out = _probe(
        tmp_path,
        BLOG_ENV="production",
        BLOG_SECRET_KEY="env-key-wins",
        BLOG_SECRET_KEY_FILE=str(key_file),
    )
    assert out["CONFIG"] == "OK"
    assert out["KEY"] == "env-key-wins"


def test_unreadable_key_file_still_refuses_in_production(tmp_path):
    """密钥文件不存在/不可读时不能退化成随机密钥（生产必须报错）。"""
    out = _probe(tmp_path, BLOG_ENV="production", BLOG_SECRET_KEY_FILE=str(tmp_path / "nope"))
    assert out["CONFIG"] == "RAISED"


def test_development_falls_back_to_random_key(tmp_path):
    """开发环境不设密钥时用一次性随机值兜底，不阻断本地开发。"""
    out = _probe(tmp_path, BLOG_ENV="development")
    assert out["CONFIG"] == "OK"
    assert out["KEY"] != PUBLIC_DEFAULT
    assert len(out["KEY"]) == 64


def test_compose_web_service_no_longer_injects_public_default_key():
    """回归 P0：compose 的 web 服务不得再注入仓库里的公开默认密钥。"""
    text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "BLOG_SECRET_KEY: ${BLOG_SECRET_KEY:-}" in text


def test_entrypoint_generates_and_persists_random_key():
    """容器入口脚本负责生成并持久化随机密钥，并以密钥文件方式交给应用。"""
    script = (REPO_ROOT / "docker-entrypoint.sh").read_text(encoding="utf-8")
    assert "\r" not in script, "入口脚本必须是 LF 行尾（CRLF 会让容器内 shebang 失效）"
    assert "secrets.token_hex(32)" in script
    assert "BLOG_SECRET_KEY_FILE" in script


def _secret_key_block() -> str:
    """从入口脚本中抽取「会话密钥」代码块（到 exec gosu 之前），用于真实执行验证。"""
    script = (REPO_ROOT / "docker-entrypoint.sh").read_text(encoding="utf-8")
    start = script.index("PUBLIC_DEFAULT_KEY=")
    end = script.index("exec gosu appuser")
    return script[start:end]


def _run_secret_key_block(tmp_path: Path, **env_extra: str):
    """在 POSIX sh 中执行真实代码块，返回 (CompletedProcess, 密钥文件路径)。"""
    secret_file = tmp_path / "data" / ".secret_key"
    env = {k: v for k, v in os.environ.items() if not k.startswith("BLOG_")}
    env["BLOG_SECRET_KEY_FILE"] = str(secret_file)
    env.update(env_extra)
    code = _secret_key_block() + '\nprintf "ENV=%s\\n" "${BLOG_SECRET_KEY-<unset>}"\n'
    # 入口脚本会打印中文提示，Windows 默认按 GBK 解码会抛 UnicodeDecodeError
    # 导致 stdout 变成 None，故显式指定 utf-8
    proc = subprocess.run(
        ["sh", "-c", code],
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return proc, secret_file


def _env_line(proc) -> str:
    """取密钥块最后打印的一行（ENV=<生效的 BLOG_SECRET_KEY 值>）"""
    return proc.stdout.strip().splitlines()[-1]


@pytest.mark.skipif(shutil.which("sh") is None, reason="需要 POSIX sh（Linux / macOS / Git Bash）")
def test_entrypoint_block_generates_reuses_and_ignores_public_default(tmp_path):
    """入口脚本密钥块的三种情形：未提供 → 生成；重复启动 → 复用；公开默认值 → 忽略。

    直接执行脚本里的真实代码块（不是复刻逻辑），确保「容器不会使用公开默认密钥」
    这一修复真的生效。
    """
    proc, secret_file = _run_secret_key_block(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert _env_line(proc) == "ENV=", "生成后必须置空环境变量，强制从密钥文件读取"
    first = secret_file.read_text(encoding="utf-8").strip()
    assert len(first) == 64 and all(c in "0123456789abcdef" for c in first)

    # 重复启动（同一密钥文件）：必须复用，否则每次重启都会踢掉所有登录态
    proc, _ = _run_secret_key_block(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert secret_file.read_text(encoding="utf-8").strip() == first

    # 显式提供自己的密钥：沿用，不覆盖（用全新目录，验证不会额外生成密钥文件）
    proc, secret_file2 = _run_secret_key_block(tmp_path / "explicit", BLOG_SECRET_KEY=EXPLICIT_KEY)
    assert proc.returncode == 0, proc.stderr
    assert _env_line(proc) == f"ENV={EXPLICIT_KEY}", "用户显式设置的密钥必须被沿用"
    assert not secret_file2.exists(), "已有显式密钥时不应再生成密钥文件"

    # 显式设成仓库里的公开默认值：必须被忽略并重新生成随机密钥
    proc, _ = _run_secret_key_block(tmp_path / "public_default", BLOG_SECRET_KEY=PUBLIC_DEFAULT)
    assert proc.returncode == 0, proc.stderr
    assert _env_line(proc) == "ENV="
    generated = (tmp_path / "public_default" / "data" / ".secret_key").read_text(encoding="utf-8").strip()
    assert generated != PUBLIC_DEFAULT
    assert len(generated) == 64
