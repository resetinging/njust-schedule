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
import base64

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
# 凭据存储/退出删除依赖 SESSION_KEY(测试用固定 32 字节密钥, 非生产值)
os.environ["SESSION_KEY"] = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wxcloudrun import app, db, dao  # noqa: E402  (导入即触发 db.create_all())

_APP_CTX = app.app_context()
_APP_CTX.push()

client = app.test_client()

from wxcloudrun.model import SchemaMigration  # noqa: E402
assert SchemaMigration.query.count() >= 5, "Schema migration registry missing"

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
# 公开网页端已下线: 根路径 302 跳管理面板, 旧的五个页面路由已删除
check("/ -> /admin", client.get("/"), 302)
for path in ["/exams", "/evaluations", "/grades", "/settings", "/gallery"]:
    check(path + " 已下线", client.get(path), 404)

print("== 公开 API (未登录) ==")
check("/api/status", client.get("/api/status"), 200)
check("/api/prefetch-status 未登录 401", client.get("/api/prefetch-status"), 401)
check("/api/settings", client.get("/api/settings"), 200)
check("/api/semesters", client.get("/api/semesters"), 200)
check("/api/gallery-images", client.get("/api/gallery-images"), 200)
check("/api/gallery-image?name=26-27年校历.png",
      client.get("/api/gallery-image?name=26-27年校历.png"), 200)
check("/api/gallery-image 路径穿越防护",
      client.get("/api/gallery-image?name=..%2Fconfig.py"), 400)
check("/api/connect-test", client.get("/api/connect-test"), 200)
check("/healthz", client.get("/healthz"), 200)
check("/readyz", client.get("/readyz"), 200)
_metrics = client.get("/metrics")
assert _metrics.status_code == 200
assert "njust_http_requests_total" in _metrics.get_data(as_text=True)
print("  [PASS] 健康探针与 Prometheus 指标可用")
check("/api/sso-qr/status 未知 qr_id", client.get("/api/sso-qr/status?qr_id=x"), 400)
check("/api/sso-qr/cancel", client.post("/api/sso-qr/cancel", json={}), 200)

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
check("login-webvpn 畸形 JSON",
      client.post("/api/login-webvpn", data="{bad", content_type="application/json"), 400)
check("未登录禁止写全局设置",
      client.post("/api/settings", json={"first_week_date": "2000-01-01"}), 401)
check("未登录禁止切换全局学期",
      client.post("/api/semester", json={"semester": ""}), 401)
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
ps = client.get("/api/prefetch-status", headers=h1)
check("/api/prefetch-status 登录后 200", ps, 200)
assert ps.get_json().get("data_refresh", {}).get("state") == "idle", ps.get_json()
print("  [PASS] /api/status 返回 token 对应用户")

for _bad_url in (
    "http://169.254.169.254/latest/meta-data",
    "//evil.example/path",
    "/njlgdx/../../etc/passwd",
    "/other/path",
):
    r = client.get("/api/eval-courses",
                   query_string={"url": _bad_url}, headers=h1)
    assert r.status_code == 400, (_bad_url, r.status_code, r.get_json())
r = client.post("/api/submit-eval",
                json={"form_data": {},
                      "action": "http://169.254.169.254/latest/meta-data"},
                headers=h1)
assert r.status_code == 400, r.get_json()
r = client.post("/api/jw-proxy",
                json={"method": "GET", "path": "http://evil.example"},
                headers=h1)
assert r.status_code == 400, r.get_json()
print("  [PASS] 评教/代理 URL 白名单阻止 SSRF 与路径穿越")

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
check("semester 空值", client.post(
    "/api/semester", json={"semester": ""}, headers=h1), 400)
assert dao.get_user_setting("10001", "semester") == "2026-2027-1"
assert dao.get_user_setting("10002", "semester") == "2025-2026-2"
print("  [PASS] 学期设置按用户隔离")

_global_first_week = dao.get_setting("first_week_date", "")
r = client.post("/api/settings",
                json={"first_week_date": "2026-08-24",
                      "auto_refresh": "true"},
                headers=h1)
assert r.status_code == 200 and r.get_json()["success"], r.get_json()
assert dao.get_user_setting(
    "10001", "first_week_date:2026-2027-1") == "2026-08-24"
