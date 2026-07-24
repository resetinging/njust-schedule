"""
南京理工大学强智教务系统客户端
===================================
NJUST 教务路径前缀: /njlgdx/（不是 /jsxsd/）
登录: 8080/Logon.do → POST 9080/LoginToXk?method=jwxt
"""

import logging
import requests
import re
import json
import base64
import time
import os
from typing import Optional, Tuple
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

from config import (
    JW_BASE_8080, JW_BASE_9080, JW_PATH_PREFIX,
    JW_LOGON_PAGE, JW_SCHEDULE_URL, JW_EXAM_QUERY, JW_EXAM_LIST,
    JW_EVAL_PAGE, JW_GRADE_QUERY, JW_GRADE_LIST, JW_CET_LIST,
    JW_APP_DO, JW_CAPTCHA_URLS, BIG_PERIOD_MAP,
    HTTP_TIMEOUT, HTTP_HEADERS,
    SSO_BASE, SSO_LOGIN_URL,
    WEBVPN_BASE, WEBVPN_PREFIX_JW,
    JW_BASE_8080_VPN, JW_BASE_9080_VPN, DEBUG_WEBVPN,
)

# === 加密模块（WebVPN 密码加密） ===
try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad as aes_pad
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False

# === URL 别名（保持向后兼容） ===
BASE_URL = JW_BASE_8080
BASE_9080 = JW_BASE_9080
URL_LOGON_PAGE = JW_LOGON_PAGE
URL_LOGON_SESS = f"{BASE_URL}/Logon.do?method=logon&flag=sess"
URL_LOGIN_9080 = f"{BASE_9080}{JW_PATH_PREFIX}/xk/LoginToXk"
URL_APP_DO = JW_APP_DO
URL_SCHEDULE_HTML = JW_SCHEDULE_URL
URL_EXAM_QUERY = JW_EXAM_QUERY
URL_EXAM_LIST = JW_EXAM_LIST
URL_EVAL_PAGE = JW_EVAL_PAGE
URL_GRADE_QUERY = JW_GRADE_QUERY
URL_GRADE_LIST = JW_GRADE_LIST
URL_CET_LIST = JW_CET_LIST
URL_MAIN_PAGE = f"{BASE_9080}{JW_PATH_PREFIX}/framework/main.jsp"
URL_CAPTCHA_CANDIDATES = JW_CAPTCHA_URLS
HEADERS = HTTP_HEADERS
TIMEOUT = HTTP_TIMEOUT


