# -*- coding: utf-8 -*-
"""Audit-course query parser and API contract checks."""
import os
import sys
import tempfile
import json

from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + _tmp.name.replace("\\", "/")
os.environ["AUDIT_OPTIONS_CHUNK_SIZE"] = "2"

from wxcloudrun import app, db, views  # noqa: E402
from wxcloudrun.jwc_client import JWCClient  # noqa: E402
from wxcloudrun.model import AuditCourse  # noqa: E402


def make_catalog_html(course_name, first_cell):
    header = (
        "<tr><td></td>"
        + "".join(
            f"<td colspan='6'>星期{day}</td>" for day in "一二三四五六日")
        + "</tr>"
    )
    periods = (
        "<tr><td>课程\\节次</td>"
        + "".join(
            f"<td>{code}</td>"
            for _ in range(7)
            for code in ("010203", "0405", "0607", "080910", "111213", "14")
        )
        + "</tr>"
    )
    cells = [first_cell] + ["<td></td>"] * 41
    return (
        "<html><body><table id='kbtable'>"
        + header + periods
        + f"<tr><td>{course_name}</td>" + "".join(cells)
        + "</tr></table></body></html>"
    )


HTML = make_catalog_html(
    "数据结构",
    "<td><div class='kbcontent1'>924101960123<br>张老师<br>"
    "(1-16周)<br>Ⅳ-A101</div></td>",
)

PAGE_HTML = """
<html><body>
<form id="Form1" action="/njlgdx/kbcx/kbxx_kc_ifr" method="post">
  <input name="kc" value="">
  <select name="xnxqh">
    <option value="2025-2026-2">2025-2026-2</option>
    <option value="2026-2027-1">2026-2027-1</option>
  </select>
  <select name="skyx"><option value="">全部</option></select>
  <select name="kkyx"><option value="">全部</option></select>
  <select name="zzdKcSX"><option value="">全部</option></select>
  <select name="zc1"><option value="">全部</option></select>
  <select name="zc2"><option value="">全部</option></select>
  <select name="jc1"><option value="">全部</option></select>
  <select name="jc2"><option value="">全部</option></select>
</form>
</body></html>
"""


class FakeResponse:
    status_code = 200
    text = HTML
    url = "https://bkjw.njust.edu.cn/njlgdx/kbcx/kbxx_kc_ifr"


class FakePageResponse:
    status_code = 200
    text = PAGE_HTML
    url = "https://bkjw.njust.edu.cn/njlgdx/kbcx/kbxx_kc"


def check(name, condition, detail=""):
    if not condition:
        raise AssertionError(f"{name}: {detail}")
    print(f"  [PASS] {name}")


client = JWCClient()
client.logged_in = True
client.student_id = "924101960123"
posted = {}


def fake_post(url, *args, **kwargs):
    posted["url"] = url
    posted["data"] = kwargs.get("data", {})
    return FakeResponse()


client.session.get = lambda *args, **kwargs: FakePageResponse()
client.session.post = fake_post
client._is_jw_login_page = lambda resp: False
courses = client.fetch_course_schedule("2026-2027-1", "数据结构")
check("course parser returns available fields",
      len(courses) == 1
      and courses[0]["name"] == "数据结构"
      and courses[0]["class_info"] == "924101960123"
      and courses[0]["teacher"] == "张老师"
      and courses[0]["classroom"] == "Ⅳ-A101"
      and courses[0]["weeks"] == "1-16"
      and courses[0]["day"] == 1
      and courses[0]["start"] == 1,
      courses)
check("course query resolves the actual Form1 action and fields",
      posted["url"] == "https://bkjw.njust.edu.cn/njlgdx/kbcx/kbxx_kc_ifr"
      and posted["data"]["xnxqh"] == "2026-2027-1"
      and posted["data"]["kc"] == "数据结构",
      posted)

catalog_table = BeautifulSoup(
    HTML,
    "lxml",
).find("table", id="kbtable")
catalog_courses = client._parse_kbtable(catalog_table, {})
check("real course-catalog table parser",
      catalog_courses == [{
          "name": "数据结构",
          "class_info": "924101960123",
          "teacher": "张老师",
          "classroom": "Ⅳ-A101",
          "day": 1,
          "start": 1,
          "end": 3,
          "weeks": "1-16",
          "week_type": 0,
          "credits": "",
          "course_type": "",
          "raw": {},
      }],
      catalog_courses)