assert dao.get_user_setting("10001", "auto_refresh") == "true"
assert dao.get_setting("first_week_date", "") == _global_first_week
print("  [PASS] 设置写入按用户隔离, 不污染全局配置")

# 旧库 {sid}:{key} 行迁移到 user_settings, 全局 settings 不再承载用户命名空间
dao.set_setting("legacy-user:semester", "2024-2025-1")
import wxcloudrun as _wxcloudrun  # noqa: E402
_wxcloudrun._migrate_user_settings()
assert dao.get_user_setting("legacy-user", "semester") == "2024-2025-1"
assert dao.get_setting("legacy-user:semester", "") == ""
print("  [PASS] 旧用户设置已迁移到 user_settings 表")

# 退出登录：token 失效
r = client.post("/api/logout", headers=h1)
assert r.status_code == 200
st = client.get("/api/status", headers=h1).get_json()
assert st["logged_in"] is False, st
r = client.get("/api/courses", headers=h1)
assert r.status_code == 401
print("  [PASS] 退出登录后 token 失效（401）")

print("== 空教室查询解析(离线, 借用页结构回归) ==")

from wxcloudrun.jwc_client import ClassroomBorrowError  # noqa: E402


def _borrow_html(rows):
    """构造 jsjy_query2 结果页(教务实测形态): form + table#dataList + jsids 行"""
    trs = ('<tr><th>星期</th><th>星期三</th></tr>'
           '<tr><td></td><td id="jc2" tdvalue="0607">第三大节</td></tr>')
    for name in rows:
        trs += ('<tr><td><input type="checkbox" name="jsids" value="x" /> %s</td>'
                '<td></td></tr>' % name)
    return ('<html><body><form action="/njlgdx/jspyfa/selectJx02" id="Form1" '
            'name="Form1" method="post"><input type="hidden" name="jszt" value="5" />'
            '<table id="dataList" class="Nsb_table">%s</table>'
            '</form></body></html>' % trs)


_rooms = JWCClient.parse_borrow_free_list(_borrow_html([
    "Ⅳ-A312(60/0)", "II-101(187/60)", "345-101(40/0)", "江阴致源B331(80/0)",
    "347-1(150/75)", "99-107(40/40)", "384栋405(100/0)", "线上(1/0)", "其它教室(1/0)",
]))
assert _rooms == ["Ⅳ教学楼-A312", "Ⅱ教学楼-101",
                  "东区平房-101", "致源楼B331"], _rooms
print("  [PASS] 借用页清单解析: 去容量后缀 + 楼名映射 + 未映射/非实体过滤")

assert JWCClient.parse_borrow_free_list(_borrow_html([])) == []
print("  [PASS] 借用页空清单(无 jsids 行) = 0 间, 不当作解析失败")


def _borrow_html_multi(rows):
    """跨大节响应形态: 每行 = 教室 + N 个状态列(空/"空闲"=空闲, 其他=占用)"""
    trs = ('<tr><th>星期</th><th>星期三</th></tr>'
           '<tr><td></td><td>第一大节</td><td>第二大节</td></tr>')
    for name, marks in rows:
        trs += ('<tr><td><input type="checkbox" name="jsids" value="x" /> %s</td>%s</tr>'
                % (name, ''.join('<td>%s</td>' % m for m in marks)))
    return ('<html><body><form action="/njlgdx/jspyfa/selectJx02" id="Form1" '
            'name="Form1" method="post"><table id="dataList">%s</table>'
            '</form></body></html>' % trs)


_multi = JWCClient.parse_borrow_free_list(_borrow_html_multi([
    ("Ⅳ-A101(60/0)", ["", ""]),        # 两个大节都空闲 → 保留
    ("Ⅳ-A102(60/0)", ["◆", ""]),       # 仅第二大节空闲 → 排除
    ("Ⅰ-201(60/0)", ["空闲", "空闲"]),   # 字面"空闲" → 保留
]))
assert _multi == ["Ⅳ教学楼-A101", "Ⅰ教学楼-201"], _multi
print("  [PASS] 跨大节时段: 所有大节均空闲才保留(并集响应按交集过滤)")

# 请求契约: get_free_classrooms 按借用页表单字段提交(规则八: 不猜字段名)
_contract = {}
_c = JWCClient()
_c._borrow_page_opts = lambda force=False: {
    "ts": 0, "sem_vals": ["2026-2027-1"], "cur_sem": "2026-2027-1",
    "xq_map": {"孝陵卫": "01"}, "action": "/njlgdx/kbxx/jsjy_query2"}


