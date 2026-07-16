"""
南理工课表管理系统 — 页面路由
=============================
HTML 页面渲染和教务页面代理。
"""
import os

from flask import Blueprint, render_template, request, Response, jsonify, current_app

from routes import jwc_client, jwc_lock
from eval_helpers import EVAL_HEADERS, warm_eval_session

pages_bp = Blueprint("pages", __name__)


@pages_bp.route("/")
def index():
    """课表主页"""
    return render_template("index.html")


@pages_bp.route("/exams")
def exams_page():
    """考试安排页面"""
    return render_template("exams.html")


@pages_bp.route("/evaluations")
def evaluations_page():
    """教学评价页面"""
    return render_template("evaluations.html")


@pages_bp.route("/grades")
def grades_page():
    """成绩查询页面"""
    return render_template("grades.html")


@pages_bp.route("/settings")
def settings_page():
    """设置页面"""
    return render_template("settings.html")


@pages_bp.route("/gallery")
def gallery_page():
    """校历 & 照片墙"""
    return render_template("gallery.html")


@pages_bp.route("/api/gallery-images")
def api_gallery_images():
    """返回 static/gallery/ 中的所有图片文件名"""
    gallery_dir = os.path.join(current_app.static_folder, "gallery")
    images = []
    if os.path.isdir(gallery_dir):
        for f in sorted(os.listdir(gallery_dir)):
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")):
                images.append(f)
    return jsonify({"images": images})


@pages_bp.route("/proxy/jw/<path:target_path>", methods=["GET", "POST"])
def proxy_jw(target_path):
    """代理教务系统页面（用于嵌入式评价表单）"""
    if not jwc_client.logged_in:
        return "请先登录教务系统", 401

    target_url = f"http://202.119.81.112:9080/njlgdx/{target_path}"
    qs = request.query_string.decode()
    if qs:
        target_url += "?" + qs

    try:
        if request.method == "POST":
            resp = jwc_client.session.post(target_url, data=request.form,
                                           headers=EVAL_HEADERS, timeout=15)
        else:
            warm_eval_session()
            resp = jwc_client.session.get(target_url, headers=EVAL_HEADERS, timeout=15)
    except Exception as e:
        return f"代理请求失败: {e}", 502

    if "text/html" in (resp.headers.get("content-type") or ""):
        content = resp.text
        # 检查是否被教务系统拦截
        if "非法访问" in content or "非法操作" in content:
            return Response(f"""
                <html><body style="padding:40px;text-align:center;font-family:sans-serif;">
                <h2>⚠️ 教务系统拒绝了请求</h2>
                <p>{target_path}</p>
                <p>请尝试：</p>
                <p><a href="/evaluations">返回评价列表</a></p>
                <p><a href="/settings">重新登录教务系统</a></p>
                </body></html>
            """, status=403)
        # 路径替换
        for old, new in [('src="/njlgdx/', 'src="/proxy/jw/'),
                         ('href="/njlgdx/', 'href="/proxy/jw/'),
                         ("src='/njlgdx/", "src='/proxy/jw/"),
                         ("href='/njlgdx/", "href='/proxy/jw/"),
                         ('action="/njlgdx/', 'action="/proxy/jw/'),
                         ("action='/njlgdx/", "action='/proxy/jw/"),
                         ('"/njlgdx/js/', '"/proxy/jw/js/'),
                         ("'/njlgdx/js/", "'/proxy/jw/js/")]:
            content = content.replace(old, new)
        return Response(content, status=resp.status_code,
                        content_type="text/html; charset=utf-8")
    return Response(resp.content, status=resp.status_code,
                    content_type=resp.headers.get("content-type", "text/html"))
