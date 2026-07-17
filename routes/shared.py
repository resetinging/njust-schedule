"""Routes shared state (jwc_client singleton, locks, progress dicts)."""
import base64
import time
import threading
import socket

from jwc import JWCClient
from database import get_setting, set_setting

# ---- 全局教务客户端 ----
jwc_client = JWCClient()
jwc_lock = threading.Lock()

# ---- 批量评教进度 ----
_batch_progress = {}
_batch_progress_lock = threading.Lock()

# ---- 自动登录冷却 ----
_auto_login_attempted = False
_last_auto_login_time = 0.0

# ---- 网络状态缓存（30 秒有效期） ----
_network_status = {"reachable": False, "method": "", "latency_ms": 0,
                   "label": "检测中...", "hint": "", "checked_at": 0.0}
_NETWORK_CACHE_TTL = 30


def check_network() -> dict:
    """获取网络状态（带缓存）"""
    global _network_status
    now = time.time()
    if now - _network_status.get("checked_at", 0) < _NETWORK_CACHE_TTL:
        return dict(_network_status)
    status = jwc_client.check_connectivity()
    status["checked_at"] = now
    _network_status = status
    return dict(status)


def get_lan_ip() -> str:
    """获取局域网 IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.254.254.254", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"