class _BorrowResp:
    url = "http://202.119.81.112:9080/njlgdx/kbxx/jsjy_query2"
    text = _borrow_html(["345-101(40/0)"])


def _fake_post(url, data=None, **kw):
    _contract["url"] = url
    _contract["data"] = data
    return _BorrowResp()


_c.session.post = _fake_post
_c._is_jw_login_page = lambda resp: False
_rooms2 = _c.get_free_classrooms(campus="孝陵卫", weekday=3, jc1=6, jc2=7,
                                 week=3, semester="2026-2027-1")
assert _rooms2.get("rooms") == ["东区平房-101"], _rooms2
assert _contract["data"] == {
    "typewhere": "jszq", "xnxqh": "2026-2027-1", "xqbh": "01",
    "jxqbh": "", "jxlbh": "", "jsbh": "", "bjfh": "=", "rnrs": "",
    "jszt": "5", "zc": "3", "zc2": "3", "xq": "3", "xq2": "3",
    "jc": "06", "jc2": "07"}, _contract["data"]
assert _contract["url"].endswith("/njlgdx/kbxx/jsjy_query2")
print("  [PASS] 请求契约: 表单字段名/取值/节次补零 与借用页实测一致")

for _name, _bad in [
    ("空响应", ""),
    ("错误页", "<html><body>非法访问！</body></html>"),
    ("只有表格无表单", '<table id="dataList"><tr><td>1</td></tr></table>'),
]:
    try:
        JWCClient.parse_borrow_free_list(_bad)
        raise AssertionError(f"{_name}: 应抛 ClassroomBorrowError")
    except ClassroomBorrowError:
        pass
print("  [PASS] 借用页结构异常抛 ClassroomBorrowError(不与'没有空闲教室'混淆)")

# 定时预热计划(上下课时刻): 5 个官方大节按时间升序; 下一刷新时刻跨天正确
from datetime import datetime as _dt  # noqa: E402
from wxcloudrun.views import (  # noqa: E402
    freeclass_refresh_plan, _next_freeclass_refresh, _freeclass_ttl)
_plan = freeclass_refresh_plan()
assert len(_plan) == 5 and _plan[0][1] == "1-3" and _plan[-1][1] == "11-13", _plan
assert [t for t, _ in _plan] == sorted(t for t, _ in _plan)
_nxt, _slot = _next_freeclass_refresh(_dt(2026, 9, 1, 8, 30))   # 08:30 → 10:10
assert _nxt.hour == 10 and _nxt.minute == 10 and _slot == "4-5", (_nxt, _slot)
_nxt2, _slot2 = _next_freeclass_refresh(_dt(2026, 9, 1, 23, 0))  # 23:00 → 次日 08:00
assert _nxt2.day == 2 and _nxt2.hour == 8 and _slot2 == "1-3", (_nxt2, _slot2)
# 缓存 TTL: 到下一个自然日 00:00 + 120s 缓冲
assert _freeclass_ttl(_dt(2026, 9, 1, 8, 30)) == 15 * 3600 + 30 * 60 + 120
assert _freeclass_ttl(_dt(2026, 9, 1, 23, 0)) == 1 * 3600 + 120
print("  [PASS] 预热计划(上下课时刻/跨天) + 每日零点缓存 TTL")

# 响应兼容性: 旧版前端依赖 slot_name/slot; 新版用 time_text/jc1/jc2/updated_at
from wxcloudrun.views import _freeclass_resp  # noqa: E402
_resp = _freeclass_resp("孝陵卫", 3, 1, 5, 2, "2026-2027-1",
                        {"rooms": ["东区平房-101"], "buildings": []})
assert _resp["slot_name"] == _resp["time_text"] == "第1-5节", _resp
assert "slot" in _resp and "jc1" in _resp and "updated_at" in _resp
assert _resp["count"] == 1 and _resp["rooms"] == ["东区平房-101"]
print("  [PASS] 空教室响应兼容字段(slot_name/time_text/jc1/jc2/updated_at)")

