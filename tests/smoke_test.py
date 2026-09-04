"""
部署前冒烟测试
==============
使用独立临时 SQLite 库 + Flask test client 验证：
  - 应用导入与建表
  - 全部页面路由
  - 公开 API 与参数校验
  - 未登录保护（401）
  - 数据访问层（课表/考试/成绩/四六级/评教/设置）
  - 关键业务逻辑（课表去重、评教提交参数排序）

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
# 用户池上限调小, 便于测试淘汰逻辑
os.environ["MAX_SESSIONS"] = "3"

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

# 公告公开接口: 返回 enabled/text/updated(小程序端按 updated 判断新公告)
ann = client.get("/api/announcement").get_json()
assert ann["success"] is True and set(("enabled", "text", "updated")) <= set(ann), ann
print("  [PASS] /api/announcement 公开接口(含 updated)")

# 无账号模式: 未登录时不泄露数据库里保存的账号/密码状态
st = client.get("/api/status").get_json()
assert st["logged_in"] is False and st["student_id"] == "" and st["student_name"] == ""
assert st["auto_login_attempted"] is False and st["login_method"] == ""
print("  [PASS] /api/status 未登录: 无账号信息、不触发自动登录")
se = client.get("/api/settings").get_json()
assert se["student_id"] == "" and se["student_name"] == ""
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
    ("clear-data", "/api/clear-data", "post"),
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
}], "2025-2026-1", "10001")
courses = dao.get_courses("2025-2026-1", "10001")
assert len(courses) == 1 and courses[0]["name"] == "高等数学", courses
print("  [PASS] courses 存取")

# 考试
dao.save_exams([{
    "course_name": "高等数学", "date": "2026-01-15", "time": "09:00-11:00",
    "location": "一工101", "seat": "12", "type": "期末考试",
}], "2025-2026-1", "10001")
exams = dao.get_exams("2025-2026-1", "10001")
assert len(exams) == 1 and exams[0]["seat"] == "12", exams
print("  [PASS] exams 存取")

# 成绩
dao.save_grades([{
    "course_name": "高等数学", "score": "95", "credit": 4.0, "grade_point": 4.0,
    "academic_year": "2025-2026", "semester": "1", "course_type": "必修",
    "course_nature": "公共基础", "exam_type": "正常考试",
}], "2025-2026", "1", "10001")
grades = dao.get_grades("2025-2026", "1", "10001")
assert len(grades) == 1 and grades[0]["course_name"] == "高等数学" and grades[0]["credit"] == 4.0, grades
assert dao.get_grade_semesters("10001") == ["2025-2026-1"], dao.get_grade_semesters()
print("  [PASS] grades 存取与学期列表")

# 四六级 全量替换
dao.save_cet_scores([{"type": "CET4", "score": 550, "exam_date": "2025-06"},
                     {"type": "CET4", "score": 580, "exam_date": "2025-12"},
                     {"type": "CET6", "score": 500, "exam_date": "2025-12"}], "10001")
cet = dao.get_cet_scores("10001")
assert len(cet) == 2 and cet[0]["type"] == "CET4" and cet[0]["score"] == 580, cet
print("  [PASS] cet_scores 存取（每种取最高分）")

# 评教批次
dao.save_evaluations([{
    "semester": "2025-2026-1", "category": "理论课", "batch": "第1批",
    "start_date": "2025-12-01", "end_date": "2025-12-31", "is_done": False,
    "items": [{"name": "进入评教", "url": "/njlgdx/xspj/xspj_find.do"}],
}], "2025-2026-1", "10001")
evs = dao.get_evaluations("2025-2026-1", "10001")
assert len(evs) == 1 and evs[0]["batch"] == "第1批" and evs[0]["is_done"] is False
assert evs[0]["items"][0]["name"] == "进入评教", evs
print("  [PASS] evaluations 存取（含 items JSON）")

# 多用户数据隔离: 用户 10002 看不到用户 10001 的任何数据
assert dao.get_courses("2025-2026-1", "10002") == []
assert dao.get_exams("2025-2026-1", "10002") == []
assert dao.get_grades(student_id="10002") == []
assert dao.get_cet_scores("10002") == []
assert dao.get_evaluations("2025-2026-1", "10002") == []
assert dao.get_grade_semesters("10002") == []
print("  [PASS] 多用户数据隔离（10001/10002 互不可见）")

# 清除数据
dao.clear_data("2025-2026-1", "10001")
assert dao.count_courses("2025-2026-1", "10001") == 0 \
    and dao.count_exams("2025-2026-1", "10001") == 0
print("  [PASS] clear_data")

print("== 业务逻辑 ==")
from wxcloudrun.jwc_client import JWCClient, _dedupe_schedule_courses  # noqa: E402
from wxcloudrun.views import _build_ordered_eval_post_data  # noqa: E402

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

print("== 多用户会话（token） ==")
from wxcloudrun import views  # noqa: E402

# 模拟两个已登录用户（跳过真实教务探测）
c1 = JWCClient()
c1.logged_in = True
c1.student_id = "10001"
c1.student_name = "测试甲"
c1.is_session_valid = lambda: True
c2 = JWCClient()
c2.logged_in = True
c2.student_id = "10002"
c2.student_name = "测试乙"
c2.is_session_valid = lambda: True
token1 = views._register_session(c1)
token2 = views._register_session(c2)
h1 = {"X-Auth-Token": token1}
h2 = {"X-Auth-Token": token2}

# token 会话可访问数据接口；无 token 仍 401
r1 = client.get("/api/courses", headers=h1)
assert r1.status_code == 200 and r1.get_json()["courses"] == [], r1.status_code
check("带 token 访问 /api/courses", r1, 200)
st = client.get("/api/status", headers=h1).get_json()
assert st["logged_in"] is True and st["student_id"] == "10001", st
print("  [PASS] /api/status 返回 token 对应用户")

# 用户1 写入课表 → 用户1 可见，用户2 不可见
dao.save_courses([{
    "name": "甲的专业课", "teacher": "T1", "classroom": "A101",
    "day": 1, "start": 1, "end": 2, "weeks": "1-16", "week_type": 0,
    "credits": "2.0", "course_type": "必修", "raw": {},
}], "2025-2026-1", "10001")
r1 = client.get("/api/courses?semester=2025-2026-1", headers=h1).get_json()
r2 = client.get("/api/courses?semester=2025-2026-1", headers=h2).get_json()
assert len(r1["courses"]) == 1 and r1["courses"][0]["name"] == "甲的专业课", r1
assert r2["courses"] == [], r2
print("  [PASS] API 层数据隔离：用户1 的课表用户2 看不到")

# 学期按用户独立
client.post("/api/semester", json={"semester": "2026-2027-1"}, headers=h1)
client.post("/api/semester", json={"semester": "2025-2026-2"}, headers=h2)
assert dao.get_user_setting("10001", "semester") == "2026-2027-1"
assert dao.get_user_setting("10002", "semester") == "2025-2026-2"
print("  [PASS] 学期设置按用户隔离")

# 退出登录：token 失效
r = client.post("/api/logout", headers=h1)
assert r.status_code == 200
st = client.get("/api/status", headers=h1).get_json()
assert st["logged_in"] is False, st
r = client.get("/api/courses", headers=h1)
assert r.status_code == 401
print("  [PASS] 退出登录后 token 失效（401）")

print("== 空教室网格解析(离线, 教务结构回归) ==")


def _grid_html(day_rows):
    """构造教室课表网格 HTML(单大节形态): day_rows=[(教室名, 周一..周日占用 bool)]"""
    head = "<table><tr><td></td>" + \
        "".join(f"<td>{d}</td>" for d in ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]) + "</tr>"
    head += "<tr><td>教室\\节次</td>" + "<td>0607</td>" * 7 + "</tr>"
    body = ""
    for name, occ in day_rows:
        cells = [f"<td>{name}</td>"] + \
            [("<td>课程 教师 (1-3周)</td>" if o else "<td>&nbsp;</td>") for o in occ]
        body += "<tr>" + "".join(cells) + "</tr>"
    return head + body + "</table>"


_grid = _grid_html([
    ("Ⅳ-A411", [0, 0, 0, 0, 0, 0, 0]),
    ("Ⅳ-C201", [1, 0, 0, 0, 0, 0, 0]),
    ("Ⅳ-B505", [0, 0, 1, 0, 0, 0, 0]),
    ("Ⅳ-A308", [1, 1, 1, 1, 1, 0, 0]),
])
free1 = JWCClient.parse_free_classroom_grid(_grid, 1, "0607")
assert free1 == ["Ⅳ-A411", "Ⅳ-B505"], free1
free3 = JWCClient.parse_free_classroom_grid(_grid, 3, "0607")
assert free3 == ["Ⅳ-A411", "Ⅳ-C201"], free3
free7 = JWCClient.parse_free_classroom_grid(_grid, 7, "0607")
assert free7 == ["Ⅳ-A411", "Ⅳ-C201", "Ⅳ-B505", "Ⅳ-A308"], free7
print("  [PASS] 空教室网格解析(单大节形态, 空格=空闲)")

# 全天多列形态: 星期列 colspan=5, 每列一个官方大节码
_g5 = ["010203", "0405", "0607", "080910", "111213"]
_head2 = "<tr><td></td>" + "".join(f'<td colspan="5">{d}</td>' for d in ["星期一", "星期二"]) + "</tr>"
_head2 += "<tr><td>教室\\节次</td>" + "".join(f"<td>{c}</td>" for _ in range(2) for c in _g5) + "</tr>"
_rows2 = [
    "<tr><td>Ⅳ-A101</td>" + "<td></td>" * 10 + "</tr>",
    # Ⅳ-A102 周一第 3 大节(0607)被占: 教室名列后第 3 个格
    "<tr><td>Ⅳ-A102</td>" + "<td></td>" * 2 + "<td>占</td>" + "<td></td>" * 7 + "</tr>",
]
_grid2 = "<table>" + _head2 + "".join(_rows2) + "</table>"
free_m1 = JWCClient.parse_free_classroom_grid(_grid2, 1, "0607")
assert free_m1 == ["Ⅳ-A101"], free_m1
free_t2 = JWCClient.parse_free_classroom_grid(_grid2, 2, "111213")
assert free_t2 == ["Ⅳ-A101", "Ⅳ-A102"], free_t2
print("  [PASS] 空教室网格解析(全天多列 colspan 形态)")

# 时间段范围(expect_code=None): 该星期全部列均空闲才算(任一组被占即排除)
free_m1_all = JWCClient.parse_free_classroom_grid(_grid2, 1, None)
assert free_m1_all == ["Ⅳ-A101"], free_m1_all    # A102 周一 0607 列被占 → 排除
free_t2_all = JWCClient.parse_free_classroom_grid(_grid2, 2, None)
assert free_t2_all == ["Ⅳ-A101", "Ⅳ-A102"], free_t2_all
print("  [PASS] 空教室网格解析(时间段范围: 全列空闲才算)")

# 教学楼联动接口解析: 数组 / data 包装 / 空与异常输入
b1 = JWCClient.parse_classroom_buildings(
    '[{"dm":"1","dmmc":"Ⅰ教学楼"},{"dm":"GUID","dmmc":"体育中心"}]')
assert b1 == [{"code": "1", "name": "Ⅰ教学楼"}, {"code": "GUID", "name": "体育中心"}], b1
b2 = JWCClient.parse_classroom_buildings('{"data":[{"dm":"4y","dmmc":"江阴"}]}')
assert b2 == [{"code": "4y", "name": "江阴"}], b2
assert JWCClient.parse_classroom_buildings("not json") == []
assert JWCClient.parse_classroom_buildings("") == []
print("  [PASS] 教学楼列表解析(数组/data 包装/异常输入)")

# 定时预热计划(上下课时刻): 5 个官方大节按时间升序; 下一刷新时刻跨天正确
from datetime import datetime as _dt  # noqa: E402
from wxcloudrun.views import freeclass_refresh_plan, _next_freeclass_refresh  # noqa: E402
_plan = freeclass_refresh_plan()
assert len(_plan) == 5 and _plan[0][1] == "1-3" and _plan[-1][1] == "11-13", _plan
assert [t for t, _ in _plan] == sorted(t for t, _ in _plan)
_nxt, _slot = _next_freeclass_refresh(_dt(2026, 9, 1, 8, 30))   # 08:30 → 10:10 第二大节
assert _nxt.hour == 10 and _nxt.minute == 10 and _slot == "4-5", (_nxt, _slot)
_nxt2, _slot2 = _next_freeclass_refresh(_dt(2026, 9, 1, 23, 0))  # 23:00 → 次日 08:00
assert _nxt2.day == 2 and _nxt2.hour == 8 and _slot2 == "1-3", (_nxt2, _slot2)
print("  [PASS] 空教室定时预热计划(上下课时刻/跨天)")

# 响应兼容性: 旧版前端依赖 slot_name/slot; 新版用 time_text/jc1/jc2/updated_at
from wxcloudrun.views import _freeclass_resp  # noqa: E402
_resp = _freeclass_resp("孝陵卫", 3, 1, 5, 2, "2026-2027-1", {"rooms": ["Ⅳ-A101"], "buildings": []})
assert _resp["slot_name"] == _resp["time_text"] == "第1-5节", _resp
assert "slot" in _resp and "jc1" in _resp and "updated_at" in _resp
assert _resp["count"] == 1 and _resp["rooms"] == ["Ⅳ-A101"]
print("  [PASS] 空教室响应兼容字段(slot_name/time_text/jc1/jc2/updated_at)")

print("== 管理端仪表盘与反馈(留言板已下线) ==")
import time as _time  # noqa: E402
from wxcloudrun import admin as admin_mod  # noqa: E402
admin_mod._admin_token = ("dash-test-token", _time.time() + 3600)
ah = {"X-Admin-Token": "dash-test-token"}

# 仪表盘重聚合端点: 回归防护(历史 bug: 误删 func 导入导致 500; 缓存二次命中)
check("admin 未授权 401", client.get("/api/admin/summary"), 401)
for path in ("/api/admin/summary", "/api/admin/users", "/api/admin/stats/grades",
             "/api/admin/requests", "/api/admin/sessions"):
    r = client.get(path, headers=ah)
    assert r.status_code == 200 and r.get_json()["success"], (path, r.status_code)
r = client.get("/api/admin/summary?refresh=1", headers=ah)
assert r.status_code == 200 and r.get_json()["success"], r.status_code
print("  [PASS] 管理端仪表盘端点(含缓存与强制刷新)")

# 留言板功能已下线: 相关路由应 404(小程序/管理端均不再提供)
check("留言板路由已下线 404", client.get("/api/board", headers=ah), 404)
check("留言板管理端路由已下线 404", client.get("/api/admin/board", headers=ah), 404)
check("admin/stream 已移除(改轮询) 404", client.get("/api/admin/stream", headers=ah), 404)
print("  [PASS] 留言板/SSE 路由已下线")

# 问题反馈(仅存的社区渠道): 提交/敏感词/管理端可见
_fc = JWCClient()
_fc.logged_in = True
_fc.student_id = "10001"
_fc.student_name = "回归甲"
_fc.is_session_valid = lambda: True
_ft = views._register_session(_fc)
_fh = {"X-Auth-Token": _ft}
check("/api/feedback 未登录 401", client.post("/api/feedback", json={"content": "x"}), 401)
r = client.post("/api/feedback", json={"type": "bug", "content": "仪表盘回归测试反馈"}, headers=_fh)
assert r.status_code == 200 and r.get_json()["success"], r.status_code
check("反馈-敏感词 400", client.post("/api/feedback", json={"content": "代考找我"}, headers=_fh), 400)
r = client.get("/api/admin/feedback", headers=ah).get_json()
assert any(f["content"] == "仪表盘回归测试反馈" for f in r["feedback"]), r
print("  [PASS] 问题反馈提交/敏感词过滤/管理端可见")

print("== 会话池维护 ==")
import time  # noqa: E402

# 用户池上限: 注册超过 MAX_SESSIONS(=3) 的会话, 最久未活动者被淘汰
for i in range(5):
    c = JWCClient()
    c.logged_in = True
    c.student_id = f"pool{i}"
    c.is_session_valid = lambda: True
    views._register_session(c)
assert len(views._sessions) <= 3, f"用户池超限: {len(views._sessions)}"
print(f"  [PASS] 用户池上限淘汰（当前 {len(views._sessions)}/3）")

# 验证码临时会话 TTL 清理
cid, _ = views._new_captcha_client()
views._captcha_clients[cid][1] = time.time() - 9999  # 模拟 10 分钟前创建
views._prune_captcha_locked()
assert cid not in views._captcha_clients, "过期验证码会话未清理"
print("  [PASS] 验证码临时会话 TTL 清理")

print()
print(f"结果: {PASS} 通过, {FAIL} 失败")
if FAIL:
    print("失败项:", FAILURES)
    sys.exit(1)
print("冒烟测试全部通过 [OK]")
