"""教务会话 Cookie 的加密持久化(会话持久化方案的加密层)。

设计要点:
- AES-256-GCM, 每行随机 IV(12B), AAD 绑定学号(换学号解密必然失败);
- 密文结构 base64(key_version | iv | ciphertext+tag);
- 未配置 SESSION_KEY(config/env) 时整体禁用: enabled() 返回 False, 调用方直接跳过,
  绝不降级成明文;
- 只负责加解密, 不碰认证流程。
"""
import base64
import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import config

_KEY = None
_KEY_LOADED = False
KEY_VERSION = 1
IV_LEN = 12


def key() -> bytes:
    """32 字节密钥; 未配置/长度不对时返回 b''(视为禁用)"""
    global _KEY, _KEY_LOADED
    if not _KEY_LOADED:
        raw = os.environ.get('SESSION_KEY', '') or getattr(config, 'SESSION_KEY', '')
        try:
            _KEY = base64.b64decode(raw) if raw else b''
        except Exception:
            _KEY = b''
        _KEY_LOADED = True
    return _KEY if len(_KEY) == 32 else b''


def enabled() -> bool:
    return len(key()) == 32


def encrypt(student_id: str, cookies: list) -> str:
    """cookies(纯数据 list) → 密文; 未启用时抛 RuntimeError"""
    k = key()
    if not k:
        raise RuntimeError('SESSION_KEY 未配置, 会话持久化不可用')
    iv = os.urandom(IV_LEN)
    plain = json.dumps(cookies, ensure_ascii=False).encode('utf-8')
    blob = AESGCM(k).encrypt(iv, plain, str(student_id).encode('utf-8'))
    return base64.b64encode(bytes([KEY_VERSION]) + iv + blob).decode('ascii')


def decrypt(student_id: str, token: str) -> list:
    """密文 → cookies; 密钥缺失/版本不符/被篡改/学号不符 一律返回 []"""
    k = key()
    if not k or not token:
        return []
    try:
        raw = base64.b64decode(token)
        if not raw or raw[0] != KEY_VERSION or len(raw) < 1 + IV_LEN + 16:
            return []
        iv = raw[1:1 + IV_LEN]
        plain = AESGCM(k).decrypt(iv, raw[1 + IV_LEN:], str(student_id).encode('utf-8'))
        data = json.loads(plain.decode('utf-8'))
        return data if isinstance(data, list) else []
    except (InvalidTag, ValueError, TypeError):
        return []
    except Exception:
        return []