reverse_room_div = BeautifulSoup(
    "<div class='kbcontent1'>92337125E1<br>周广盼<br>"
    "(1-2周)<br>其它教室</div>",
    "lxml",
).find("div", class_="kbcontent1")
reverse_room_course = client._parse_catalog_course(
    reverse_room_div, "土木工程常用软件简介【英】", 4, (11, 13))
check("catalog parser distinguishes classroom from teacher",
      len(reverse_room_course) == 1
      and reverse_room_course[0]["teacher"] == "周广盼"
      and reverse_room_course[0]["classroom"] == "其它教室"
      and reverse_room_course[0]["weeks"] == "1-2",
      reverse_room_course)

design_room_div = BeautifulSoup(
    "<div class='kbcontent1'>9251091603<br>设传外教01\n(6周)<br></div>",
    "lxml",
).find("div", class_="kbcontent1")
design_room_course = client._parse_catalog_course(
    design_room_div, "2D数字表现技法", 4, (8, 10))
check("catalog parser treats 设传外教01 as classroom",
      len(design_room_course) == 1
      and design_room_course[0]["teacher"] == ""
      and design_room_course[0]["classroom"] == "设传外教01"
      and design_room_course[0]["weeks"] == "6",
      design_room_course)

with app.app_context():
    migration_row = AuditCourse(
        semester="migration-test", course_name="存量教室迁移",
        class_info="test", teacher="设传外教01", classroom="",
        day_of_week=1, start_period=1, end_period=2, weeks="1")
    db.session.add(migration_row)
    db.session.commit()
    import wxcloudrun as _wxcloudrun
    _wxcloudrun._migrate_audit_course_rooms()
    db.session.refresh(migration_row)
    check("legacy audit classroom value is moved out of teacher",
          migration_row.teacher == ""
          and migration_row.classroom == "设传外教01",
          migration_row.to_dict())
    db.session.delete(migration_row)
    db.session.commit()

multi_block_div = BeautifulSoup(
    "<div class='kbcontent1'>"
    "9241015001,9241015002<br>陈刚,李四<br>"
    "(2,5-6,8-9周)<br>Ⅳ-A303<br>"
    "9241015001,9241015002<br>陈刚<br>"
    "(10周)<br>Ⅳ-A303"
    "</div>",
    "lxml",
).find("div", class_="kbcontent1")
multi_block_courses = client._parse_catalog_course(
    multi_block_div, "工程流体力学基础", 2, (1, 3))
check("one cell splits multiple class/teacher/week blocks",
      len(multi_block_courses) == 2
      and multi_block_courses[0]["class_info"] == "9241015001,9241015002"
      and multi_block_courses[0]["teacher"] == "陈刚,李四"
      and multi_block_courses[0]["weeks"] == "2,5-6,8-9"
      and multi_block_courses[1]["teacher"] == "陈刚"
      and multi_block_courses[1]["weeks"] == "10",
      multi_block_courses)

audit_courses = courses + [
    {
        "name": "高等数学",
        "teacher": "李老师",
        "classroom": "Ⅰ-201",
        "day": 2,
        "start": 3,
        "end": 5,
        "weeks": "1-16",
    },
    {
        "name": "大学物理",
        "teacher": "张老师",
        "classroom": "Ⅳ-B202",
        "day": 3,
        "start": 6,
        "end": 7,
        "weeks": "1-16",
    },
    {
        "name": "线性代数",
        "teacher": "赵老师,钱老师",
        "classroom": "Ⅰ-301",
        "day": 5,
        "start": 12,
        "end": 13,
        "weeks": "1-16",
    },
]

client.is_session_valid = lambda: True
token = views._register_session(client)
client.fetch_course_schedule = lambda **kwargs: (
    _ for _ in ()).throw(RuntimeError("API should not access JWC"))
from wxcloudrun import dao  # noqa: E402
with app.app_context():
    dao.replace_audit_courses(audit_courses, "2026-2027-1")
    dao.set_setting("audit_catalog_at:2026-2027-1", "1")
http = app.test_client()


sync_versions = http.get(
    "/api/sync/versions", headers={"X-Auth-Token": token})
check("sync versions expose all dataset version keys",
      sync_versions.status_code == 200
      and sync_versions.get_json()["versions"].keys() == {
          "courses", "exams", "evaluations", "grades", "cet_scores"},
      sync_versions.get_json())


def query(params):
    response = http.get("/api/audit-courses", query_string=params,
                        headers={"X-Auth-Token": token})
    payload = response.get_json()
    if response.status_code != 200 or not payload.get("success"):
        raise AssertionError((response.status_code, payload))
    return payload


