"""
多用户集成测试（本地，不依赖真实教务账号）
============================================
模拟两个用户完整链路: 登录 → 刷新课表/考试/成绩/四六级 → 互查数据 → 登出。
教务抓取通过 monkeypatch 假数据模拟（本地无法并发使用真实账号）。
验证:
  - 各自刷新数据互不干扰（后端会话按 token 隔离）
  - 数据按学号隔离（互不可见）
  - 登出只影响本人

用法: python tests/multi_user_test.py
"""
import os
import sys

# 独立临时 SQLite 库
_here = os.path.dirname(os.path.abspath(__file__))
_db_path = os.path.join(_here, "multi_user_tmp.db").replace("\\", "/")
if os.path.exists(_db_path):
    os.remove(_db_path)
os.environ["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{_db_path}"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wxcloudrun import app, dao  # noqa: E402
from wxcloudrun.jwc_client import JWCClient  # noqa: E402
from wxcloudrun import views  # noqa: E402

client = app.test_client()

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def make_user(sid: str, name: str) -> JWCClient:
    """构造已登录用户，mock 教务抓取方法"""
    c = JWCClient()
    c.logged_in = True
    c.student_id = sid
    c.student_name = name
    c.is_session_valid = lambda: True

    def fake_schedule(semester=""):
        return [{"name": f"{name}的专业课", "teacher": "T1", "classroom": "R1",
                 "day": 1, "start": 1, "end": 2, "weeks": "1-16", "week_type": 0,
                 "credits": "2", "course_type": "必修", "raw": {}}]

    def fake_exams(semester=""):
        return [{"course_name": f"{name}的考试", "date": "2026-09-01",
                 "time": "09:00-11:00", "location": "A101", "seat": "1",
                 "type": "期末考试"}]

    def fake_grades(semester=""):
        return [{"academic_year": "2025-2026", "semester": "2", "course_code": "C1",
                 "course_name": f"{name}的成绩课", "score": "90", "credit": 3,
                 "grade_point": 4.0, "course_type": "必修", "course_nature": "",
                 "exam_type": "正常考试"}]

    def fake_cet():
        return [{"type": "CET4", "score": 550, "exam_date": "2025-12"}]

    c.get_schedule = fake_schedule
    c.get_exams = fake_exams
    c.get_grades = fake_grades
    c.get_cet_scores = fake_cet
    return c


print("== 两用户登录并各自刷新全部数据 ==")
A = make_user("10001", "甲")
tA = views._register_session(A)
hA = {"X-Auth-Token": tA}
B = make_user("10002", "乙")
tB = views._register_session(B)
hB = {"X-Auth-Token": tB}

r = client.post("/api/refresh-all", headers=hA)
check("用户甲 刷新课表+考试", r.status_code == 200 and r.get_json()["success"], r.status_code)
r = client.post("/api/refresh-all", headers=hB)
check("用户乙 刷新课表+考试", r.status_code == 200 and r.get_json()["success"], r.status_code)
r = client.post("/api/refresh-grades", headers=hA)
check("用户甲 刷新成绩", r.status_code == 200 and r.get_json()["success"], r.status_code)
r = client.post("/api/refresh-grades", headers=hB)
check("用户乙 刷新成绩", r.status_code == 200 and r.get_json()["success"], r.status_code)
r = client.post("/api/refresh-cet", headers=hA)
check("用户甲 刷新四六级", r.status_code == 200 and r.get_json()["success"], r.status_code)

print("== 数据隔离验证 ==")
# 课表
rA = client.get("/api/courses", headers=hA).get_json()
rB = client.get("/api/courses", headers=hB).get_json()
check("甲看到自己的课", len(rA["courses"]) == 1 and "甲" in rA["courses"][0]["name"], rA["courses"])
check("乙看到自己的课", len(rB["courses"]) == 1 and "乙" in rB["courses"][0]["name"], rB["courses"])
check("甲看不到乙的课", all("乙" not in c["name"] for c in rA["courses"]))
check("乙看不到甲的课", all("甲" not in c["name"] for c in rB["courses"]))

# 考试
eA = client.get("/api/exams", headers=hA).get_json()
eB = client.get("/api/exams", headers=hB).get_json()
check("甲看到自己的考试", len(eA["exams"]) == 1 and "甲" in eA["exams"][0]["course_name"], eA["exams"])
check("乙看不到甲的考试", all("甲" not in e["course_name"] for e in eB["exams"]))

# 成绩
gA = client.get("/api/grades", headers=hA).get_json()
gB = client.get("/api/grades", headers=hB).get_json()
check("甲看到自己的成绩", len(gA["grades"]) == 1 and "甲" in gA["grades"][0]["course_name"], gA["grades"])
check("乙看不到甲的成绩", all("甲" not in g["course_name"] for g in gB["grades"]))

# 四六级
cA = client.get("/api/cet-scores", headers=hA).get_json()
cB = client.get("/api/cet-scores", headers=hB).get_json()
check("甲看到自己的四六级", len(cA["scores"]) == 1 and cA["scores"][0]["score"] == 550, cA["scores"])
check("乙的四六级为空", cB["scores"] == [], cB["scores"])

# 状态接口
sA = client.get("/api/status", headers=hA).get_json()
sB = client.get("/api/status", headers=hB).get_json()
check("甲的状态为已登录本人", sA["logged_in"] and sA["student_id"] == "10001", sA)
check("乙的状态为已登录本人", sB["logged_in"] and sB["student_id"] == "10002", sB)

print("== 验证码隔离验证 ==")
# 模拟两个用户同时获取验证码
cid1, c1 = views._new_captcha_client()
cid2, c2 = views._new_captcha_client()
check("两个验证码会话 ID 不同", cid1 != cid2, (cid1[:8], cid2[:8]))
check("两个验证码会话客户端实例独立", c1 is not c2)
check("两个客户端 Cookie 罐相互独立", c1.session.cookies is not c2.session.cookies)
check("两个客户端 Session 对象相互独立", c1.session is not c2.session)
# 客户端内验证码状态也是实例级的
c1._captcha_ready = True
c2._captcha_ready = False
check("验证码就绪状态互不影响", c1._captcha_ready is True and c2._captcha_ready is False)
# 登录消耗后互不影响
views._pop_captcha_client(cid1)
check("pop 仅删除对应用户的验证码会话",
      cid1 not in views._captcha_clients and cid2 in views._captcha_clients)
views._pop_captcha_client(cid2)
check("两个验证码会话均已消费删除", len(views._captcha_clients) == 0)

print("== 登出隔离验证 ==")
r = client.post("/api/logout", headers=hA)
check("甲 退出登录", r.status_code == 200)
check("甲 退出后 401", client.get("/api/courses", headers=hA).status_code == 401)
check("乙 不受影响仍可访问", client.get("/api/courses", headers=hB).status_code == 200)

# 清理
os.remove(_db_path)

print()
print(f"结果: {PASS} 通过, {FAIL} 失败")
sys.exit(1 if FAIL else 0)
