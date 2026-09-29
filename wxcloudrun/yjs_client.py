# -*- coding: utf-8 -*-
"""研究生综合管理信息系统客户端。

登录链路(与教务的 CAS 直连不同):
  智慧理工 SSO(ids) → 网上办事服务大厅(ehall2) 服务票据
  → yjs.njust.edu.cn/ulogin.aspx?gid_=… → 进入 /Gstudent/

课表:
  从 LeftMenu.aspx 的菜单树里取「学期课表信息查询」的当前 EID 链接,
  抓取后解析 GridView(节次 × 星期, 上午/下午/晚上分组),
  再转换成与教务完全一致的 courses 结构, 供小程序前端无缝复用。
"""
import json
import re
import threading
import time
from urllib.parse import urljoin, quote

import requests
from bs4 import BeautifulSoup

from config import SSO_BASE
from wxcloudrun.jwc.common import _encrypt_sso_password

TIMEOUT = 25
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

EHALL = "https://ehall2.njust.edu.cn"
YJS_BASE = "https://yjs.njust.edu.cn"
GSTUDENT = f"{YJS_BASE}/Gstudent/"
EHALL_YJS_SERVICE_ID = "854314156332171264"     # 服务大厅里"研究生综合管理信息系统"
SESSION_SETTING_KEY = "yjs_session"             # settings 表: {sid}:yjs_session

COURSE_RE = re.compile(
    r"^\s*(?P<name>.+?)\s*(?P<cls>\d+班)?\s*[｛{](?P<weeks>[^［\[]+?)\s*"
    r"\[教师[:：](?P<teacher>[^,\]]+)\s*,\s*地点[:：](?P<room>[^\]]+)\]\s*[｝}]"
)


def _normalize_weeks(raw: str) -> str:
    """'4-6、8-12周' → '4-6,8-12'(前端按逗号切分)。"""
    s = (raw or "").replace("周", "").replace("、", ",").replace("，", ",")
    s = s.replace("－", "-").replace("—", "-").replace("~", "-")
    return ",".join(p.strip() for p in s.split(",") if p.strip())


def parse_yjs_week_table(html: str) -> dict:
    """解析研究生课表页(节次 × 星期 GridView) → 统一 courses 结构。"""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id=re.compile(r"dgData$"))
    if not table:
        return {"courses": [], "semesters": [], "timetable": []}

    semesters = []
    for s in re.findall(r"\d{4}-\d{4}[^\s<【】]{0,6}?学期", html):
        if s not in semesters:
            semesters.append(s)

    rows = table.find_all("tr")
    day_cols = []
    col = 0
    for th in rows[0].find_all(["th", "td"]):
        if th.get_text(strip=True).startswith("星期"):
            day_cols.append(col)
        col += int(th.get("colspan") or 1)

    courses, occupied, section = [], {}, ""
    for tr in rows[1:]:
        for k in list(occupied):        # 行首递减上一行设置的 rowspan 占位
            occupied[k] -= 1
            if occupied[k] <= 0:
                del occupied[k]
        cells, col = {}, 0
        for td in tr.find_all(["td", "th"]):
            while occupied.get(col, 0) > 0:
                col += 1
            txt = td.get_text("\n", strip=True)
            rs = int(td.get("rowspan") or 1)
            cs = int(td.get("colspan") or 1)
            cells[col] = (txt, rs)
            if rs > 1:
                for dc in range(cs):
                    occupied[col + dc] = rs
            col += cs

        if 0 in cells and cells[0][0] in ("上午", "下午", "晚上"):
            section = cells[0][0]
        sec_raw = cells.get(1, ("", 0))[0]
        if not re.fullmatch(r"\d+", sec_raw):
            continue
        sec_no = int(sec_raw)
        for day_i, dcol in enumerate(day_cols):
            if dcol not in cells:
                continue
            txt, span = cells[dcol]
            for piece in [p for p in txt.split("\n") if p.strip()]:
                mm = COURSE_RE.search(piece)
                if not mm:
                    continue
                courses.append({
                    "name": mm.group("name").strip(),
                    "class_no": (mm.group("cls") or "").strip(),
                    "teacher": mm.group("teacher").strip(),
                    "classroom": mm.group("room").strip(),
                    "day_of_week": day_i + 1,
                    "start_period": sec_no,
                    "end_period": sec_no + span - 1,
                    "weeks": _normalize_weeks(mm.group("weeks")),
                    "section": section,
                })

    plain = soup.get_text(" ", strip=True)
    timetable = []
    for m in re.finditer(r"第\s*(\d+)\s*节[：:]\s*([0-9:：\-—~～]+)", plain):
        timetable.append({"section": int(m.group(1)),
                          "time": m.group(2).replace("：", ":").strip()})
    return {"courses": courses, "semesters": semesters, "timetable": timetable}


