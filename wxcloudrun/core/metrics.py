# -*- coding: utf-8 -*-
"""轻量 Prometheus 指标(单进程聚合, 无外部依赖)。"""
import threading

_lock = threading.Lock()
_requests = {}
_duration_sum = {}


def observe_request(path: str, status: int, duration_ms: float) -> None:
    path = str(path or "-").split("?", 1)[0]
    key = (path, str(int(status)))
    with _lock:
        _requests[key] = int(_requests.get(key, 0)) + 1
        _duration_sum[key] = float(_duration_sum.get(key, 0.0)) + max(
            0.0, float(duration_ms))


def render() -> str:
    with _lock:
        requests = dict(_requests)
        durations = dict(_duration_sum)
    lines = [
        "# HELP njust_http_requests_total Total HTTP requests.",
        "# TYPE njust_http_requests_total counter",
    ]
    for (path, status), count in sorted(requests.items()):
        lines.append(
            'njust_http_requests_total{path="%s",status="%s"} %d'
            % (path.replace('"', '\\"'), status, count))
    lines.extend([
        "# HELP njust_http_request_duration_ms_sum Total request duration.",
        "# TYPE njust_http_request_duration_ms_sum counter",
    ])
    for (path, status), value in sorted(durations.items()):
        lines.append(
            'njust_http_request_duration_ms_sum{path="%s",status="%s"} %.3f'
            % (path.replace('"', '\\"'), status, value))
    return "\n".join(lines) + "\n"
