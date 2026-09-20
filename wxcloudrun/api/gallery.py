# -*- coding: utf-8 -*-
"""图鉴(校历 / 校区地图)图片路由。

从 views.py 拆出; URL 与响应字段保持不变:
  - /api/gallery-images        图片列表
  - /api/gallery-image         整图 base64(兼容旧版/Web)
  - /api/gallery-image-meta    分片元信息
  - /api/gallery-image-part    分片数据
"""
import base64
import os

from flask import Blueprint, current_app, jsonify, request

from wxcloudrun.core.media import _sniff_image_mime

gallery_bp = Blueprint("gallery_api", __name__)

# 分片下载: 每片二进制 300KB → base64 约 400KB(JSON 包装后 <500KB),
# 远离 callContainer 返回包 ~1000KB 限制。
_GALLERY_CHUNK_BYTES = 300 * 1024


@gallery_bp.route('/api/gallery-images')
def api_gallery_images():
    """返回 static/gallery/ 目录下的图片列表"""
    gallery_dir = os.path.join(current_app.static_folder, 'gallery')
    images = []
    if os.path.isdir(gallery_dir):
        for f in sorted(os.listdir(gallery_dir)):
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')):
                images.append(f)
    return jsonify({"success": True, "images": images})


@gallery_bp.route('/api/gallery-image')
def api_gallery_image():
    """返回单张校历图片的 base64 数据（供小程序通过云托管内网获取）

    注意: 微信云托管 callContainer 返回包限制约 1000KB, 大图必须走
    /api/gallery-image-meta + /api/gallery-image-part 分片下载。
    此接口保留用于兼容旧版小程序与 Web 端。
    """
    name = (request.args.get("name") or "").strip()
    if not name or "/" in name or "\\" in name or ".." in name:
        return jsonify({"success": False, "message": "无效的文件名"}), 400
    path = os.path.join(current_app.static_folder, 'gallery', name)
    if not os.path.isfile(path):
        return jsonify({"success": False, "message": "图片不存在"}), 404
    with open(path, "rb") as f:
        data = f.read()
    return jsonify({
        "success": True,
        "name": name,
        "mime": _sniff_image_mime(data),
        "data_b64": base64.b64encode(data).decode(),
    })


def _gallery_validate(name):
    """校验图片文件名, 返回 (path, None) 或 (None, 错误响应)"""
    if not name or "/" in name or "\\" in name or ".." in name:
        return None, (jsonify({"success": False, "message": "无效的文件名"}), 400)
    path = os.path.join(current_app.static_folder, 'gallery', name)
    if not os.path.isfile(path):
        return None, (jsonify({"success": False, "message": "图片不存在"}), 404)
    return path, None


@gallery_bp.route('/api/gallery-image-meta')
def api_gallery_image_meta():
    """单张校历图片的分片元信息（小程序分片下载大图）"""
    name = (request.args.get("name") or "").strip()
    path, err = _gallery_validate(name)
    if err:
        return err
    size = os.path.getsize(path)
    parts = max(1, (size + _GALLERY_CHUNK_BYTES - 1) // _GALLERY_CHUNK_BYTES)
    return jsonify({
        "success": True,
        "name": name,
        "size": size,
        "parts": parts,
        "chunk_bytes": _GALLERY_CHUNK_BYTES,
    })


@gallery_bp.route('/api/gallery-image-part')
def api_gallery_image_part():
    """返回单张校历图片第 part 片的 base64 数据（part 从 0 开始）"""
    name = (request.args.get("name") or "").strip()
    try:
        part = int(request.args.get("part", "0"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "无效的分片序号"}), 400
    path, err = _gallery_validate(name)
    if err:
        return err
    size = os.path.getsize(path)
    parts = max(1, (size + _GALLERY_CHUNK_BYTES - 1) // _GALLERY_CHUNK_BYTES)
    if part < 0 or part >= parts:
        return jsonify({"success": False, "message": "分片序号越界"}), 400
    with open(path, "rb") as f:
        f.seek(part * _GALLERY_CHUNK_BYTES)
        data = f.read(_GALLERY_CHUNK_BYTES)
    return jsonify({
        "success": True,
        "name": name,
        "part": part,
        "parts": parts,
        "data_b64": base64.b64encode(data).decode(),
    })