def options(params):
    response = http.get("/api/audit-options", query_string=params,
                        headers={"X-Auth-Token": token})
    payload = response.get_json()
    if response.status_code != 200 or not payload.get("success"):
        raise AssertionError((response.status_code, payload))
    return payload


public_version = http.get("/api/audit-options?field=version")
check("audit query form requires login",
      public_version.status_code == 401,
      public_version.get_json())

payload = query({"q": "数据结构"})
check("legacy q still returns pageable course fields",
      payload["total"] == 1
      and payload["courses"][0]["name"] == "数据结构"
      and payload["courses"][0]["schedule_count"] == 1
      and payload["courses"][0]["schedules"][0]["weeks"] == "1-16"
      and payload["fields"] == [
          "name", "class_info", "teacher", "classroom", "schedules",
          "schedule_count"],
      payload)

check("course name filter",
      query({"name": "物理"})["total"] == 1,
      query({"name": "物理"}))
check("teacher filter",
      query({"teacher": "张老师"})["total"] == 2,
      query({"teacher": "张老师"}))
check("classroom filter",
      query({"classroom": "B202"})["total"] == 1,
      query({"classroom": "B202"}))
check("weekday and period overlap filter",
      query({"weekday": 2, "jc1": 4, "jc2": 6})["total"] == 1,
      query({"weekday": 2, "jc1": 4, "jc2": 6}))
check("reversed period range is normalized",
      query({"jc1": 6, "jc2": 4})["total"] == 2,
      query({"jc1": 6, "jc2": 4}))
check("combined filters use AND semantics",
      query({"teacher": "张老师", "classroom": "B202",
             "weekday": 3})["total"] == 1,
      query({"teacher": "张老师", "classroom": "B202", "weekday": 3}))
check("course name options are distinct",
      options({"field": "name"})["options"] == [
          "大学物理", "数据结构", "线性代数", "高等数学"],
      options({"field": "name"}))
check("teacher options support prefix filtering",
      options({"field": "teacher", "q": "张"})["options"] == ["张老师"],
      options({"field": "teacher", "q": "张"}))
check("teacher options split comma-separated teachers",
      options({"field": "teacher", "q": "赵"})["options"] == ["赵老师"],
      options({"field": "teacher", "q": "赵"}))
check("classroom options support keyword filtering",
      options({"field": "classroom", "q": "B202"})["options"] == ["Ⅳ-B202"],
      options({"field": "classroom", "q": "B202"}))
all_options = options({"field": "all"})
check("full query list returns split names/teachers/classrooms",
      all_options["names"] == [
          "大学物理", "数据结构", "线性代数", "高等数学"]
      and "张老师" in all_options["teachers"]
      and "赵老师" in all_options["teachers"]
      and all("," not in value and "，" not in value
              for value in all_options["teachers"])
      and "Ⅳ-B202" in all_options["classrooms"],
      all_options)
check("full query list includes cascading relations",
      any(
          all_options["names"][item[0]] == "数据结构"
          and any(all_options["teachers"][index] == "张老师"
                  for index in item[1])
          and any(all_options["classrooms"][index] == "Ⅳ-A101"
                  for index in item[2])
          and item[3:] == [1, 1, 3]
          for item in all_options["relations"]
      ),
      all_options["relations"])
chunk0 = options({"field": "all", "part": 0})
chunk1 = options({"field": "all", "part": 1})
check("full query list supports chunked transfer",
      chunk0["parts"] == 2
      and chunk0["part"] == 0
      and chunk0["relations_offset"] == 0
      and len(chunk0["relations"]) == 2
      and chunk0["names"]
      and chunk1["part"] == 1
      and chunk1["relations_offset"] == 2
      and len(chunk1["relations"]) == 2
      and "names" not in chunk1,
      (chunk0, chunk1))
version_info = options({"field": "version"})
check("query list version endpoint is lightweight",
      version_info["catalog_version"] == 1
      and version_info["count"] == 4,
      version_info)
bad_options = http.get(
    "/api/audit-options?field=unknown", headers={"X-Auth-Token": token})
check("audit options reject unsupported fields",
      bad_options.status_code == 400
      and not bad_options.get_json().get("success"),
      bad_options.get_json())

