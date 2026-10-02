# -*- coding: utf-8 -*-
"""分布式状态后端契约测试(使用内存假 Redis, 不依赖外部服务)。"""
import base64
import fnmatch
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + _tmp.name.replace("\\", "/")
os.environ["SESSION_KEY"] = base64.b64encode(
    b"0123456789abcdef0123456789abcdef").decode()

from wxcloudrun.core import state  # noqa: E402
from wxcloudrun.core import sessions  # noqa: E402
from wxcloudrun.jwc_client import JWCClient  # noqa: E402

PASS, FAIL, FAILURES = 0, 0, []


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print("  [PASS] " + name)
    else:
        FAIL += 1
        FAILURES.append(name)
        print("  [FAIL] " + name + (" -> " + str(detail) if detail else ""))


class _Pipeline:
    def __init__(self, store):
        self.store = store
        self.ops = []

    def incr(self, key):
        self.ops.append(("incr", key, None, None))
        return self

    def expire(self, key, ttl):
        self.ops.append(("expire", key, None, ttl))
        return self

    def execute(self):
        out = []
        for op, key, value, ttl in self.ops:
            if op == "incr":
                out.append(self.store.incr(key))
            elif op == "expire":
                out.append(self.store.expire(key, ttl))
        return out


class _FakeRedis:
    def __init__(self):
        self.data = {}
        self.expiry = {}

    def ping(self):
        return True

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return False
        self.data[key] = str(value)
        if ex:
            self.expiry[key] = float(ex)
        return True

    def delete(self, *keys):
        for key in keys:
            self.data.pop(key, None)
            self.expiry.pop(key, None)

    def expire(self, key, ttl):
        self.expiry[key] = float(ttl)
        return key in self.data

    def incr(self, key):
        value = int(self.data.get(key) or 0) + 1
        self.data[key] = str(value)
        return value

    def scan_iter(self, match="*", count=100):
        for key in list(self.data):
            if fnmatch.fnmatch(key, match):
                yield key

    def pipeline(self):
        return _Pipeline(self)


_fake = _FakeRedis()
state._client = _fake
state._loaded = True

try:
    check("Redis 后端可用时启用分布式状态", state.enabled() is True)
    check("JSON 状态可读写", state.set_json("demo", {"ok": True}, 60)
          and state.get_json("demo") == {"ok": True})
    check("分布式限流计数生效",
          state.rate_hit("rate:test", 60)
          and state.rate_over("rate:test", 1, 60))

    with state.distributed_lock("lock:test", ttl=30) as first:
        with state.distributed_lock("lock:test", ttl=30) as second:
            check("分布式锁同一时刻只允许一个持有者",
                  first is True and second is False, (first, second))

    client = JWCClient()
    client.student_id = "924101960123"
    client.student_name = "State Test"
    client.login_method = "sso-cached"
    client.session.cookies.set(
        "JSESSIONID", "state-cookie", domain="bkjw.njust.edu.cn", path="/")
    check("会话可写入 Redis",
          sessions._persist_remote_session("remote-token", client) is True)
    restored = sessions._load_remote_session("remote-token")
    check("会话可从 Redis 恢复",
          restored is not None
          and restored.student_id == client.student_id
          and restored.logged_in is True)
    check("恢复后的教务 Cookie 一致",
          restored is not None
          and restored.session.cookies.get("JSESSIONID").value == "state-cookie")
    sessions._delete_remote_session("remote-token")
    check("登出可清除远端会话",
          state.get_text("wx:session:token:remote-token") is None)
finally:
    state._client = None
    state._loaded = True
    try:
        os.remove(_tmp.name)
    except OSError:
        pass

print("\n结果: %d 通过, %d 失败" % (PASS, FAIL))
if FAIL:
    print("失败项:", FAILURES)
    sys.exit(1)
print("分布式状态测试全部通过 [OK]")
