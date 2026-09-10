"""敏感字段加密/解密工具。

`site_config.mail_password` 等敏感字段以 Fernet 对称加密后落库，
密钥由 `SECRET_KEY` 经 SHA-256 派生（不新增独立密钥管理负担）。

注意：`SECRET_KEY` 必须持久化（写入 .env 的 `BLOG_SECRET_KEY`），
否则每次进程重启密钥变化，将无法解出已加密的字段。
"""

import base64
import hashlib

from cryptography.fernet import Fernet
from flask import current_app

# Fernet token 前缀特征（版本字节 0x80 → "gA"，后跟时间戳，固定以 "gAAAA" 开头）
_FERNET_PREFIX = "gAAAA"


def _key() -> bytes:
    secret = current_app.config.get("SECRET_KEY") or ""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_secret(plaintext: str) -> str:
    """加密敏感值；空值返回空串。"""
    if not plaintext:
        return ""
    return Fernet(_key()).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    """解密敏感值。

    - 空值返回空串；
    - 非密文（历史明文）原样返回，兼容旧数据；
    - 解密失败（密钥变更/损坏）返回空串，避免抛异常中断业务流程。
    """
    if not value:
        return ""
    if not value.startswith(_FERNET_PREFIX):
        return value  # 兼容历史明文
    try:
        return Fernet(_key()).decrypt(value.encode("ascii")).decode("utf-8")
    except Exception:
        return ""
