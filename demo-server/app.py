"""
课表助手 · 素材服务器（演示账号 + 种子数据）— 用于录制推广视频

设计原则:
- 不修改 wxcloudrun / 小程序任何源码: 复用完整 Flask 应用,
  仅在本进程中替换几个 view_functions 注入演示逻辑。
- 独立 SQLite 库 demo.db, 演示账号登录即完成种子数据(彩课/考试/成绩/评教批次)。
- 空教室查询仍走真实服务账号(数据真实, 适合拍"61 间"素材);
  刷新/评教/清缓存接口替换为演示行为, 拍摄时不会碰教务、不会清掉种子数据。

启动: ..\\.venv\\Scripts\\python.exe app.py   (或双击 run.bat)
登录: 学号 20260001, 密码任意(如 123456)
重置: 删除本目录 demo.db 后重启
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

# 必须在导入 wxcloudrun 之前指定独立演示库
DEMO_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo.db")
os.environ["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DEMO_DB.replace(chr(92), '/')}"

from wxcloudrun import app, dao  # noqa: E402  (导入即建表)
from wxcloudrun import views  # noqa: E402
from wxcloudrun.jwc_client import JWCClient  # noqa: E402

# 登录成功后的公共处理: 重构后位于 api/auth.py(旧版在 views)
try:
    from wxcloudrun.api.auth import _on_login_success
except ImportError:  # pragma: no cover
    from wxcloudrun.views import _on_login_success

DEMO_SID = "20260001"
DEMO_NAME = "南理工同学"


def _view_key(name):
    """实际 view_functions 键名。

    兼容两种情况: 蓝图命名空间(如 auth_api.api_login)与旧版 plain 名(api_login)。
    """
    if name in app.view_functions:
        return name
    for k in app.view_functions:
        if k.endswith("." + name):
            return k
    return None


def _get_view(name):
    k = _view_key(name)
    return app.view_functions.get(k) if k else None


def _set_view(name, fn):
    """替换视图实现(跟随蓝图命名空间键, 找不到时回退旧名)"""
    app.view_functions[_view_key(name) or name] = fn


def _current_semester() -> str:
    return JWCClient()._current_semester()  # 纯日期计算, 不联网


def _this_monday() -> str:
    import datetime
    today = datetime.date.today()
    return (today - datetime.timedelta(days=today.weekday())).isoformat()


def _seed(sid: str) -> str:
    """首登写入拍摄用种子数据(幂等), 返回当前学期"""
    semester = _current_semester()
    if dao.count_courses(semester, sid) > 0:
        return semester

    monday = _this_monday()
    # 第一周周一=本周一 → 课表"第1周(本周)"、今天列定位正确
    dao.set_user_setting(sid, "semester", semester)
    dao.set_setting(f"{sid}:first_week_date:{semester}", monday)
    dao.set_setting("first_week_date", monday)

    # ── 课表: 10 门, 覆盖周一~周五(颜色由课程名自动分配, 五彩) ──
    courses = [
        dict(name="高等数学", teacher="王建国", classroom="Ⅳ-A411", day=1, start=1, end=3,
             weeks="1-20", week_type=0, credits="5.0", course_type="必修", raw={}),
        dict(name="大学英语", teacher="李静", classroom="Ⅳ-B505", day=2, start=4, end=5,
             weeks="1-20", week_type=0, credits="3.0", course_type="必修", raw={}),
        dict(name="线性代数", teacher="陈晓", classroom="I-201", day=3, start=1, end=3,
             weeks="1-20", week_type=0, credits="3.5", course_type="必修", raw={}),
        dict(name="程序设计", teacher="刘洋", classroom="Ⅳ-C107", day=4, start=6, end=7,
             weeks="1-20", week_type=0, credits="4.0", course_type="必修", raw={}),
        dict(name="大学物理", teacher="赵启明", classroom="Ⅳ-A301", day=1, start=8, end=10,
             weeks="1-20", week_type=0, credits="4.0", course_type="必修", raw={}),
        dict(name="体育", teacher="孙教练", classroom="体育中心", day=3, start=6, end=7,
             weeks="1-20", week_type=0, credits="1.0", course_type="必修", raw={}),
        dict(name="形势与政策", teacher="周强", classroom="Ⅱ-101", day=2, start=11, end=13,
             weeks="1-16", week_type=0, credits="2.0", course_type="必修", raw={}),
        # 同一门课"不同周次上课时间不同"(第1-8周 第4-5节 → 第9-16周 第1-2节):
        # 用于演示"按周次各显示各自时间"(多时段解析修复)
        dict(name="概率论与数理统计", teacher="吴敏", classroom="Ⅳ-B411", day=5, start=4, end=5,
             weeks="1-8", week_type=0, credits="3.0", course_type="必修", raw={}),
        dict(name="概率论与数理统计", teacher="吴敏", classroom="Ⅳ-B411", day=5, start=1, end=2,
             weeks="9-16", week_type=0, credits="3.0", course_type="必修", raw={}),
        dict(name="工程制图", teacher="郑华", classroom="I-102", day=5, start=1, end=3,
             weeks="1-20", week_type=0, credits="3.0", course_type="必修", raw={}),
        dict(name="军事理论", teacher="胡教官", classroom="Ⅳ-A308", day=3, start=11, end=13,
             weeks="1-12", week_type=1, credits="2.0", course_type="选修", raw={}),
    ]
    dao.save_courses(courses, semester, sid)

    # ── 考试 ──
    dao.save_exams([
        dict(course_name="高等数学", date="2027-01-12", time="09:00-11:00",
             location="一工101", seat="12", type="期末考试"),
        dict(course_name="大学英语", date="2027-01-14", time="14:00-16:00",
             location="二工203", seat="8", type="期末考试"),
        dict(course_name="大学物理", date="2027-01-16", time="09:00-11:00",
             location="四工A301", seat="20", type="期末考试"),
    ], semester, sid)

    # ── 成绩: 本学期 8 门 + 上学期 3 门(多学期对比) ──
    grades_this = [
        dict(course_name="高等数学", score="92", credit=5.0, grade_point=4.0,
             academic_year="2026-2027", semester="1", course_type="必修",
             course_nature="公共基础", exam_type="正常考试"),
        dict(course_name="大学英语", score="85", credit=3.0, grade_point=3.7,
             academic_year="2026-2027", semester="1", course_type="必修",
             course_nature="公共基础", exam_type="正常考试"),
        dict(course_name="线性代数", score="88", credit=3.5, grade_point=3.7,
             academic_year="2026-2027", semester="1", course_type="必修",
             course_nature="学科基础", exam_type="正常考试"),
        dict(course_name="程序设计", score="90", credit=4.0, grade_point=4.0,
             academic_year="2026-2027", semester="1", course_type="必修",
             course_nature="学科基础", exam_type="正常考试"),
        dict(course_name="大学物理", score="86", credit=4.0, grade_point=3.7,
             academic_year="2026-2027", semester="1", course_type="必修",
             course_nature="公共基础", exam_type="正常考试"),
        dict(course_name="体育", score="良好", credit=1.0, grade_point=3.0,
             academic_year="2026-2027", semester="1", course_type="必修",
             course_nature="公共基础", exam_type="正常考试"),
        dict(course_name="形势与政策", score="及格", credit=2.0, grade_point=1.0,
             academic_year="2026-2027", semester="1", course_type="必修",
             course_nature="公共基础", exam_type="正常考试"),
        dict(course_name="概率论与数理统计", score="89", credit=3.0, grade_point=3.7,
             academic_year="2026-2027", semester="1", course_type="必修",
             course_nature="学科基础", exam_type="正常考试"),
    ]
    grades_prev = [
        dict(course_name="高等数学", score="85", credit=5.0, grade_point=3.7,
             academic_year="2025-2026", semester="2", course_type="必修",
             course_nature="公共基础", exam_type="正常考试"),
        dict(course_name="C语言程序设计", score="91", credit=4.0, grade_point=4.0,
             academic_year="2025-2026", semester="2", course_type="必修",
             course_nature="学科基础", exam_type="正常考试"),
        dict(course_name="大学英语", score="82", credit=3.0, grade_point=3.3,
             academic_year="2025-2026", semester="2", course_type="必修",
             course_nature="公共基础", exam_type="正常考试"),
    ]
    dao.save_grades(grades_this, "2026-2027", "1", sid)
    dao.save_grades(grades_prev, "2025-2026", "2", sid)

    # ── 四六级 ──
    dao.save_cet_scores([
        dict(type="CET4", score=550, exam_date="2026-06"),
        dict(type="CET6", score=500, exam_date="2026-12"),
    ], sid)

    # ── 评教: 一个未完成批次(一键评教拍摄素材) ──
    dao.save_evaluations([
        dict(semester=semester, category="理论课", batch="第1批",
             start_date="2026-12-01", end_date="2026-12-31", is_done=False,
             items=[dict(name="进入评教", url="/demo/eval")]),
    ], semester, sid)

    # ── 公告: 主页面顶部横幅 + "我的"页公告栏(拍摄"公告即时送达") ──
    dao.set_setting("announcement_enabled", "1")
    dao.set_setting("announcement_text",
                    "期末考试安排已发布，可在「考试」页查看时间与考场；"
                    "评教第一批已开放，记得在截止前完成～")
    import time as _time
    dao.set_setting("announcement_updated", _time.strftime("%Y-%m-%d %H:%M:%S"))

    # ── 反馈: 一条已回复(带未读小红点) + 一条待处理(拍摄"查看官方回复") ──
    fb_replied = dao.save_feedback(
        sid, DEMO_NAME, "bug",
        "课表里有门课在第1-8周和第9-16周的上课时间不一样，之前只显示一个时间")
    dao.set_feedback_reply(
        fb_replied.get("id"), "已修复：现在按周次分别显示各自的上课时间，重新获取课表即可看到。感谢反馈！")
    dao.save_feedback(sid, DEMO_NAME, "suggest", "希望空教室能收藏常用教学楼～")

    return semester


def _demo_sid():
    """当前请求对应的用户学号(无会话返回 '')"""
    from flask import request
    try:
        client = views._get_session_client()
    except Exception:
        client = None
    return (client.student_id or "") if client else ""


# ============================================================
# 视图替换: 演示账号走演示逻辑, 其余照旧
# ============================================================

def _demo_client(sid, login_method="demo"):
    """构造演示会话客户端(不联网)"""
    _seed(sid)
    client = JWCClient()
    client.logged_in = True
    client.student_id = sid
    client.student_name = DEMO_NAME
    client.login_method = login_method
    client.is_session_valid = lambda: True
    return client


def _demo_sid_from_request():
    from flask import request
    return ((request.get_json(silent=True) or {}).get("student_id") or "").strip()


def _wrap_login(name, login_method="demo"):
    """登录类接口: 演示学号 → 直接签发会话(不联网); 其它学号走原逻辑"""
    orig = _get_view(name)
    if orig is None:
        return

    def wrapper():
        if _demo_sid_from_request() != DEMO_SID:
            return orig()
        client = _demo_client(DEMO_SID, login_method)
        token = views._register_session(client)
        return _on_login_success(client, token)

    _set_view(name, wrapper)


# 教务直连(自动 OCR / 手动验证码) + 智慧理工(自动 / 手动验证码) 全部支持演示账号
_wrap_login("api_login", "demo")
_wrap_login("api_login_manual", "demo")
_wrap_login("api_login_webvpn", "webvpn")
_wrap_login("api_login_webvpn_manual", "webvpn")

# 智慧理工第一步: 演示账号直接返回"验证码已自动识别, 登录成功"
# (与线上新流程一致: SSO 通过后自动识别教务验证码, 一次点击即登录)
_orig_webvpn_captcha = _get_view("api_get_webvpn_captcha")


def _demo_webvpn_captcha():
    from flask import jsonify
    if _demo_sid_from_request() != DEMO_SID:
        return _orig_webvpn_captcha()
    client = _demo_client(DEMO_SID, "webvpn")
    token = views._register_session(client)
    _on_login_success(client, token)   # 初始化用户学期设置(不重复返回 JSON)
    return jsonify({
        "success": True,
        "already_logged_in": True,
        "token": token,
        "student_id": DEMO_SID,
        "student_name": DEMO_NAME,
        "semester": client._current_semester(),
        "message": "验证码已自动识别，登录成功",
    })


if _orig_webvpn_captcha:
    _set_view("api_get_webvpn_captcha", _demo_webvpn_captcha)

# ---------- 微信扫码登录: 演示账号用假二维码, 不连真实智慧理工 ----------
# 真实二维码 3 分钟失效且需要手机确认, 录制视频时不方便;
# 演示账号改为「假二维码 + 3 次轮询后自动登录」(约 6 秒), 也可点「我已确认」提前完成。
_qr_poll_seen = {}      # demo qr_id -> 已轮询次数
_qr_images = {}         # demo qr_id -> 二维码 PNG 字节(图片直链接口用)

_orig_qr_start = _get_view("api_sso_qr_start")
_orig_qr_status = _get_view("api_sso_qr_status")
_orig_qr_cancel = _get_view("api_sso_qr_cancel")


def _demo_qr_png_bytes() -> bytes:
    """生成一张"看起来像二维码"的演示图(不含真实内容)。"""
    try:
        import random as _random
        from io import BytesIO
        from PIL import Image, ImageDraw

        n, cell, quiet = 25, 12, 2          # 25×25 模块, 每模块 12px, 四周留白 2 模块
        size = (n + quiet * 2) * cell
        img = Image.new("RGB", (size, size), "white")
        d = ImageDraw.Draw(img)
        rnd = _random.Random(20260926)      # 固定种子: 每次生成一致

        def finder(ox, oy):
            """画定位角(7×7 同心方框)"""
            x0, y0 = (ox + quiet) * cell, (oy + quiet) * cell
            d.rectangle([x0, y0, x0 + 7 * cell - 1, y0 + 7 * cell - 1], fill="black")
            d.rectangle([x0 + cell, y0 + cell, x0 + 6 * cell - 1, y0 + 6 * cell - 1],
                        fill="white")
            d.rectangle([x0 + 2 * cell, y0 + 2 * cell, x0 + 5 * cell - 1,
                         y0 + 5 * cell - 1], fill="black")

        finder(0, 0)
        finder(n - 7, 0)
        finder(0, n - 7)
        for y in range(n):
            for x in range(n):
                if (x < 8 and y < 8) or (x >= n - 8 and y < 8) or (x < 8 and y >= n - 8):
                    continue                # 定位角区域跳过
                if rnd.random() < 0.45:
                    x0, y0 = (x + quiet) * cell, (y + quiet) * cell
                    d.rectangle([x0, y0, x0 + cell - 1, y0 + cell - 1], fill="black")
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:                        # noqa: BLE001 Pillow 不可用时给空图
        return b""


def _demo_qr_start():
    from flask import jsonify
    import base64 as _b64
    import secrets as _secrets
    if _demo_sid_from_request() != DEMO_SID:
        return _orig_qr_start()
    qid = "demo-" + _secrets.token_urlsafe(12)
    _qr_poll_seen[qid] = 0
    png = _demo_qr_png_bytes()
    _qr_images[qid] = png
    return jsonify({
        "success": True,
        "qr_id": qid,
        "qr_b64": _b64.b64encode(png).decode() if png else "",
        "expires_in": 180,
        "message": "演示二维码：约 6 秒后自动登录，也可点「我已确认」",
    })


def _demo_qr_status():
    from flask import jsonify, request
    qid = (request.args.get("qr_id") or "").strip()
    if not qid.startswith("demo-"):
        return _orig_qr_status()
    # 第 1 次=未扫, 第 2 次=已扫待确认, 第 3 次起=已确认(≈6 秒)
    n = _qr_poll_seen.get(qid, 0) + 1
    _qr_poll_seen[qid] = n
    if n < 2:
        return jsonify({"success": True, "status": "pending"})
    if n == 2:
        return jsonify({"success": True, "status": "scanned"})
    _qr_poll_seen.pop(qid, None)
    _qr_images.pop(qid, None)
    client = _demo_client(DEMO_SID, "sso-qr")
    token = views._register_session(client)
    _on_login_success(client, token)          # 初始化用户学期设置
    return jsonify({
        "success": True,
        "status": "ok",
        "token": token,
        "student_id": DEMO_SID,
        "student_name": DEMO_NAME,
        "semester": client._current_semester(),
        "login_method": "sso-qr",
        "message": f"登录成功！欢迎 {DEMO_NAME}",
    })


def _demo_qr_cancel():
    from flask import jsonify, request
    data = request.get_json(silent=True) or {}
    _qid = (data.get("qr_id") or "").strip()
    _qr_poll_seen.pop(_qid, None)
    _qr_images.pop(_qid, None)
    return jsonify({"success": True})


_orig_qr_image = _get_view("api_sso_qr_image")


def _demo_qr_image():
    """演示二维码图片直链(小程序 <image src> 用 URL 才能在真机长按识别)。"""
    from flask import Response, jsonify, request
    qid = (request.args.get("qr_id") or "").strip()
    data = _qr_images.get(qid)
    if not data:
        return _orig_qr_image()
    return Response(data, mimetype="image/png",
                    headers={"Cache-Control": "no-store"})


if _orig_qr_start:
    _set_view("api_sso_qr_start", _demo_qr_start)
if _orig_qr_status:
    _set_view("api_sso_qr_status", _demo_qr_status)
if _orig_qr_cancel:
    _set_view("api_sso_qr_cancel", _demo_qr_cancel)
if _orig_qr_image:
    _set_view("api_sso_qr_image", _demo_qr_image)

# 刷新类接口: 演示账号直接返回成功(不清不写, 种子数据永不丢失)
for _name in ("api_refresh_schedule", "api_refresh_exams", "api_refresh_all",
              "api_refresh_grades", "api_refresh_cet", "api_refresh_evaluations"):
    _orig = _get_view(_name)
    if _orig is None:
        continue

    def _make_refresh(orig):
        def wrapper():
            from flask import jsonify
            if _demo_sid() == DEMO_SID:
                return jsonify({"success": True, "message": "演示数据已就绪(素材服务器)", "count": 0})
            return orig()
        return wrapper

    _set_view(_name, _make_refresh(_orig))

# 评教: 课程列表 / 表单 / 提交 → 演示数据
_orig_eval_courses = _get_view("api_eval_courses")
_orig_eval_form = _get_view("api_eval_form")
_orig_submit_eval = _get_view("api_submit_eval")


def _demo_eval_courses():
    from flask import jsonify
    if _demo_sid() != DEMO_SID:
        return _orig_eval_courses()
    return jsonify({
        "success": True,
        "courses": [
            {"name": "高等数学", "eval_url": "/demo/eval/1"},
            {"name": "大学英语", "eval_url": "/demo/eval/2"},
            {"name": "线性代数", "eval_url": "/demo/eval/3"},
        ],
        "hidden_fields": {"cj0701id": "demo"},
    })


def _demo_eval_form():
    from flask import jsonify
    if _demo_sid() != DEMO_SID:
        return _orig_eval_form()
    # 素材规格: 10 个指标, 每个指标 0~10 分 → 满分 100
    labels = ["教学态度", "教学内容", "教学方法", "课堂组织", "语言表达",
              "作业批改", "答疑辅导", "教学效果", "教材选用", "总体评价"]
    indicators = []
    for i in range(1, 11):
        options = [{"value": v, "name": f"pj0601fz_{i}_{j}"}
                   for j, v in enumerate(("10", "9", "8", "7", "6", "5",
                                          "4", "3", "2", "1", "0"))]
        indicators.append({"seq": str(i), "label": labels[i - 1],
                           "options": options})
    return jsonify({
        "success": True,
        "action": "/demo/submit",
        "indicators": indicators,
        "hidden_fields": {"kcmc": "高等数学", "issubmit": "1"},
    })


def _demo_submit_eval():
    from flask import jsonify
    if _demo_sid() != DEMO_SID:
        return _orig_submit_eval()
    return jsonify({"success": True, "message": "评教提交成功(演示)"})


_set_view("api_eval_courses", _demo_eval_courses)
_set_view("api_eval_form", _demo_eval_form)
_set_view("api_submit_eval", _demo_submit_eval)

# 清除缓存: 演示账号不清(避免误清种子数据)
_orig_clear = _get_view("api_clear_data")


def _demo_clear_data():
    from flask import jsonify
    if _demo_sid() != DEMO_SID:
        return _orig_clear()
    return jsonify({"success": True, "message": "演示数据已保留"})


if _orig_clear:
    _set_view("api_clear_data", _demo_clear_data)


if __name__ == "__main__":
    print("=" * 60)
    print("课表助手 · 素材服务器已启动")
    print(f"  地址: http://127.0.0.1:5000")
    print(f"  演示账号: {DEMO_SID}  (密码任意)")
    print(f"  数据库: {DEMO_DB}  (删除后重启可重置种子数据)")
    print("  提示: DevTools 需勾选「不校验合法域名」, 配置 USE_LOCAL=true")
    print("=" * 60)
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