# 服务账号密码必须加密落库; 旧明文记录首次读取时自动升级为密文
from wxcloudrun.api import freeclass as _freeclass_api  # noqa: E402
assert _freeclass_api.set_service_password("FreeClass@Test")
_service_blob = dao.get_setting("free_classroom_pwd", "")
assert _service_blob.startswith("enc:v1:")
assert "FreeClass@Test" not in _service_blob
assert _freeclass_api._read_service_password() == "FreeClass@Test"
dao.set_setting("free_classroom_pwd", "LegacyPlain@Test")
assert _freeclass_api._read_service_password() == "LegacyPlain@Test"
_upgraded_blob = dao.get_setting("free_classroom_pwd", "")
assert _upgraded_blob.startswith("enc:v1:")
assert "LegacyPlain@Test" not in _upgraded_blob
print("  [PASS] 空教室服务账号密码加密落库并自动迁移旧明文")

# 时区: 教学周按传入日期计算(修复前用 date.today(), 容器 UTC 时会偏一天)
from wxcloudrun.views import (  # noqa: E402
    _beijing_date, _current_teaching_week, _prewarm_targets)
from datetime import date as _d  # noqa: E402

assert _current_teaching_week("2026-09-07", on=_d(2026, 9, 7)) == 1
assert _current_teaching_week("2026-09-07", on=_d(2026, 9, 13)) == 1     # 周日仍属第1周
assert _current_teaching_week("2026-09-07", on=_d(2026, 9, 14)) == 2     # 周一进入第2周
assert _current_teaching_week("", on=_d(2026, 9, 14)) == 1               # 无设置回退 1
assert isinstance(_beijing_date(), _d)
# 默认只预热今天; 明天首次查询时按需抓取并缓存, 避免后台重复访问教务
_tg = [(x[1], x[2]) for x in _prewarm_targets("2026-09-07", today=_d(2026, 9, 13))]
assert _tg == [(7, 1)], _tg
print("  [PASS] 时区: 教学周按给定日期算 + 默认只预热今天")

print("== 管理端仪表盘与反馈(留言板已下线) ==")
from wxcloudrun import admin as admin_mod  # noqa: E402

# 真实登录链路: 密码校验 → 签发无状态 token → /api/admin/check 认可
check("admin 登录密码错误 401",
      client.post("/api/admin/login", json={"password": admin_mod.ADMIN_PASSWORD + "-wrong"}), 401)
_lr = client.post("/api/admin/login", json={"password": admin_mod.ADMIN_PASSWORD})
check("admin 登录成功签发 token", _lr, 200)
assert _lr.get_json().get("token"), _lr.get_json()
_cr = client.get("/api/admin/check", headers={"X-Admin-Token": _lr.get_json()["token"]})
check("登录 token 通过 /api/admin/check", _cr, 200)
assert _cr.get_json().get("logged_in") is True, _cr.get_json()

_admin_tok = admin_mod._issue_admin_token(ttl=3600)
ah = {"X-Admin-Token": _admin_tok}

# 管理员明文凭据查询已下线
from wxcloudrun.core import credential_store as _cred  # noqa: E402
check("管理员明文凭据查询已下线 404",
      client.post("/api/admin/credentials/reveal", json={"student_id": "10002"}, headers=ah), 404)
# 默认保存密码: 密码校验走本地专用比较, 24 小时信任期由 credential_store 管理
from wxcloudrun.api import auth as _auth  # noqa: E402
assert _cred.save("10002", "Keep@1234") is True
assert _cred.verify("10002", "Keep@1234") is True
assert _cred.can_resume("10002", "Keep@1234") is True
assert _cred.can_resume("10002", "Wrong@1234") is False
print("  [PASS] 默认保存密码 + 本地信任校验")
assert _cred.save("10005", "Revoke@1234") is True
_dt = _cred.issue_delete_token("10005")
check("仅凭删除 token 也可撤销凭据",
      client.delete("/api/credentials", headers={"X-Credential-Delete-Token": _dt}), 200)
assert _cred.resolve("10005") is None, "删除 token 未撤销服务端凭据"
_bad_dt = _dt[:-1] + ("A" if _dt[-1] != "A" else "B")
check("篡改删除 token 被拒绝",
      client.delete("/api/credentials", headers={"X-Credential-Delete-Token": _bad_dt}), 401)
print("  [PASS] 删除 token 不依赖教务会话且可防篡改")

# 仪表盘重聚合端点: 回归防护(历史 bug: 误删 func 导入导致 500; 缓存二次命中)
check("admin 未授权 401", client.get("/api/admin/summary"), 401)
check("旧格式 token 拒绝 401",
      client.get("/api/admin/summary", headers={"X-Admin-Token": "dash-test-token"}), 401)