def parse_yjs_grade_page(html: str) -> dict:
    """解析研究生成绩页: 学分进度统计 + 成绩明细行(列含义待有数据时精修)。"""
    soup = BeautifulSoup(html, "lxml")
    plain = soup.get_text(" ", strip=True).replace("\xa0", " ")

    stats, seen = [], set()
    for m in re.finditer(
            r"(总学分|必修课|选修课|必修环节|学位课)\s*"
            r"【培养方案要求最低[:：]\s*([\d.]+)\s*已修[:：]\s*([\d.]+)\s*"
            r"培养计划制定[:：]\s*([\d.]+)】", plain):
        name = m.group(1)
        if name in seen:
            continue
        seen.add(name)
        stats.append({"name": name, "required": float(m.group(2)),
                      "earned": float(m.group(3)), "planned": float(m.group(4))})

    rows = []
    table = soup.find("table", id=re.compile(r"dgData$"))
    if table:
        for tr in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if any(cells):
                rows.append(cells)

    semesters = []
    for s in re.findall(r"\d{4}-\d{4}[^\s<【】]{0,6}?学期", html):
        if s not in semesters:
            semesters.append(s)

    return {"stats": stats, "rows": rows, "semesters": semesters}


class YJSClient:
    """与 JWCClient 对外接口保持一致的会话载体(student_id/student_name/logged_in)。"""

    account_type = "graduate"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA})
        self._lock = threading.RLock()      # 与 JWCClient 一致: 供请求池串行化使用
        self.student_id = ""
        self.student_name = ""
        self.last_error = ""
        self.logged_in = False
        self.login_method = ""
        self._menu_html = ""
        self._semesters = []

    # ---------------- 登录 ----------------
    def _sso_login(self, student_id: str, password: str) -> bool:
        login_url = (f"{SSO_BASE}/authserver/login?"
                     f"service={quote(EHALL + '/login', safe='')}")
        r = self.session.get(login_url, timeout=TIMEOUT)
        form = BeautifulSoup(r.text, "lxml").find("form", id="pwdFromId")
        if not form:
            self.last_error = "未拿到智慧理工登录表单"
            return False

        def fv(fid):
            inp = form.find("input", id=fid)
            return (inp.get("value") or "").strip() if inp else ""

        post_url = urljoin(r.url, (form.get("action") or "").strip() or r.url)
        if "service=" in r.url and "service=" not in post_url:
            post_url += ("&" if "?" in post_url else "?") + r.url.split("?", 1)[1]
        resp = self.session.post(
            post_url, timeout=TIMEOUT, allow_redirects=True,
            headers={"Referer": r.url},
            data={"username": student_id, "passwordText": password,
                  "password": _encrypt_sso_password(password, fv("pwdEncryptSalt")),
                  "captcha": "", "rememberMe": "true", "_eventId": "submit",
                  "cllt": "userNameLogin", "dllt": "generalLogin",
                  "lt": fv("lt"), "execution": fv("execution")})
        m_tip = re.search(r'id="showErrorTip"[^>]*>\s*<span>([^<]*)</span>', resp.text)
        if m_tip and m_tip.group(1).strip():
            self.last_error = f"智慧理工登录失败：{m_tip.group(1).strip()}"
            return False
        if resp.status_code == 401:
            self.last_error = "智慧理工账号或密码错误"
            return False
        return True

    def _enter_yjs(self) -> bool:
        """服务大厅取票据 → 进研究生系统。"""
        r = self.session.get(f"{EHALL}/serviceShow", timeout=TIMEOUT,
                             params={"isMobile": "0",
                                     "serviceId": EHALL_YJS_SERVICE_ID})
        try:
            data = (r.json() or {}).get("data") or {}
        except ValueError:
            self.last_error = "服务大厅返回异常"
            return False
        url = data.get("serviceUrl") or ""
        if not url:
            grants = data.get("grantData") or []
            url = (grants[0].get("serviceUrl") if grants else "") or ""
        if not url:
            self.last_error = "服务大厅未返回研究生系统入口"
            return False
        home = self.session.get(url, timeout=TIMEOUT, allow_redirects=True)
        if "Gstudent" not in home.url and "登录窗口" in home.text:
            self.last_error = "研究生系统未接受服务票据"
            return False
        # 姓名: 服务大厅接口里带着
        try:
            info = self.session.get(f"{EHALL}/getLoginUser", timeout=TIMEOUT).json()
            self.student_name = ((info or {}).get("data") or {}).get("userName") or ""
        except Exception:  # noqa: BLE001 拿不到姓名不影响使用
            self.student_name = ""
        return True

    def login(self, student_id: str, password: str) -> bool:
        self.student_id = student_id
        self.last_error = ""
        self.logged_in = False
        try:
            if not self._sso_login(student_id, password):
                return False
            if not self._enter_yjs():
                return False
        except requests.RequestException as e:
            self.last_error = f"研究生系统网络异常: {e}"
            return False
        except Exception as e:  # noqa: BLE001
            self.last_error = f"研究生系统登录异常: {e}"
            return False
        self.logged_in = True
        self.login_method = "yjs"
        return True

    # ---------------- 会话持久化 ----------------
    def _session_key(self) -> str:
        return f"{self.student_id}:{SESSION_SETTING_KEY}"

    def persist_session(self) -> None:
        try:
            from wxcloudrun import dao
            from wxcloudrun.core.session_store import serialize_cookies
            dao.set_user_setting(self.student_id, SESSION_SETTING_KEY,
                                 json.dumps({"ts": time.time(),
                                             "cookies": serialize_cookies(
                                                 self.session.cookies)},
                                            ensure_ascii=False))
        except Exception:  # noqa: BLE001 持久化失败不影响本次使用
            pass

    def try_resume(self, student_id: str) -> bool:
        """用持久化 cookie 恢复会话(免登录)。"""
        from wxcloudrun import dao
        saved = dao.get_user_setting(student_id, SESSION_SETTING_KEY)
        try:
            saved = json.loads(saved) if saved else None
        except ValueError:
            saved = None
        if not saved or time.time() - float(saved.get("ts") or 0) > 30 * 24 * 3600:
            return False
        try:
            for c in saved.get("cookies") or []:
                self.session.cookies.set(c["name"], c["value"],
                                         domain=c.get("domain"),
                                         path=c.get("path") or "/")
            home = self.session.get(f"{GSTUDENT}Default.aspx", timeout=TIMEOUT,
                                    allow_redirects=True)
        except Exception:  # noqa: BLE001
            return False
        if "Gstudent" not in home.url and "登录窗口" in home.text:
            return False
        self.student_id = student_id
        try:
            info = self.session.get(f"{EHALL}/getLoginUser", timeout=TIMEOUT).json()
            self.student_name = ((info or {}).get("data") or {}).get("userName") or ""
        except Exception:  # noqa: BLE001 姓名只是展示用
            self.student_name = ""
        self.logged_in = True
        self.login_method = "yjs-cached"
        return True

    def logout(self) -> None:
        from wxcloudrun import dao
        try:
            self.session.cookies.clear()
        finally:
            self.logged_in = False
        try:
            dao.set_user_setting(self.student_id, SESSION_SETTING_KEY, "")
        except Exception:  # noqa: BLE001
            pass

    # ---------------- 课表 ----------------
    def is_session_valid(self) -> bool:
        """轻量探测: 研究生系统默认页还能否打开(供 _require_login 校验)。"""
        if not self.logged_in:
            return False
        try:
            r = self.session.get(f"{GSTUDENT}Default.aspx", timeout=TIMEOUT,
                                 allow_redirects=True)
        except requests.RequestException:
            return True          # 网络抖动不判失效
        return not ("登录窗口" in r.text and "Gstudent" not in r.url)

    def _current_semester(self) -> str:
        """当前学期 = 研究生课表页学期列表的第一个(登录回调里会用到)。"""
        if not self._semesters:
            self.fetch_courses()
        return self._semesters[0] if self._semesters else ""

    def _menu_url(self, name: str) -> str:
        """从菜单树里取功能的当前链接(url 带一次性 EID)。"""
        if not self._menu_html:
            r = self.session.get(f"{GSTUDENT}LeftMenu.aspx", timeout=TIMEOUT,
                                 allow_redirects=True)
            self._menu_html = r.text
        m = re.search(r"name:\s*'" + re.escape(name) + r"'[^}]{0,240}?url:\s*'([^']+)'",
                      self._menu_html)
        return m.group(1) if m else ""

    def fetch_courses(self) -> dict:
        """学期课表(整学期视角, 含周次范围)。"""
        if not self.logged_in:
            return {"courses": [], "semesters": [], "timetable": []}
        target = self._menu_url("学期课表信息查询")
        if not target:
            self.last_error = "研究生系统菜单里没有『学期课表信息查询』"
            return {"courses": [], "semesters": [], "timetable": []}
        page = self.session.get(urljoin(GSTUDENT, target), timeout=TIMEOUT,
                                allow_redirects=True)
        if "登录窗口" in page.text and "Gstudent" not in page.url:
            self.logged_in = False
            self.last_error = "研究生系统会话已失效"
            return {"courses": [], "semesters": [], "timetable": []}
        data = parse_yjs_week_table(page.text)
        if data.get("semesters"):
            self._semesters = data["semesters"]
        return data

    def fetch_grades(self) -> dict:
        """课程成绩(研究生不做绩点计算, 只给成绩与学分进度)。"""
        empty = {"stats": [], "rows": [], "semesters": []}
        if not self.logged_in:
            return empty
        target = self._menu_url("课程成绩信息查询")
        if not target:
            self.last_error = "研究生系统菜单里没有『课程成绩信息查询』"
            return empty
        page = self.session.get(urljoin(GSTUDENT, target), timeout=TIMEOUT,
                                allow_redirects=True)
        if "登录窗口" in page.text and "Gstudent" not in page.url:
            self.logged_in = False
            self.last_error = "研究生系统会话已失效"
            return empty
        return parse_yjs_grade_page(page.text)

    def fetch_exams(self) -> dict:
        """学期考试信息(研究生系统「学期考试信息查询」)。"""
        empty = {"stats": [], "rows": [], "semesters": []}
        if not self.logged_in:
            return empty
        target = self._menu_url("学期考试信息查询")
        if not target:
            self.last_error = "研究生系统菜单里没有『学期考试信息查询』"
            return empty
        page = self.session.get(urljoin(GSTUDENT, target), timeout=TIMEOUT,
                                allow_redirects=True)
        if "登录窗口" in page.text and "Gstudent" not in page.url:
            self.logged_in = False
            self.last_error = "研究生系统会话已失效"
            return empty
        # 与成绩页同构: 表格行 + 学期列表
        return parse_yjs_grade_page(page.text)
