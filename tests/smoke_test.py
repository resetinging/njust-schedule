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

print("== 留言板 ==")
# 未登录保护
check("/api/board 未登录", client.get("/api/board"), 401)
check("/api/board POST 未登录", client.post("/api/board", json={"content": "x"}), 401)
check("/api/board/1/like 未登录", client.post("/api/board/1/like"), 401)
check("/api/board/1/comments 未登录", client.get("/api/board/1/comments"), 401)
check("/api/admin/board 未授权", client.get("/api/admin/board"), 401)

# 三个留言板用户(新会话; MAX_SESSIONS=3, 注册时自动顶掉同号旧会话)
import time as _time  # noqa: E402
_b_clients = []
for _sid, _name in [("10001", "留言甲"), ("10002", "留言乙"), ("10003", "留言丙")]:
    _c = JWCClient()
    _c.logged_in = True
    _c.student_id = _sid
    _c.student_name = _name
    _c.is_session_valid = lambda: True
    _b_clients.append(_c)
bt1 = views._register_session(_b_clients[0])
bt2 = views._register_session(_b_clients[1])
bt3 = views._register_session(_b_clients[2])
bh1 = {"X-Auth-Token": bt1}
bh2 = {"X-Auth-Token": bt2}
bh3 = {"X-Auth-Token": bt3}

# 发布留言: 强制匿名 + 首尾空白清洗 + 学号不外泄
r = client.post("/api/board", json={"content": "  大家好，这是第一条留言  "}, headers=bh1)
assert r.status_code == 200, r.status_code
m1 = r.get_json()["msg"]
assert m1["is_anonymous"] == 1 and m1["student_name"] == "" and m1["student_id"] == "" \
    and m1["content"] == "大家好，这是第一条留言", m1
print("  [PASS] 发布留言(强制匿名+内容清洗+学号不外泄)")

# 零宽字符与连续换行清洗
r = client.post("/api/board", json={"content": "A\u200bB\n\n\n\nC"}, headers=bh2)
assert r.status_code == 200, r.status_code
assert r.get_json()["msg"]["content"] == "AB\n\nC", r.get_json()
print("  [PASS] 零宽字符/连续换行清洗")

# 参数校验(校验先于限流, 故返回 400 而非 429)
check("留言-空内容", client.post("/api/board", json={"content": "  \n  "}, headers=bh1), 400)
check("留言-超长", client.post("/api/board", json={"content": "长" * 201}, headers=bh1), 400)
check("留言-敏感词", client.post("/api/board", json={"content": "代考找我"}, headers=bh1), 400)
check("留言-零宽绕过敏感词", client.post("/api/board", json={"content": "代\u200b考"}, headers=bh3), 400)

# 限流: 内存快路径 + DB 兜底(模拟另一实例已写入)
check("留言-10s 限流(内存)", client.post("/api/board", json={"content": "第二条"}, headers=bh1), 429)
with views._board_rate_lock:
    views._board_last_post["10001"] = 0
check("留言-10s 限流(DB 兜底)", client.post("/api/board", json={"content": "第三条"}, headers=bh1), 429)
print("  [PASS] 发布限流(内存+DB 双保险)")

# 列表: 匿名不暴露身份
r = client.get("/api/board", headers=bh2).get_json()
assert r["success"] and len(r["messages"]) >= 2, r
assert all(m["student_id"] == "" and m["student_name"] == "" for m in r["messages"]), r
print("  [PASS] 留言列表(匿名不暴露身份)")

# 点赞/取消 + 不存在留言 404
r = client.post(f"/api/board/{m1['id']}/like", headers=bh3)
j = r.get_json()
assert j["likes"] == 1 and j["liked"] is True, j
r = client.post(f"/api/board/{m1['id']}/like", headers=bh3)
j = r.get_json()
assert j["likes"] == 0 and j["liked"] is False, j
check("点赞-不存在留言 404", client.post("/api/board/999999/like", headers=bh3), 404)
print("  [PASS] 点赞/取消")

# 评论: 发表/读取 + 孤儿评论被拒 + 学号不外泄
r = client.post(f"/api/board/{m1['id']}/comments", json={"content": "沙发"}, headers=bh3)
assert r.status_code == 200, r.status_code
cmid = r.get_json()["comment"]["id"]
r = client.get(f"/api/board/{m1['id']}/comments", headers=bh2).get_json()
assert len(r["comments"]) == 1 and r["comments"][0]["content"] == "沙发" \
    and r["comments"][0]["student_id"] == "", r
check("评论-不存在留言 404", client.post("/api/board/999999/comments",
                                         json={"content": "x"}, headers=bh3), 404)
print("  [PASS] 评论发表与读取(孤儿评论被拒+学号不外泄)")

# 最热排序 (likes,id) 键集分页: 构造不同点赞数(直接写 dao, 绕过限流)
from wxcloudrun.model import BoardMessage as _BM  # noqa: E402
for i in range(3):
    _d = dao.save_board_message("10003", "留言丙", f"热门留言 {i}", 1)
    _BM.query.filter(_BM.id == _d["id"]).update({"likes": i + 1})
db.session.commit()
p1 = dao.get_board_messages(limit=2, sort="likes", viewer_id="10003")
assert len(p1) == 2 and p1[0]["likes"] == 3 and p1[1]["likes"] == 2, \
    [(m["likes"], m["id"]) for m in p1]
p2 = dao.get_board_messages(limit=2, sort="likes", before_id=p1[-1]["id"],
                            before_likes=p1[-1]["likes"], viewer_id="10003")
ids1 = {m["id"] for m in p1}
assert p2 and not ids1 & {m["id"] for m in p2}, "最热分页出现重复"
# 客户端不带 before_likes 时后端反查锚点, 分页结果一致
p2b = dao.get_board_messages(limit=2, sort="likes", before_id=p1[-1]["id"], viewer_id="10003")
assert {m["id"] for m in p2} == {m["id"] for m in p2b}, "before_likes 反查兜底不一致"
alls = p1 + p2
assert alls == sorted(alls, key=lambda m: (m["likes"], m["id"]), reverse=True), "最热排序乱序"
print("  [PASS] 最热排序键集分页(无重叠/有序/反查兜底)")

# 管理端: 列表含真实学号 + 删除评论 + 删除留言级联
from wxcloudrun import admin as admin_mod  # noqa: E402
admin_mod._admin_token = ("board-test-token", _time.time() + 3600)
ah = {"X-Admin-Token": "board-test-token"}
r = client.get("/api/admin/board", headers=ah)
assert r.status_code == 200 and r.get_json()["success"], r.status_code
sids = {m["student_id"] for m in r.get_json()["messages"]}
assert {"10001", "10002", "10003"} <= sids, sids
print("  [PASS] 管理端留言列表(含真实学号)")
check("admin 删除评论", client.delete(f"/api/admin/board/comment/{cmid}", headers=ah), 200)
r = client.get(f"/api/board/{m1['id']}/comments", headers=bh2).get_json()
assert all(c["id"] != cmid for c in r["comments"]), r
check("admin 删除不存在评论 404",
      client.delete("/api/admin/board/comment/999999", headers=ah), 404)
print("  [PASS] 管理端删除单条评论")
# 删除留言级联: 评论/点赞一并清除, 后续访问 404
check("admin 删除留言", client.delete(f"/api/admin/board/{m1['id']}", headers=ah), 200)
check("删除后读评论 404", client.get(f"/api/board/{m1['id']}/comments", headers=bh2), 404)
check("删除后点赞 404", client.post(f"/api/board/{m1['id']}/like", headers=bh3), 404)
print("  [PASS] 管理端删除留言(级联+404)")

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