check("admin token 过期拒绝 401",
      client.get("/api/admin/summary", headers={"X-Admin-Token": admin_mod._issue_admin_token(ttl=-1)}), 401)
_ver, _exp_s, _sig_s = _admin_tok.split(".")
_sig_broken = f"{_ver}.{_exp_s}." + ("A" if _sig_s[0] != "A" else "B") + _sig_s[1:]
check("admin token 签名篡改拒绝 401",
      client.get("/api/admin/summary", headers={"X-Admin-Token": _sig_broken}), 401)
check("admin token 有效期篡改拒绝 401",
      client.get("/api/admin/summary",
                 headers={"X-Admin-Token": f"{_ver}.{int(_exp_s) + 3600}.{_sig_s}"}), 401)
check("admin 退出 200",
      client.post("/api/admin/logout", headers={"X-Admin-Token": admin_mod._issue_admin_token(ttl=60)}), 200)

# 登录失败限流: 连续 5 次失败后第 6 次 429(只统计失败, 成功清零); 测完清桶避免影响其他用例
from wxcloudrun import views as _views  # noqa: E402
with app.test_request_context(headers={"X-Forwarded-For": "1.1.1.1, 2.2.2.2"}):
    assert _views._client_ip() == "2.2.2.2", _views._client_ip()
print("  [PASS] 可信代理 IP 解析不采用客户端最左侧伪造值")
_views._RATE_BUCKETS.clear()
for _ in range(admin_mod._ADMIN_FAIL_LIMIT):
    assert client.post("/api/admin/login", json={"password": "x"}).status_code == 401
check("admin 登录失败限流 429", client.post("/api/admin/login", json={"password": "x"}), 429)
_views._RATE_BUCKETS.clear()
print("  [PASS] admin 登录失败限流(60s 内失败 5 次后拒绝)")

for path in ("/api/admin/summary", "/api/admin/users", "/api/admin/stats/grades",
             "/api/admin/requests", "/api/admin/sessions"):
    r = client.get(path, headers=ah)
    assert r.status_code == 200 and r.get_json()["success"], (path, r.status_code)
r = client.get("/api/admin/summary?refresh=1", headers=ah)
assert r.status_code == 200 and r.get_json()["success"], r.status_code
print("  [PASS] 管理端仪表盘端点(含缓存与强制刷新)")

# 管理员删除应用会话: token 失效, 但持久化教务 Cookie 保留
from wxcloudrun.core import session_store as _session_store  # noqa: E402
_dc = JWCClient()
_dc.logged_in = True
_dc.student_id = "10009"
_dc.student_name = "保留Cookie"
_dc.is_session_valid = lambda: True
_dc.session.cookies.set("JWX", "keep-cookie",
                        domain="jw.njust.edu.cn", path="/")
_delete_token = views._register_session(_dc)
assert client.get("/api/courses", headers={
    "X-Auth-Token": _delete_token
}).status_code == 200
assert _session_store.load_session("10009") is not None
_dr = client.delete("/api/admin/sessions/10009", headers=ah)
assert _dr.status_code == 200 and _dr.get_json()["success"], _dr.get_json()
assert client.get("/api/courses", headers={
    "X-Auth-Token": _delete_token
}).status_code == 401
assert _session_store.load_session("10009") is not None
_session_store.clear_session("10009")
print("  [PASS] 管理员删除会话后 token 失效且保留持久化 Cookie")

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

# 用户主动删除服务端凭据; 退出登录保留密码
_fc.logout = lambda: None            # 假客户端: 避免真的发网络请求
assert _cred.save(_fc.student_id, "Smoke@1234") is True
assert _cred.resolve(_fc.student_id) == "Smoke@1234"
_fc.logged_in = False                # 教务会话失效时仍应允许删除凭据
assert _cred.save(_fc.student_id, "Smoke@1234") is True
check("/api/credentials DELETE 教务会话失效时仍可删除",
      client.delete("/api/credentials", headers=_fh), 200)
assert _cred.resolve(_fc.student_id) is None, "会话失效时删除凭据失败"
_fc.logged_in = True
assert _cred.save(_fc.student_id, "Smoke@1234") is True
check("/api/credentials DELETE 删除服务端凭据",
      client.delete("/api/credentials", headers=_fh), 200)
