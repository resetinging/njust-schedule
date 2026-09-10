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

DEMO_SID = "20260001"
DEMO_NAME = "南理工同学"


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
        dict(name="概率论与数理统计", teacher="吴敏", classroom="Ⅳ-B411", day=5, start=4, end=5,
             weeks="1-20", week_type=0, credits="3.0", course_type="必修", raw={}),
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

_orig_login = app.view_functions.get("api_login")


def _demo_login():
    from flask import request
    data = request.get_json(silent=True) or {}
    sid = (data.get("student_id") or "").strip()
    if sid != DEMO_SID:
        return _orig_login()
    _seed(sid)
    client = JWCClient()
    client.logged_in = True
    client.student_id = sid
    client.student_name = DEMO_NAME
    client.login_method = "demo"
    client.is_session_valid = lambda: True
    token = views._register_session(client)
    return views._on_login_success(client, token)


app.view_functions["api_login"] = _demo_login

# 刷新类接口: 演示账号直接返回成功(不清不写, 种子数据永不丢失)
for _name in ("api_refresh_schedule", "api_refresh_exams", "api_refresh_all",
              "api_refresh_grades", "api_refresh_cet", "api_refresh_evaluations"):
    _orig = app.view_functions.get(_name)
    if _orig is None:
        continue

    def _make_refresh(orig):
        def wrapper():
            from flask import jsonify
            if _demo_sid() == DEMO_SID:
                return jsonify({"success": True, "message": "演示数据已就绪(素材服务器)", "count": 0})
            return orig()
        return wrapper

    app.view_functions[_name] = _make_refresh(_orig)

# 评教: 课程列表 / 表单 / 提交 → 演示数据
_orig_eval_courses = app.view_functions.get("api_eval_courses")
_orig_eval_form = app.view_functions.get("api_eval_form")
_orig_submit_eval = app.view_functions.get("api_submit_eval")


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
    indicators = []
    for i in range(1, 7):
        options = [{"value": v, "name": f"pj0601fz_{i}_{j}"}
                   for j, v in enumerate(("100", "90", "80", "70", "60"))]
        indicators.append({"seq": str(i), "options": options})
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


app.view_functions["api_eval_courses"] = _demo_eval_courses
app.view_functions["api_eval_form"] = _demo_eval_form
app.view_functions["api_submit_eval"] = _demo_submit_eval

# 清除缓存: 演示账号不清(避免误清种子数据)
_orig_clear = app.view_functions.get("api_clear_data")


def _demo_clear_data():
    from flask import jsonify
    if _demo_sid() != DEMO_SID:
        return _orig_clear()
    return jsonify({"success": True, "message": "演示数据已保留"})


if _orig_clear:
    app.view_functions["api_clear_data"] = _demo_clear_data


if __name__ == "__main__":
    print("=" * 60)
    print("课表助手 · 素材服务器已启动")
    print(f"  地址: http://127.0.0.1:5000")
    print(f"  演示账号: {DEMO_SID}  (密码任意)")
    print(f"  数据库: {DEMO_DB}  (删除后重启可重置种子数据)")
    print("  提示: DevTools 需勾选「不校验合法域名」, 配置 USE_LOCAL=true")
    print("=" * 60)
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
