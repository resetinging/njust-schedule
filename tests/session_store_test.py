# -*- coding: utf-8 -*-
"""会话持久化加密层用例(用 sqlite 跑, 不依赖 MySQL)。

覆盖: 加解密往返 / 换学号(AAD)必须失败 / 篡改密文必须失败 / 未配置密钥时整体禁用。
"""
import base64
import os
import sys

os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///session_store_test.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["SESSION_KEY"] = base64.b64encode(os.urandom(32)).decode()

from wxcloudrun.core import cookie_crypto as ss  # noqa: E402
from wxcloudrun.core import session_store as store  # noqa: E402

COOKIES = [{"name": "JWX", "value": "abc123", "domain": "jw.njust.edu.cn", "path": "/"}]
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(ok)
    line = ("  [PASS] " if ok else "  [FAIL] ") + name
    if detail and not ok:
        line += " -> " + str(detail)
    print(line)


def main():
    check("密钥已启用", ss.enabled())
    token = ss.encrypt("924101960123", COOKIES)
    check("密文非空且不含明文", bool(token) and "JWX" not in token, token[:24])
    check("加解密往返一致", ss.decrypt("924101960123", token) == COOKIES)
    check("换学号(AAD)必须失败", ss.decrypt("924101960999", token) == [])
    tampered = token[:-6] + ("AAAAAA" if token[-6:] != "AAAAAA" else "BBBBBB")
    check("篡改密文必须失败", ss.decrypt("924101960123", tampered) == [])
    check("空密文返回空", ss.decrypt("924101960123", "") == [])
    # 真实读写路径(dao + 加密落库 + 旧明文兼容)
    class _Cookie(object):
        def __init__(self, name, value):
            self.name, self.value, self.domain, self.path = name, value, "jw.njust.edu.cn", "/"

    sid = "924101960123"
    written = store.save_session(sid, [_Cookie("JWX", "abc123")])
    check("加密落库写入成功", written == 1, written)
    loaded = store.load_session(sid) or []
    check("加密落库后能原样读回", loaded == COOKIES)
    from wxcloudrun import dao as _dao
    from config import SSO_SESSION_SETTING_KEY as K
    import json as _json
    _dao.set_user_setting(sid, K, _json.dumps({"ts": int(__import__("time").time()),
                                               "cookies": [{"name": "LEGACY", "value": "1",
                                                            "domain": "x", "path": "/"}]}))
    check("旧明文格式仍可读(向后兼容)",
          (store.load_session(sid) or [{}])[0].get("name") == "LEGACY")
    store.clear_session(sid)
    check("清理后读不到", store.load_session(sid) is None)
    # 认证节流契约(登录链路依赖, 之前无人覆盖)
    check("初始无冷却", store.cooldown_left(sid) == 0, store.cooldown_left(sid))
    store.mark_failure(sid)
    check("失败后进入冷却", store.cooldown_left(sid) > 0, store.cooldown_left(sid))
    store.clear_failure(sid)
    check("成功后冷却清零", store.cooldown_left(sid) == 0, store.cooldown_left(sid))
    os.environ["SESSION_KEY"] = ""
    # config 在 import 时就把环境变量捕获了, 必须同步清掉它, 否则测的仍是旧密钥
    import config as _cfg
    _cfg.SESSION_KEY = ""
    ss._KEY_LOADED = False
    check("未配置密钥时禁用", ss.enabled() is False)
    try:
        ss.encrypt("924101960123", COOKIES)
        check("未配置密钥时加密应抛错", False)
    except RuntimeError:
        check("未配置密钥时加密应抛错", True)
    bad = sum(1 for r in RESULTS if not r)
    print("\n结果: %d 通过, %d 失败" % (len(RESULTS) - bad, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