assert _cred.resolve(_fc.student_id) is None, "主动删除后服务端凭据仍存在"
print("  [PASS] 用户主动删除服务端保存的密码")
assert _cred.save(_fc.student_id, "Smoke@1234") is True
check("/api/logout 退出登录", client.post("/api/logout", headers=_fh), 200)
assert _cred.resolve(_fc.student_id) == "Smoke@1234", "退出登录不应删除服务端密码"
print("  [PASS] 退出登录保留服务端保存的密码")

# 会话失效: 用户明确保存的服务端凭据可自动重登一次
_rc = JWCClient()
_rc.logged_in = True
_rc.student_id = "10004"
_rc.student_name = "自动重登"
_rc.is_session_valid = lambda: False
_rc.login_webvpn = lambda sid, pwd: (
    setattr(_rc, "logged_in", sid == "10004" and pwd == "AutoRelogin@1234")
    or _rc.logged_in
)
_rt = views._register_session(_rc)
assert _cred.save("10004", "AutoRelogin@1234") is True
_rr = client.get("/api/courses", headers={"X-Auth-Token": _rt})
assert _rr.status_code == 200 and _rr.get_json()["success"] is True, _rr.get_json()
print("  [PASS] 会话失效时使用明确授权保存的密码自动重登")

print("== 教学周历 / 培养方案接口 ==")
_cc = JWCClient()
_cc.logged_in = True
_cc.student_id = "10001"
_cc.student_name = "回归甲"
_cc.is_session_valid = lambda: True
_cc.account_type = ""
dao.set_user_setting("10001", "semester", "2026-2027-1")
_ct = views._register_session(_cc)
_ch = {"X-Auth-Token": _ct}
check("/api/calendar 未登录 401", client.get("/api/calendar"), 401)
_cc.fetch_calendar = lambda semester="": {
    "semester": "2026-2027-1", "first_monday": "2026-08-24", "count": 1,
    "weeks": [{"week": 1, "monday": "2026-08-24", "sunday": "2026-08-30",
               "days": ["2026-08-24"] * 7, "note": ""}],
}
_cr = client.get("/api/calendar", headers=_ch)
check("/api/calendar 200", _cr, 200)
assert _cr.get_json().get("first_monday") == "2026-08-24", _cr.get_json()
assert dao.get_user_setting(
    "10001", "first_week_date:2026-2027-1") == "2026-08-24", "周历未回写 first_week_date"
_cached = client.get("/api/calendar", headers=_ch).get_json()
assert _cached.get("cached") is True, _cached
check("/api/refresh-calendar 200", client.post("/api/refresh-calendar", headers=_ch), 200)

_cc.fetch_programme = lambda: {
    "pages": 1, "count": 1,
    "courses": [{"semester": "2024-2025-1", "code": "00010701", "name": "劳动教育理论",
                 "dept": "教务处", "credit": 0.5, "hours": 8,
                 "exam_type": "考查", "attribute": "必修", "is_exam": "是"}],
}
check("/api/programme 未登录 401", client.get("/api/programme"), 401)
_pr = client.get("/api/programme", headers=_ch)
check("/api/programme 200", _pr, 200)
assert _pr.get_json()["courses"][0]["code"] == "00010701", _pr.get_json()
_pr2 = client.get("/api/programme", headers=_ch).get_json()
assert _pr2.get("cached") is True, _pr2
check("/api/refresh-programme 200", client.post("/api/refresh-programme", headers=_ch), 200)
_cc.account_type = "graduate"
_pg = client.get("/api/programme", headers=_ch).get_json()
assert _pg.get("supported") is False and _pg.get("courses") == [], _pg

_cc.fetch_profile = lambda: {
    "fields": {"院系": "机械工程学院", "专业": "机器人工程", "学号": "10001", "姓名": "回归甲"},
    "base": {"college": "机械工程学院", "major": "机器人工程", "student_id": "10001"},
}
check("/api/profile 未登录 401", client.get("/api/profile"), 401)
_pf = client.get("/api/profile", headers=_ch)
check("/api/profile 200", _pf, 200)
assert _pf.get_json()["fields"]["专业"] == "机器人工程", _pf.get_json()
_pf2 = client.get("/api/profile", headers=_ch).get_json()
assert _pf2.get("cached") is True, _pf2
check("/api/refresh-profile 200", client.post("/api/refresh-profile", headers=_ch), 200)

