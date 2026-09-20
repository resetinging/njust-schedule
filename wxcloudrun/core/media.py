# -*- coding: utf-8 -*-
"""图片类型嗅探(验证码/图鉴共用)。"""


def _sniff_image_mime(data: bytes) -> str:
    """根据文件头识别图片类型, 前端据此构造 data URL"""
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if data.startswith(b"BM"):
        return "image/bmp"
    return "image/png"
