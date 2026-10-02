# -*- coding: utf-8 -*-
"""外部目标 URL 校验: 教务网关只允许固定站点内的相对路径。"""
import posixpath
from urllib.parse import unquote, urlsplit


class UnsafeUrlError(ValueError):
    """目标 URL 越出允许的教务站点或路径范围。"""


def safe_jw_path(raw: str, prefix: str = "/njlgdx") -> str:
    """校验并规范化教务相对路径, 返回 path[?query]。

    拒绝绝对 URL、协议相对 URL、反斜杠和路径穿越, 调用方只需拼接固定 origin。
    """
    raw = str(raw or "").strip()
    if not raw or "\\" in raw:
        raise UnsafeUrlError("非法教务路径")
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        raise UnsafeUrlError("只允许教务站内相对路径")
    decoded_path = unquote(parsed.path or "")
    segments = [part for part in decoded_path.split("/") if part]
    if ".." in segments:
        raise UnsafeUrlError("路径穿越被拒绝")
    normalized = posixpath.normpath("/" + "/".join(segments))
    if not normalized.startswith(prefix.rstrip("/") + "/"):
        raise UnsafeUrlError("只允许 /njlgdx/ 下的教务路径")
    out = normalized
    if parsed.query:
        out += "?" + parsed.query
    return out
