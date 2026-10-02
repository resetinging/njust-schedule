# -*- coding: utf-8 -*-
"""评教页面预热(避免 API 层反向依赖 views)。"""
import time


def warm_eval_session(client):
    now = time.time()
    if now - getattr(client, "_eval_warm_ts", 0.0) < 60:
        return
    client._eval_warm_ts = now
    client.session.get(
        "http://202.119.81.112:9080/njlgdx/xspj/xspj_find.do",
        headers={
            "Referer":
            "http://202.119.81.112:9080/njlgdx/framework/main.jsp"
        },
        timeout=10)