# 订阅消息: 状态 / 授权额度 / 未配置密钥时的样例发送
check("/api/subscribe/status 未登录 401", client.get("/api/subscribe/status"), 401)
_sub = client.get("/api/subscribe/status", headers=_ch)
check("/api/subscribe/status 200", _sub, 200)
assert "exam" in _sub.get_json()["kinds"], _sub.get_json()
check("/api/subscribe/grant 200",
      client.post("/api/subscribe/grant", json={"kind": "exam"}, headers=_ch), 200)
assert client.get("/api/subscribe/status", headers=_ch).get_json()["kinds"]["exam"]["quota"] == 1
client.post("/api/subscribe/grant",
            json={"kind": "exam", "count": 999}, headers=_ch)
assert client.get("/api/subscribe/status",
                  headers=_ch).get_json()["kinds"]["exam"]["quota"] == 2
check("/api/subscribe/grant 未知类型 400",
      client.post("/api/subscribe/grant", json={"kind": "nope"}, headers=_ch), 400)
check("/api/subscribe/test-send 未配置密钥 400",
      client.post("/api/subscribe/test-send", headers=_ch), 400)
print("  [PASS] 教学周历/培养方案/学籍卡片/订阅消息接口")

# 研究生登录: 必须真实校验密码(不再"有缓存会话就放行"), 明确授权后保存凭据
print("== 研究生登录(假客户端, 不打真实 SSO) ==")
import wxcloudrun.yjs_client as _yjs_mod  # noqa: E402


class _FakeYJS:
    def __init__(self):
        self.student_id = ""
        self.student_name = "研究生甲"
        self.last_error = ""
        self.logged_in = False
        self.login_method = ""
        self.login_calls = []

    def login(self, sid, password):
        self.login_calls.append((sid, password))
        if password != "Yjs@1234":
            self.last_error = "密码错误"
            return False
        self.student_id = sid
        self.logged_in = True
        self.login_method = "yjs"
        return True

    def _current_semester(self):
        return "2026-2027-1"


_yjs_orig = _yjs_mod.YJSClient
_yjs_created = []
_yjs_mod.YJSClient = lambda: (_yjs_created.append(_FakeYJS()) or _yjs_created[-1])
try:
    check("登录-空密码 400",
          client.post("/api/login-webvpn", json={"student_id": "199000000000", "password": ""}), 400)
    check("研究生登录 错密码 401",
          client.post("/api/login-webvpn",
                      json={"student_id": "126000000001", "password": "bad"}), 401)
    _yr = client.post("/api/login-webvpn",
                      json={"student_id": "126000000001", "password": "Yjs@1234",
                            "remember": True})
    check("研究生登录 正确密码 200", _yr, 200)
finally:
    _yjs_mod.YJSClient = _yjs_orig
assert _yjs_created and _yjs_created[0].login_calls, "研究生登录未走真实登录(疑似仍复用缓存会话)"
assert _cred.resolve("126000000001") == "Yjs@1234", "研究生登录未保存凭据"
print("  [PASS] 研究生登录强制校验密码并保存凭据")

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

print("== jwc 拆分完整性(mixin 可访问 common 全部下划线符号) ==")
import importlib as _importlib  # noqa: E402
import wxcloudrun.jwc.common as _common_mod  # noqa: E402

# 只取模块级下划线符号(类方法等类属性不在模块命名空间, 不需要导入)
_syms = sorted(n for n in vars(_common_mod)
               if n.startswith("_") and not n.startswith("__"))
_MIXINS = ("base", "login", "core", "schedule", "exams", "utils",
           "eval", "grades", "cet", "freeclass", "qrlogin",
           "calendar", "programme", "profile")
for _m in _MIXINS:
    _mod = _importlib.import_module("wxcloudrun.jwc." + _m)
    _missing = [n for n in _syms if not hasattr(_mod, n)]
    assert not _missing, "jwc.%s 缺符号: %s" % (_m, _missing)
print("  [PASS] %d 个 mixin 均可访问 common 全部下划线符号(%d 个)"
      % (len(_MIXINS), len(_syms)))

print()
print(f"结果: {PASS} 通过, {FAIL} 失败")
if FAIL:
    print("失败项:", FAILURES)
    sys.exit(1)
print("冒烟测试全部通过 [OK]")