class ParserMixin:
    def get_schedule(self, semester: str = "", week: int = 0) -> list[dict]:
        if not self.logged_in:
            self.last_error = "未登录"
            return []
        return self._schedule_api(semester, week) or self._schedule_html(semester)

    def _schedule_api(self, semester: str, week: int) -> list[dict]:
        try:
            if not semester:
                semester = self._current_semester()
            params = {"method": "getKbcxAzc", "xh": self.student_id, "xnxqid": semester}
            if week > 0:
                params["zc"] = str(week)
            resp = self._post(
                URL_APP_DO, params=params,
                headers={"token": self.token} if self.token else {},
                timeout=TIMEOUT)
            data = resp.json()
            items = data if isinstance(data, list) else data.get("data", [])
            return self._parse_schedule(items) if isinstance(items, list) else []
        except Exception:
            return []

    def _schedule_html(self, semester: str) -> list[dict]:
        """NJUST 课表 HTML 解析 — 从主页链接获取正确的 Ves632DSdyV 参数"""
        try:
            # Debug: 看看当前 cookie 状态
            self._log(f"[课表] 请求前 cookies: { {k: v[:20] for k, v in self.session.cookies.items()} }")

            # 先访问主页，提取课表链接中的 Ves632DSdyV 参数
            main_resp = self._get(
                URL_MAIN_PAGE,
                timeout=TIMEOUT, allow_redirects=True,
            )
            self._log(f"[课表] 主页 GET → status={main_resp.status_code} "
                  f"len={len(main_resp.text)} title={self._page_title(main_resp)}")
            real_schedule_url = URL_SCHEDULE_HTML  # 默认
            m = re.search(r'xskb/xskb_list\.do\?([^"\']+)', main_resp.text)
            if m:
                real_schedule_url = f"{BASE_9080}/njlgdx/xskb/xskb_list.do?{m.group(1)}"
                self._log(f"[课表] 从主页提取真实URL参数: {m.group(1)[:50]}")
            else:
                self._log(f"[课表] [WARN] 未在主页找到课表链接，使用默认URL")

            resp = self._get(real_schedule_url, timeout=TIMEOUT, allow_redirects=True)
            self._log(f"[课表] 课表 GET → status={resp.status_code} "
                  f"len={len(resp.text)} title={self._page_title(resp)}")

            if resp.status_code != 200 or len(resp.text) < 2000:
                self.last_error = "课表页面访问失败，请重新登录"
                return []

            soup = BeautifulSoup(resp.text, "lxml")

            # ★ 合并两个表格：kbtable(周次/教室) + dataList(精确小节)
            grid = soup.find("table", id="kbtable")
            data_table = soup.find("table", id="dataList")

            if grid and data_table:
                courses = self._parse_merged(grid, data_table)
                if courses:
                    self._log(f"[课表] 合并解析完成: {len(courses)} 条")
                    return courses

            # 降级
            if data_table:
                courses = self._parse_datalist(data_table)
                if courses: return courses
            if grid:
                courses = self._parse_kbtable(grid, {})
                if courses: return courses

            self.last_error = "课表表格未找到"
            self._log(f"[课表] 所有表格: {[t.get('id', t.get('class', '')) for t in soup.find_all('table')[:10]]}")
            return []
        except Exception as e:
            print(f"[课表HTML] {e}")
            import traceback; traceback.print_exc()
            return []

    def _parse_datalist(self, table) -> list[dict]:
        """解析 dataList 表格"""
        courses = []
        rows = table.find_all("tr")
        for row in rows[1:]:  # 跳过表头
            cells = row.find_all("td")
            if len(cells) < 10:
                continue
            texts = [c.get_text(strip=True) for c in cells]

            course_name = texts[3]  # 课程名称
            teacher = texts[4]      # 教师
            time_text = texts[5]    # 时间（如 "星期二(04-05小节)<br/>星期五(08-09小节)"）
            credits = texts[6]      # 学分
            location_text = texts[7]  # 地点
            course_type = texts[8]  # 课程属性

            if not course_name:
                continue

            # 解析时间列：从原始 HTML 中用正则提取所有 "星期X(数字-数字小节)"
            raw_time = str(cells[5])
            raw_loc = str(cells[7])
            time_matches = re.findall(
                r'星期([一二三四五六日])\((\d+)-(\d+)小节\)', raw_time)
            # 从原始 HTML 按 <br> 分割取教室
            loc_splits = re.split(r'<br\s*/?>|</br>', raw_loc)
            location_list = []
            for s in loc_splits:
                txt = re.sub(r'<[^>]+>', '', s).strip()
                if txt:
                    location_list.append(txt)
            # 如果没解析到，降级用逗号分割
            if not location_list:
                location_list = [l.strip() for l in re.split(r'[,，]',
                    cells[7].get_text(strip=True)) if l.strip()]

            day_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7}
            for i, (day_char, start_str, end_str) in enumerate(time_matches):
                day = day_map.get(day_char, 0)
                start = int(start_str)
                end = int(end_str)
                loc = location_list[i] if i < len(location_list) else ""
                if not loc and location_list:
                    loc = location_list[0]  # 如果教室不够分配，用第一个

                courses.append({
                    "name": course_name,
                    "teacher": teacher,
                    "classroom": loc,
                    "day": day,
                    "start": start,
                    "end": end,
                    "weeks": "",
                    "week_type": 0,
                    "credits": credits,
                    "course_type": course_type,
                    "raw": dict(zip(
                        ["num", "course_id", "class_seq", "name", "teacher",
                         "time", "credits", "location", "type", "stage"],
                        texts
                    )),
                })

        print(f"[课表] dataList 解析完成: {len(courses)} 条")
        return courses

    def _parse_merged(self, grid, data_table) -> list[dict]:
        """
        合并 kbtable（周次/教室/教师） + dataList（精确小节/学分/类型）
        kbtable 有正确的周次和教室分配，dataList 有精准的小节号
        """
        # Step 1: 从 dataList 提取精确小节信息
        day_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7}
        period_info = {}  # {(name, day): (start, end, credits, course_type)}
        dl_rows = data_table.find_all("tr")
        for row in dl_rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 9:
                continue
            name = cells[3].get_text(strip=True)
            credits = cells[6].get_text(strip=True)
            ctype = cells[8].get_text(strip=True)
            raw_time = str(cells[5])
            matches = re.findall(r'星期([一二三四五六日])\((\d+)-(\d+)小节\)', raw_time)
            for day_char, s, e in matches:
                d = day_map.get(day_char, 0)
                period_info[(name, d)] = (int(s), int(e), credits, ctype)

        # Step 2: 从 kbtable 提取课程条目（含周次、教室），用 period_info 补小节
        # 大节 → 小节（粗略，period_info 会覆盖）
        block_map = BIG_PERIOD_MAP
        rows = grid.find_all("tr")
        # 解析列映射
        hdr = rows[0].find_all(["td", "th"])
        col_day = {}
        for i, c in enumerate(hdr):
            for d, n in enumerate("一二三四五六日", 1):
                if n in c.get_text():
                    col_day[i] = d
                    break

        courses = []
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            # 大节标签
            label = cells[0].get_text(strip=True)
            rough = None
            for k, v in block_map.items():
                if k in label:
                    rough = v
                    break
            if not rough:
                continue

            for ci, cell in enumerate(cells[1:], 1):
                if ci not in col_day:
                    continue
                day = col_day[ci]

                # 找详细 div
                for div in cell.find_all("div", class_="kbcontent"):
                    raw = str(div)
                    entries = re.split(r'-{10,}', raw)
                    for entry in entries:
                        if not entry.strip() or '&nbsp;' in entry:
                            continue
                        soup = BeautifulSoup(entry, "lxml")
                        lines = [l.strip() for l in soup.get_text("\n", strip=True).split("\n") if l.strip()]
                        if len(lines) < 2:
                            continue
                        name = lines[0]

                        # ★ 用 font title 属性提取
                        teacher = weeks = classroom = ""
                        for ft in soup.find_all("font"):
                            t = ft.get("title", "")
                            v = ft.get_text(strip=True)
                            if "老师" in t or "教师" in t:
                                teacher = v
                            elif "周次" in t:
                                weeks = v.replace("(周)", "").strip()
                            elif "教室" in t:
                                classroom = v
                            elif "分组名" in t and not teacher:
                                teacher = v

                        if not name or name == '\xa0':
                            continue

                        # ★ 从 period_info 获取精确小节
                        p_start, p_end = rough
                        credits = ctype = ""
                        exact = period_info.get((name, day))
                        if exact:
                            p_start, p_end, credits, ctype = exact

                        courses.append({
                            "name": name,
                            "teacher": teacher,
                            "classroom": classroom,
                            "day": day,
                            "start": p_start,
                            "end": p_end,
                            "weeks": weeks,
                            "week_type": 0,
                            "credits": credits,
                            "course_type": ctype,
                            "raw": {},
                        })

        return courses

    def _parse_kbtable(self, table, period_info: dict = None) -> list[dict]:
        """
        解析视觉课表 kbtable — 包含完整的周次、教室、教师信息
        结构：每行=一个大节，每列=星期几，kbcontent div 内含详细课程信息
        """
        courses = []
        rows = table.find_all("tr")
        if len(rows) < 2:
            return []

        # 表头解析星期列映射
        hdr = rows[0].find_all(["td", "th"])
        day_map = {}
        for i, c in enumerate(hdr):
            for d, n in enumerate("一二三四五六日", 1):
                if n in c.get_text():
                    day_map[i] = d
                    break
        print(f"[kbtable] 列映射: {day_map}")

        # 大节 → 小节映射（从 th 文本提取）
        # NJUST 大节 → 小节映射
        # 上午8:00起, 下午14:00起, 晚上19:00起
        # 大节内小节间隔5min, 大节间隔15min
        period_map = BIG_PERIOD_MAP

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            # 第一列是时段标签
            period_label = cells[0].get_text(strip=True)
            period_range = None
            for key, val in period_map.items():
                if key in period_label:
                    period_range = val
                    break
            if not period_range:
                continue
            p_start, p_end = period_range

            # 遍历每天
            for ci, cell in enumerate(cells[1:], 1):
                if ci not in day_map:
                    continue
                day = day_map[ci]

                # 取详细 div（class="kbcontent"，不是 kbcontent1）
                detail_divs = cell.find_all("div", class_="kbcontent")
                for div in detail_divs:
                    # 用 --------------------- 分割多个课程条目
                    raw = str(div)
                    entries = re.split(r'-{10,}', raw)
                    for entry in entries:
                        if not entry.strip() or '&nbsp;' in entry:
                            continue
                        soup = BeautifulSoup(entry, "lxml")
                        # 获取纯文本第一行作为课程名
                        text = soup.get_text("\n", strip=True)
                        lines = [l.strip() for l in text.split("\n") if l.strip()]
                        if len(lines) < 2:
                            continue
                        name = lines[0]

                        # ★ 用 font 标签的 title 属性提取各字段
                        teacher = ""
                        weeks = ""
                        classroom = ""
                        for font_tag in soup.find_all("font"):
                            title_attr = font_tag.get("title", "")
                            val = font_tag.get_text(strip=True)
                            if "老师" in title_attr or "教师" in title_attr:
                                teacher = val
                            elif "周次" in title_attr:
                                weeks = val.replace("(周)", "").strip()
                            elif "教室" in title_attr:
                                classroom = val
                            elif "分组名" in title_attr:
                                if not teacher:
                                    teacher = val

                        if name and name != '\xa0':
                            # 从 dataList 获取精确小节号
                            if period_info:
                                exact = period_info.get((name, day))
                                if exact:
                                    p_start, p_end = exact

                            courses.append({
                                "name": name,
                                "teacher": teacher,
                                "classroom": classroom,
                                "day": day,
                                "start": p_start,
                                "end": p_end,
                                "weeks": weeks,
                                "week_type": 0,
                                "credits": "",
                                "course_type": "",
                                "raw": {},
                            })

        return courses

    def _parse_schedule(self, items: list) -> list[dict]:
        courses = []
        for item in items:
            if not isinstance(item, dict):
                continue
            kcsj = str(item.get("kcsj", ""))
            d = s = e = 0
            if len(kcsj) >= 5:
                try:
                    d = int(kcsj[0]); s = int(kcsj[1:3]); e = int(kcsj[3:5])
                except ValueError:
                    pass
            sjbz = str(item.get("sjbz", "0"))
            wt = 1 if sjbz == "1" else (2 if sjbz == "2" else 0)
            courses.append({
                "name": str(item.get("kcmc", "")).strip(),
                "teacher": str(item.get("jsxm", "") or item.get("jsm", "")).strip(),
                "classroom": str(item.get("jsmc", "") or item.get("jsm", "")).strip(),
                "day": d, "start": s, "end": e,
                "weeks": str(item.get("kkzc", "") or item.get("zcsm", "")),
                "week_type": wt,
                "credits": item.get("xf", ""),
                "course_type": str(item.get("kclb", "") or item.get("kcType", "")).strip(),
                "raw": item,
            })
        return courses

    # ================================================================
    # 考试
    # ================================================================

    def get_exams(self, semester: str = "") -> list[dict]:
        if not self.logged_in:
            self.last_error = "未登录"
            return []
        # 先尝试 API，失败则降级到 HTML
        result = self._exams_api(semester)
        if result:
            return result
        # API 失败是预期的（NJUST 可能不支持），清除错误信息
        self.last_error = ""
        return self._exams_html(semester)

    def _exams_api(self, semester: str) -> list[dict]:
        try:
            if not semester:
                semester = self._current_semester()
            resp = self._post(
                URL_APP_DO,
                params={"method": "getXsksap", "xh": self.student_id, "xnxqid": semester},
                headers={"token": self.token} if self.token else {},
                timeout=TIMEOUT)
            data = resp.json()
            items = data if isinstance(data, list) else data.get("data", [])
            if not isinstance(items, list):
                return []
            exams = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                exams.append({
                    "course_name": str(it.get("kcmc", "")).strip(),
                    "date": str(it.get("ksrq", "") or it.get("examDate", "")).strip(),
                    "time": str(it.get("kssj", "") or it.get("examTime", "")).strip(),
                    "location": str(it.get("ksdd", "") or it.get("examRoom", "")).strip(),
                    "seat": str(it.get("zwh", "") or it.get("seatNum", "")).strip(),
                    "type": str(it.get("kslx", "") or "期末考试").strip(),
                })
            return exams
        except Exception as e:
            self.last_error = f"考试API请求失败: {e}"
            return []

    def _exams_html(self, semester: str) -> list[dict]:
        """解析考试安排列表页面（HTML 表格）
        流程：查询页提交表单 → 列表页显示数据
        表格结构：序号 | 考试场次 | 课程编号 | 课程名称 | 考试时间 | 考场 | 座位号
        """
        def _parse_table(soup):
            t = soup.find("table", id="dataList") or soup.find("table", class_="Nsb_r_list")
            if not t:
                return None
            rows = t.find_all("tr")[1:]
            exams = []
            for row in rows:
                cells = row.find_all(["td", "th"])
                if len(cells) < 6:
                    continue
                texts = [c.get_text(strip=True) for c in cells]
                course_name = texts[3] if len(texts) > 3 else ""
                if not course_name:
                    continue
                raw_time = texts[4] if len(texts) > 4 else ""
                if " " in raw_time:
                    parts = raw_time.split(" ", 1)
                    date, time = parts[0].strip(), parts[1].strip()
                else:
                    date, time = raw_time, ""
                exams.append({
                    "course_name": course_name,
                    "date": date,
                    "time": time,
                    "location": texts[5] if len(texts) > 5 else "",
                    "seat": texts[6] if len(texts) > 6 else "",
                    "type": "期末考试",
                })
            return exams

        try:
            # 策略1：先访问查询页，获取表单，提交查询
            resp = self._get(URL_EXAM_QUERY, timeout=TIMEOUT)
            soup = BeautifulSoup(resp.text, "lxml")
            # 查找表单
            form = soup.find("form")
            if form:
                action = form.get("action", "")
                form_data = {}
                for inp in form.find_all("input"):
                    name = inp.get("name", "")
                    value = inp.get("value", "")
                    if name:
                        form_data[name] = value
                for sel in form.find_all("select"):
                    name = sel.get("name", "")
                    if name:
                        # 选中学期对应的 option
                        selected = sel.find("option", selected=True)
                        options = sel.find_all("option")
                        if options:
                            # 优先匹配当前学期
                            matched = None
                            for opt in options:
                                v = opt.get("value", "")
                                if semester and semester in v:
                                    matched = v
                                    break
                            if matched:
                                form_data[name] = matched
                            elif selected:
                                form_data[name] = selected.get("value", "")
                            else:
                                form_data[name] = options[0].get("value", "")
                # 如果有 action，构造完整 URL
                if action:
                    if action.startswith("/"):
                        target_url = f"{BASE_9080}{action}"
                    elif action.startswith("http"):
                        target_url = action
                    else:
                        target_url = f"{BASE_9080}/njlgdx/xsks/{action}"
                else:
                    target_url = URL_EXAM_LIST
                resp = self._post(target_url, data=form_data, timeout=TIMEOUT)
            else:
                # 没有表单，可能直接重定向了
                resp = self._get(URL_EXAM_LIST, timeout=TIMEOUT)

            soup = BeautifulSoup(resp.text, "lxml")
            result = _parse_table(soup)
            if result:
                return result

            # 策略2：直接 POST 学期参数到列表页
            resp = self._post(URL_EXAM_LIST,
                data={"xnxqid": semester, "method": "query"},
                timeout=TIMEOUT)
            soup = BeautifulSoup(resp.text, "lxml")
            result = _parse_table(soup)
            if result:
                return result

            # 策略3：GET 列表页（可能查询页已设置会话状态）
            resp = self._get(URL_EXAM_LIST, timeout=TIMEOUT)
            soup = BeautifulSoup(resp.text, "lxml")
            result = _parse_table(soup)
            if result:
                return result

            # 全部失败，诊断
            title = soup.find("title")
            page_title = title.get_text(strip=True) if title else "无标题"
            has_login = "logon" in resp.text.lower() or "登录" in resp.text
            form_count = len(soup.find_all("form"))
            table_count = len(soup.find_all("table"))
            self._log(f"[考试HTML] 未找到数据表格")
            self._log(f"  页面标题: {page_title}")
            self._log(f"  响应长度: {len(resp.text)}")
            self._log(f"  表单数量: {form_count}, 表格数量: {table_count}")
            self._log(f"  疑似登录页: {has_login}")
            self._log(f"  疑似登录页: {has_login}")
            if has_login:
                self.last_error = "考试页面需要重新登录，请先在设置页登录"
            else:
                self.last_error = f"考试页面解析失败（表格数={table_count}），可能本学期暂无考试"
            return []
        except Exception as e:
            self.last_error = f"考试HTML解析失败: {e}"
            return []

    # ================================================================
    # 成绩查询
    # ================================================================

    def get_grades(self, semester: str = "") -> list[dict]:
        """获取成绩数据"""
        if not self.logged_in:
            self.last_error = "未登录"
            return []
        # 先尝试 API，失败则降级到 HTML
        result = self._grades_api(semester)
        if result:
            return result
        self.last_error = ""
        return self._grades_html(semester)

    def _grades_api(self, semester: str) -> list[dict]:
        """通过 app.do API 获取成绩"""
        try:
            if not semester:
                semester = self._current_semester()
            resp = self._post(
                URL_APP_DO,
                params={"method": "getCjcx", "xh": self.student_id, "xnxqid": semester},
                headers={"token": self.token} if self.token else {},
                timeout=TIMEOUT)
            data = resp.json()
            items = data if isinstance(data, list) else data.get("data", [])
            if not isinstance(items, list):
                return []
            grades = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                grades.append({
                    "academic_year": str(it.get("xn", "") or it.get("xnm", "")).strip(),
                    "semester": str(it.get("xq", "") or it.get("xqm", "")).strip(),
                    "course_code": str(it.get("kcdm", "") or it.get("kch", "")).strip(),
                    "course_name": str(it.get("kcmc", "")).strip(),
                    "score": str(it.get("cj", "") or it.get("kscj", "")).strip(),
                    "credit": self._to_float(it.get("xf", 0)),
                    "grade_point": self._to_float(it.get("jd", 0) or it.get("jdn", 0)),
                    "course_type": str(it.get("kclb", "") or it.get("kclbmc", "")).strip(),
                    "exam_type": str(it.get("kslx", "") or it.get("khfsmc", "") or "正常考试").strip(),
                })
            return grades
        except Exception as e:
            self.last_error = f"成绩API请求失败: {e}"
            return []

    def _grades_html(self, semester: str) -> list[dict]:
        """解析成绩页面（HTML 表格）"""
        def _parse_table(soup, label=""):
            """通过表头行确定列索引，然后逐行提取"""
            # 候选表格
            candidates = []
            candidates.append(soup.find("table", id="dataList"))
            candidates.append(soup.find("table", class_="Nsb_r_list"))
            candidates.extend(soup.find_all("table", class_=lambda c: c and "Nsb" in c if c else False))
            # 兜底：所有表格
            for tbl in soup.find_all("table"):
                if tbl not in candidates:
                    candidates.append(tbl)

            for t in candidates:
                if t is None:
                    continue
                rows = t.find_all("tr")
                if len(rows) < 2:
                    continue
                # 检查表头
                hdr_cells = rows[0].find_all(["td", "th"])
                hdr_texts = [c.get_text(strip=True) for c in hdr_cells]
                print(f"[成绩] {label} 候选表格: {len(rows)}行, 表头: {hdr_texts[:12]}")

                # 必须有至少一个成绩相关关键词
                hdr_joined = " ".join(hdr_texts)
                if not any(kw in hdr_joined for kw in ("课程名称", "课程", "成绩", "学分", "绩点", "分数")):
                    continue

                # 建立列映射（精确匹配，避免 "成绩" 误匹配 "成绩标识"）
                col = {}
                for i, txt in enumerate(hdr_texts):
                    if txt == "课程名称":
                        col["course_name"] = i
                    elif txt == "课程编号" or txt == "课程代码":
                        col["course_code"] = i
                    elif txt == "成绩":
                        col["score"] = i
                    elif txt == "学分":
                        col["credit"] = i
                    elif txt == "绩点":
                        col["grade_point"] = i
                    elif txt == "课程属性":
                        col["course_type"] = i
                    elif txt == "课程性质":
                        col["course_nature"] = i
                    elif txt in ("考核方式", "考试类型", "考试性质"):
                        col["exam_type"] = i
                    elif txt in ("开课学期", "学年学期"):
                        col["semester"] = i

                # 兜底：强智教务常见布局（含成绩标识列）
                # 序号|开课学期|课程编号|课程名称|成绩|成绩标识|学分|总学时|考核方式|课程属性|课程性质
                if "course_name" not in col:
                    col = {"course_name": 3, "score": 4, "credit": 6,
                           "grade_point": None, "course_type": 9, "exam_type": 8,
                           "course_nature": 10, "course_code": 2, "semester": 1}
                    print(f"[成绩] {label} 表头匹配失败，使用固定位置")
                else:
                    print(f"[成绩] {label} 表头映射: {col}")
                # 没有绩点列时设为 None（此教务系统无绩点）
                if "grade_point" not in col:
                    col["grade_point"] = None

                def _get(key, default=""):
                    idx = col.get(key)
                    if idx is not None and idx < len(hdr_cells):
                        return hdr_cells[idx].get_text(strip=True) if False else ""
                    return default
                # 重新定义 _get 使用实际数据行
                break
            else:
                print(f"[成绩] {label} 未找到合适的表格（共检查 {len(candidates)} 个候选）")
                return None

            # 用这个表格的数据行解析
            grades = []
            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                texts = [c.get_text(strip=True) for c in cells]
                if len(texts) < 5:
                    continue

                def _get(key, default=""):
                    idx = col.get(key)
                    if idx is not None and idx < len(texts):
                        return texts[idx]
                    return default

                course_name = _get("course_name")
                if not course_name:
                    continue
                if any(kw in course_name for kw in ("平均", "合计", "必修课合计")):
                    continue

                sem_raw = _get("semester")
                ay, sm = "", ""
                if sem_raw and "-" in sem_raw:
                    parts = sem_raw.split("-")
                    if len(parts) >= 2:
                        ay = f"{parts[0]}-{parts[1]}"
                        sm = parts[2] if len(parts) > 2 else ""

                grades.append({
                    "academic_year": ay,
                    "semester": sm,
                    "course_code": _get("course_code"),
                    "course_name": course_name,
                    "score": _get("score"),
                    "credit": self._to_float(_get("credit")),
                    "grade_point": self._to_float(_get("grade_point")),
                    "course_type": _get("course_type"),
                    "course_nature": _get("course_nature"),
                    "exam_type": _get("exam_type") or "正常考试",
                })

            print(f"[成绩] {label} 解析完成: {len(grades)} 条")
            if grades:
                print(f"[成绩] 首条: {grades[0]}")
            return grades if grades else None

        # =================================================================
        # 策略执行
        # =================================================================
        strategies = []

        # 策略1: GET 查询页（可能直接显示结果）
        try:
            print(f"[成绩] 策略1: GET {URL_GRADE_QUERY}")
            resp = self._get(URL_GRADE_QUERY, timeout=TIMEOUT)
            print(f"[成绩]   状态={resp.status_code} 长度={len(resp.text)} "
                  f"标题={self._page_title(resp)}")
            soup = BeautifulSoup(resp.text, "lxml")

            # 如果有表单，收集表单数据
            form = soup.find("form")
            if form:
                action = form.get("action", "")
                form_data = {}
                for inp in form.find_all("input"):
                    n, v = inp.get("name", ""), inp.get("value", "")
                    if n:
                        form_data[n] = v
                for sel in form.find_all("select"):
                    n = sel.get("name", "")
                    if n:
                        opts = sel.find_all("option")
                        if opts:
                            picked = None
                            for o in opts:
                                ov = o.get("value", "")
                                if semester and semester in ov:
                                    picked = ov; break
                            if not picked:
                                s = sel.find("option", selected=True)
                                picked = s.get("value", "") if s else opts[0].get("value", "")
                            form_data[n] = picked
                # 构造目标 URL
                if action:
                    if action.startswith("/"):
                        target = f"{BASE_9080}{action}"
                    elif action.startswith("http"):
                        target = action
                    else:
                        target = f"{BASE_9080}/njlgdx/kscj/{action}"
                else:
                    target = URL_GRADE_LIST

                strategies.append(("POST表单", lambda: self._post(target, data=form_data, timeout=TIMEOUT)))
                print(f"[成绩]   找到表单, action={action}, 目标={target}, form_data keys={list(form_data.keys())}")

            # 先试试查询页直接有没有表格
            result = _parse_table(soup, "策略1直接")
            if result:
                return result

            # 策略1.5：如果查询页是带学期参数直接显示，尝试带 semester 的 GET
            if semester:
                strategies.append(("GET列表页(带学期)", lambda: self._get(
                    f"{URL_GRADE_LIST}?xnxqid={semester}", timeout=TIMEOUT)))
        except Exception as e:
            print(f"[成绩] 策略1异常: {e}")

        # 策略2: 直接 POST 列表页
        strategies.append(("POST列表页", lambda: self._post(
            URL_GRADE_LIST, data={"xnxqid": semester}, timeout=TIMEOUT)))

        # 策略3: GET 列表页
        strategies.append(("GET列表页", lambda: self._get(
            URL_GRADE_LIST, timeout=TIMEOUT)))

        # 执行策略
        last_soup = None
        for sname, sfn in strategies:
            print(f"[成绩] {sname}...")
            try:
                resp = sfn()
                print(f"[成绩]   状态={resp.status_code} 长度={len(resp.text)} "
                      f"标题={self._page_title(resp)}")
                soup = BeautifulSoup(resp.text, "lxml")
                last_soup = soup
                result = _parse_table(soup, sname)
                if result:
                    return result
            except Exception as e:
                print(f"[成绩]   {sname} 异常: {e}")

        # 全部失败，诊断
        self._log(f"[成绩] ===== 所有策略均失败 =====")
        if last_soup:
            tables = last_soup.find_all("table")
            self._log(f"[成绩] 总表格数: {len(tables)}")
            for i, tbl in enumerate(tables[:5]):
                rows = tbl.find_all("tr")
                r0 = rows[0].get_text("|", strip=True)[:120] if rows else "(空)"
                self._log(f"[成绩]   表格#{i}: {len(rows)}行, 首行: {r0}")
            has_login = "logon" in str(last_soup).lower() or "登录" in str(last_soup)
            if has_login:
                self.last_error = "成绩页面需要重新登录，请先在设置页登录"
            else:
                self.last_error = "成绩解析失败"
        else:
            self.last_error = "无法访问成绩页面"
        return []

    @staticmethod
    def _to_float(val) -> float:
        """安全转换为 float"""
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0

    # ================================================================
    # 等级考试（四六级）
    # ================================================================

    def get_cet_scores(self) -> list[dict]:
        """获取四六级成绩

        从 /njlgdx/kscj/djkscj_list 页面抓取等级考试成绩，
        解析 #dataList 表格，提取 CET4/CET6 的最高分。

        返回: [{type: "CET4"/"CET6", score: float, exam_date: str}, ...]
        """
        import re
        try:
            resp = self._get(URL_CET_LIST, timeout=TIMEOUT)
            if resp.status_code != 200:
                print(f"[CET] 请求失败: {resp.status_code}")
                return []
            print(f"[CET] GET {URL_CET_LIST} → status={resp.status_code} len={len(resp.text)}")
        except Exception as e:
            print(f"[CET] 请求异常: {e}")
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        table = soup.find("table", id="dataList")
        if not table:
            print("[CET] 未找到 #dataList 表格")
            return []

        rows = table.find_all("tr")
        if len(rows) < 3:  # 2行表头 + 至少1行数据
            print(f"[CET] 表格行数不足: {len(rows)}")
            return []

        cet_records = []  # [(type, score, date), ...]

        for row in rows[2:]:  # 跳过前2行表头
            cells = row.find_all("td")
            if len(cells) < 9:
                continue

            course_name = cells[1].get_text(strip=True)  # 考级课程(等级)
            total_score_text = cells[4].get_text(strip=True)  # 分数类 > 总成绩
            exam_date = cells[8].get_text(strip=True)  # 考级时间

            # 识别 CET4/CET6
            if "CET6" in course_name:
                cet_type = "CET6"
            elif "CET4" in course_name:
                cet_type = "CET4"
            else:
                continue  # 跳过英语分级考试等

            try:
                score = float(total_score_text)
            except (ValueError, TypeError):
                continue

            if score <= 0:
                continue  # 0分表示未参加

            cet_records.append((cet_type, score, exam_date))
            print(f"[CET]   解析: {cet_type} {score}分 {exam_date}")

        if not cet_records:
            print("[CET] 未找到有效四六级成绩")
            return []

        # 取每种类型的最高分
        best = {}
        for t, s, d in cet_records:
            if t not in best or s > best[t][0]:
                best[t] = (s, d)

        result = []
        for cet_type in ("CET4", "CET6"):
            if cet_type in best:
                s, d = best[cet_type]
                result.append({"type": cet_type, "score": s, "exam_date": d})

        print(f"[CET] 汇总: {result}")
        return result

    # ================================================================
    # 工具
    # ================================================================

    def _current_semester(self) -> str:
        y, m = time.localtime().tm_year, time.localtime().tm_mon
        if m >= 9: return f"{y}-{y+1}-1"
        elif m >= 2: return f"{y-1}-{y}-2"
        else: return f"{y-1}-{y}-1"

    def get_semester_list(self) -> list[str]:
        cur = self._current_semester()
        try:
            by = int(cur.split("-")[0])
        except Exception:
            by = 2025
        return [f"{y}-{y+1}-{s}" for y in range(by-2, by+3) for s in (1, 2)]

    # ================================================================
    # 教学评价
    # ================================================================

    def get_evaluations(self, semester: str = "") -> list[dict]:
        """获取教学评价列表"""
        if not self.logged_in:
            self.last_error = "未登录"
            return []
        return self._eval_html(semester)

    def _eval_html(self, semester: str = "") -> list[dict]:
        """解析教学评价页面
        表格结构：序号 | 学年学期 | 评价分类 | 评价批次 | 开始时间 | 结束时间 | 是否已完成 | 操作
        """
        try:
            resp = self._get(URL_EVAL_PAGE, timeout=TIMEOUT)
            soup = BeautifulSoup(resp.text, "lxml")
            table = soup.find("table", class_="Nsb_r_list")
            if not table:
                self.last_error = "评价页面未找到数据表格"
                self._log(f"[评价] 未找到 Nsb_r_list 表格，表格数={len(soup.find_all('table'))}")
                return []
            rows = table.find_all("tr")[1:]
            evals = []
            for row in rows:
                cells = row.find_all("td")
                if len(cells) < 7:
                    continue
                texts = [c.get_text(strip=True) for c in cells]
                batch_name = texts[3] if len(texts) > 3 else ""
                if not batch_name:
                    continue
                start_date = texts[4] if len(texts) > 4 else ""
                end_date = texts[5] if len(texts) > 5 else ""
                is_done = texts[6] if len(texts) > 6 else ""
                items = []
                if len(cells) > 7:
                    for a in cells[7].find_all("a"):
                        items.append({
                            "name": a.get_text(strip=True),
                            "url": a.get("href", ""),
                        })
                evals.append({
                    "semester": texts[1] if len(texts) > 1 else "",
                    "category": texts[2] if len(texts) > 2 else "",
                    "batch": batch_name,
                    "start_date": start_date,
                    "end_date": end_date,
                    "is_done": is_done == "是",
                    "items": items,
                })
            return evals
        except Exception as e:
            self.last_error = f"评价解析失败: {e}"
            return []

