"""
部署前冒烟测试
==============
使用独立临时 SQLite 库 + Flask test client 验证：
  - 应用导入与建表
  - 全部页面路由
  - 公开 API 与参数校验
  - 未登录保护（401）
  - 数据访问层（课表/考试/成绩/四六级/评教/设置）
  - 关键业务逻辑（课表去重、评教提交参数排序、密码加解密）

用法: python tests/smoke_test.py
"""
import os
import sys

# ── 必须在导入应用前设置: 使用独立临时 SQLite 库, 避免污染 schedule.db ──
_here = os.path.dirname(os.path.abspath(__file__))
_db_path = os.path.join(_here, "smoke_tmp.db").replace("\\", "/")
if os.path.exists(_db_path):
    os.remove(_db_path)
os.environ["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{_db_path}"
os.environ.pop("MYSQL_USERNAME", None)
os.environ.pop("MYSQL_PASSWORD", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wxcloudrun import app, db, dao  # noqa: E402  (导入即触发 db.create_all())

client = app.test_client()

PASS, FAIL, FAILURES = 0, 0, []


def check(name, resp, expect_status):
    global PASS, FAIL
    if resp.status_code == expect_status:
        PASS += 1
        print(f"  [PASS] {name} -> {resp.status_code}")
    else:
        FAIL += 1
        FAILURES.append(name)
        print(f"  [FAIL] {name} -> {resp.status_code} (期望 {expect_status})")


print("== 页面路由 ==")
for path in ["/", "/exams", "/evaluations", "/grades", "/settings", "/gallery"]:
    check(path, client.get(path), 200)

print("== 公开 API (未登录) ==")
check("/api/status", client.get("/api/status"), 200)
check("/api/settings", client.get("/api/settings"), 200)
check("/api/semesters", client.get("/api/semesters"), 200)
check("/api/gallery-images", client.get("/api/gallery-images"), 200)
check("/api/gallery-image?name=南京理工大学26-27年校历.png",
      client.get("/api/gallery-image?name=南京理工大学26-27年校历.png"), 200)
check("/api/gallery-image 路径穿越防护",
      client.get("/api/gallery-image?name=..%2Fconfig.py"), 400)
check("/api/connect-test", client.get("/api/connect-test"), 200)

# 无账号模式: 未登录时不泄露数据库里保存的账号/密码状态
st = client.get("/api/status").get_json()
assert st["logged_in"] is False and st["student_id"] == "" and st["student_name"] == ""
assert st["auto_login_attempted"] is False and st["login_method"] == ""
print("  [PASS] /api/status 未登录: 无账号信息、不触发自动登录")
se = client.get("/api/settings").get_json()
assert se["student_id"] == "" and se["has_password"] is False and se["has_jwc_password"] is False
print("  [PASS] /api/settings 未登录: 不泄露保存的账号/密码状态")

print("== 未登录保护 (期望 401) ==")
for name, path, method in [
    ("refresh-schedule", "/api/refresh-schedule", "post"),
    ("refresh-exams", "/api/refresh-exams", "post"),
    ("refresh-all", "/api/refresh-all", "post"),
    ("refresh-grades", "/api/refresh-grades", "post"),
    ("refresh-cet", "/api/refresh-cet", "post"),
    ("refresh-evaluations", "/api/refresh-evaluations", "post"),
    ("eval-form", "/api/eval-form?url=/njlgdx/xspj/x", "get"),
    ("eval-courses", "/api/eval-courses?url=/njlgdx/xspj/x", "get"),
    ("submit-eval", "/api/submit-eval", "post"),
    ("jw-proxy", "/api/jw-proxy", "post"),
    ("courses", "/api/courses", "get"),
    ("exams", "/api/exams", "get"),
    ("evaluations", "/api/evaluations", "get"),
    ("grades", "/api/grades", "get"),
    ("cet-scores", "/api/cet-scores", "get"),
]:
    resp = client.post(path, json={}) if method == "post" else client.get(path)
    check(name, resp, 401)

# 即使数据库里存有历史凭证，也不会自动登录（无账号模式核心行为）
dao.set_setting("student_id", "99999999")
dao.set_setting("password_enc", "fake-encrypted")
st = client.get("/api/status").get_json()
assert st["logged_in"] is False and st["student_id"] == "", st
print("  [PASS] 库中存有凭证时 /api/status 仍为未登录、不泄露账号")

print("== 参数校验 ==")
check("login 缺参数", client.post("/api/login", json={}), 400)
check("semester 空值", client.post("/api/semester", json={"semester": ""}), 400)
check("eval-form 缺 url", client.get("/api/eval-form"), 400)
check("404 处理", client.get("/no-such-page"), 404)

print("== 数据访问层 ==")

# 设置读写
dao.set_setting("smoke_key", "hello")
assert dao.get_setting("smoke_key") == "hello", "设置写入/读取失败"
dao.set_setting("smoke_key", "")
print("  [PASS] settings 读写")

# 课表 先删后插
dao.save_courses([{
    "name": "高等数学", "teacher": "张三", "classroom": "A101",
    "day": 1, "start": 1, "end": 2, "weeks": "1-16", "week_type": 0,
    "credits": "4.0", "course_type": "必修", "raw": {},
}], "2025-2026-1")
courses = dao.get_courses("2025-2026-1")
assert len(courses) == 1 and courses[0]["name"] == "高等数学", courses
print("  [PASS] courses 存取")

# 考试
dao.save_exams([{
    "course_name": "高等数学", "date": "2026-01-15", "time": "09:00-11:00",
    "location": "一工101", "seat": "12", "type": "期末考试",
}], "2025-2026-1")
exams = dao.get_exams("2025-2026-1")
assert len(exams) == 1 and exams[0]["seat"] == "12", exams
print("  [PASS] exams 存取")

# 成绩
dao.save_grades([{
    "course_name": "高等数学", "score": "95", "credit": 4.0, "grade_point": 4.0,
    "academic_year": "2025-2026", "semester": "1", "course_type": "必修",
    "course_nature": "公共基础", "exam_type": "正常考试",
}], "2025-2026", "1")
grades = dao.get_grades("2025-2026", "1")
assert len(grades) == 1 and grades[0]["course_name"] == "高等数学" and grades[0]["credit"] == 4.0, grades
assert dao.get_grade_semesters() == ["2025-2026-1"], dao.get_grade_semesters()
print("  [PASS] grades 存取与学期列表")

# 四六级 全量替换
dao.save_cet_scores([{"type": "CET4", "score": 550, "exam_date": "2025-06"},
                     {"type": "CET4", "score": 580, "exam_date": "2025-12"},
                     {"type": "CET6", "score": 500, "exam_date": "2025-12"}])
cet = dao.get_cet_scores()
assert len(cet) == 2 and cet[0]["type"] == "CET4" and cet[0]["score"] == 580, cet
print("  [PASS] cet_scores 存取（每种取最高分）")

# 评教批次
dao.save_evaluations([{
    "semester": "2025-2026-1", "category": "理论课", "batch": "第1批",
    "start_date": "2025-12-01", "end_date": "2025-12-31", "is_done": False,
    "items": [{"name": "进入评教", "url": "/njlgdx/xspj/xspj_find.do"}],
}], "2025-2026-1")
evs = dao.get_evaluations("2025-2026-1")
assert len(evs) == 1 and evs[0]["batch"] == "第1批" and evs[0]["is_done"] is False
assert evs[0]["items"][0]["name"] == "进入评教", evs
print("  [PASS] evaluations 存取（含 items JSON）")

# 清除数据
dao.clear_data("2025-2026-1")
assert dao.count_courses("2025-2026-1") == 0 and dao.count_exams("2025-2026-1") == 0
print("  [PASS] clear_data")

print("== 业务逻辑 ==")
from wxcloudrun.jwc_client import JWCClient, _dedupe_schedule_courses  # noqa: E402
from wxcloudrun.views import _build_ordered_eval_post_data, _encode_pwd, _decode_pwd  # noqa: E402

# 课表去重
dup = [
    {"name": "课程设计", "day": 3, "start": 1, "end": 13, "weeks": "1-16",
     "teacher": "A", "classroom": "B"},
    {"name": "课程设计", "day": 3, "start": 1, "end": 13, "weeks": "1-16",
     "teacher": "A", "classroom": "B"},
    {"name": "课程设计", "day": 3, "start": 1, "end": 13, "weeks": "1-16",
     "teacher": "A", "classroom": "B"},
]
assert len(_dedupe_schedule_courses(dup)) == 1, "课表去重失败"
print("  [PASS] 课表跨大节去重")

# 学期计算
j = JWCClient()
sems = j.get_semester_list()
cur = j._current_semester()
assert cur in sems and len(sems) >= 4, (cur, sems)
print(f"  [PASS] 当前学期 {cur} 在学期列表内（共 {len(sems)} 个）")

# 评教提交参数排序（关键: 按浏览器原生顺序重建）
post = _build_ordered_eval_post_data(
    {"pj0601fz_1": "100", "pj0601fz_2": "100", "pj0601id_1": "11", "pj0601id_2": "22",
     "kcmc": "高等数学", "issubmit": "1"},
    auto_fill_selections={"1": ("radio_1", "5"), "_total": 100},
    submit_type="1",
)
keys = [k for k, _ in post]
# 结构: [表单级字段(含radio选择)...] + [pj06xh+指标字段]×N + [issubmit]
assert keys[0] == "kcmc", keys
assert "radio_1" in keys[:3], keys          # 表单级字段(含自动填选的radio)在头部
assert keys[-1] == "issubmit", keys         # issubmit 恒在末尾
assert ("pj06xh", "1") in post and ("pj06xh", "2") in post, post
# 每个指标的 fz/id 紧跟其 pj06xh
i1, i2 = post.index(("pj06xh", "1")), post.index(("pj06xh", "2"))
assert post[i1 + 1] == ("pj0601fz_1", "100") and post[i1 + 2] == ("pj0601id_1", "11"), post
assert post[i2 + 1] == ("pj0601fz_2", "100") and post[i2 + 2] == ("pj0601id_2", "22"), post
print("  [PASS] 评教提交参数排序:", keys)

# 密码加解密
enc = _encode_pwd("s3cret!")
assert _decode_pwd(enc) == "s3cret!", "密码加解密失败"
print("  [PASS] 密码加解密（itsdangerous）")

print()
print(f"结果: {PASS} 通过, {FAIL} 失败")
if FAIL:
    print("失败项:", FAILURES)
    sys.exit(1)
print("冒烟测试全部通过 ✔")