# 精确选择: 课程名/教师/地点应只匹配当前值, 不匹配前缀或包含关系。
with app.app_context():
    dao.replace_audit_courses(audit_courses + [
        {
            "name": "大学物理实验",
            "teacher": "张老师傅",
            "classroom": "Ⅳ-B2021",
            "day": 4,
            "start": 6,
            "end": 7,
            "weeks": "1-16",
        },
        {
            "name": "多教室课程",
            "teacher": "王老师",
            "classroom": "Ⅳ-A303,Ⅳ-A304",
            "day": 5,
            "start": 8,
            "end": 10,
            "weeks": "1-16",
        },
    ], "2026-2027-1")
    dao.set_setting("audit_catalog_at:2026-2027-1", "2")

check("exact course name excludes prefix matches",
      query({"name": "大学物理", "name_exact": 1})["total"] == 1,
      query({"name": "大学物理", "name_exact": 1}))
check("exact teacher excludes similar names",
      query({"teacher": "张老师", "teacher_exact": 1})["total"] == 2,
      query({"teacher": "张老师", "teacher_exact": 1}))
check("exact classroom excludes longer room codes",
      query({"classroom": "Ⅳ-B202", "classroom_exact": 1})["total"] == 1,
      query({"classroom": "Ⅳ-B202", "classroom_exact": 1}))

split_options = options({"field": "classroom", "q": "A303"})
check("classroom options split comma-separated rooms",
      split_options["options"] == ["Ⅳ-A303"],
      split_options)
split_all = options({"field": "all"})
check("full query list splits comma-separated rooms",
      "Ⅳ-A303" in split_all["classrooms"]
      and "Ⅳ-A304" in split_all["classrooms"],
      split_all["classrooms"])
multi_room_index = split_all["names"].index("多教室课程")
check("full query relations include both split rooms",
      any(
          item[0] == multi_room_index
          and {split_all["classrooms"][index] for index in item[2]}
          == {"Ⅳ-A303", "Ⅳ-A304"}
          for item in split_all["relations"]
      ),
      split_all["relations"])

multi_names = query({
    "names": json.dumps(["数据结构", "高等数学"], ensure_ascii=False),
    "name_exact": 1,
})
check("multi-select names use OR within dimension",
      multi_names["total"] == 2
      and {item["name"] for item in multi_names["courses"]}
      == {"数据结构", "高等数学"},
      multi_names)

multi_cross = query({
    "names": json.dumps(["数据结构"], ensure_ascii=False),
    "teachers": json.dumps(["张老师"], ensure_ascii=False),
    "name_exact": 1,
    "teacher_exact": 1,
})
check("multi-select dimensions remain AND across dimensions",
      multi_cross["total"] == 1
      and multi_cross["courses"][0]["name"] == "数据结构",
      multi_cross)

favorite_course = {
    "name": "数据结构",
    "class_info": "924101960123",
    "teacher": "张老师",
    "classroom": "Ⅳ-A101",
    "schedules": [{
        "day": 1,
        "start": 1,
        "end": 3,
        "weeks": "1-16",
        "teacher": "张老师",
        "classroom": "Ⅳ-A101",
    }],
}
favorite_resp = http.post(
    "/api/audit-favorites",
    json={"semester": "2026-2027-1", "course": favorite_course},
    headers={"X-Auth-Token": token},
)
favorite_payload = favorite_resp.get_json()
favorite_id = favorite_payload.get("favorite", {}).get("id")
check("audit favorite can be saved",
      favorite_resp.status_code == 200
      and favorite_payload["success"]
      and favorite_id
      and favorite_payload["favorite"]["name"] == "数据结构",
      favorite_payload)
duplicate_resp = http.post(
    "/api/audit-favorites",
    json={"semester": "2026-2027-1", "course": favorite_course},
    headers={"X-Auth-Token": token},
)
favorite_list = http.get(
    "/api/audit-favorites?semester=2026-2027-1",
    headers={"X-Auth-Token": token},
).get_json()
check("audit favorite is idempotent and scoped to the user",
      len(favorite_list["favorites"]) == 1
      and favorite_list["favorites"][0]["id"] == favorite_id,
      (duplicate_resp.get_json(), favorite_list))
delete_resp = http.delete(
    f"/api/audit-favorites/{favorite_id}",
    headers={"X-Auth-Token": token},
)
check("audit favorite can be deleted",
      delete_resp.status_code == 200
      and delete_resp.get_json()["success"]
      and not http.get(
          "/api/audit-favorites?semester=2026-2027-1",
          headers={"X-Auth-Token": token},
      ).get_json()["favorites"],
      delete_resp.get_json())

try:
    os.remove(_tmp.name)
except OSError:
    pass
print("\nAudit-course tests passed.")
