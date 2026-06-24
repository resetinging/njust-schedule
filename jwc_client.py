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
from typing import Optional, Tuple
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

from config import (
    JW_BASE_8080, JW_BASE_9080, JW_PATH_PREFIX,
    JW_LOGON_PAGE, JW_SCHEDULE_URL, JW_EXAM_QUERY, JW_EXAM_LIST,
    JW_EVAL_PAGE, JW_APP_DO, JW_CAPTCHA_URLS, BIG_PERIOD_MAP,
    HTTP_TIMEOUT, HTTP_HEADERS,
)

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
URL_MAIN_PAGE = f"{BASE_9080}{JW_PATH_PREFIX}/framework/main.jsp"
URL_CAPTCHA_CANDIDATES = JW_CAPTCHA_URLS
HEADERS = HTTP_HEADERS
TIMEOUT = HTTP_TIMEOUT


class JWCClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.token = None
        self.student_id = None
        self.student_name = None
        self.logged_in = False
        self.login_method = ""
        self.last_error = ""
        self._captcha_ready = False
        self._active_captcha_url = URL_CAPTCHA_CANDIDATES[0]

    # ================================================================
    # 登录入口
    # ================================================================

    def login(self, student_id: str, password: str) -> bool:
        self.student_id = student_id
        self.last_error = ""
        self.logged_in = False
        self.token = None
        self._captcha_ready = False
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

        # 8080 端口 Web 登录 + OCR
        if self._try_web_auto(student_id, password):
            return True

        return False

    # ================================================================
    # 方式1: Web 表单登录（USERNAME + PASSWORD 明文 + 验证码）
    # ================================================================

    def _try_simple_login(self, student_id: str, password: str, captcha: str) -> bool:
        """
        NJUST 真实登录：
        1. POST /Logon.do?method=logon（8080）
        2. 服务器返回 302 → 9080/LoginToXk?method=jwxt&secret=...
        3. 跟随重定向链完成认证
        """
        payload = {
            "USERNAME": student_id,
            "PASSWORD": password,
            "RANDOMCODE": captcha,
            "useDogCode": "",
        }
        try:
            # ★ 用 allow_redirects=True 让 requests 自动跟随整个重定向链
            resp = self.session.post(
                URL_LOGON_PAGE,
                data=payload,
                timeout=TIMEOUT,
                allow_redirects=True,  # ← 自动跟随 302 → 9080 → ...
                headers={"Referer": URL_LOGON_PAGE},
            )
            # ★ 先去重 cookie，否则 dict() 会崩溃
            self._dedupe_cookies()

            print(f"[Login] POST → final status={resp.status_code} "
                  f"final URL={resp.url[:120]}")
            print(f"[Login] 页面标题: {self._page_title(resp)}")
            for i, h in enumerate(resp.history):
                print(f"[Login]   重定向#{i}: {h.status_code} → {h.headers.get('Location','')[:80]}")

            # 安全打印 cookies
            ck = {c.name: c.value for c in self.session.cookies}
            print(f"[Login] cookies: {ck}")

            # 检查是否登录成功
            if self._check_success(resp):
                self._extract_name(resp.text)
                self.logged_in = True
                self.login_method = "web-auto"
                # ★ 访问 9080 主页巩固 session
                self.session.get(
                    URL_MAIN_PAGE,
                    timeout=TIMEOUT, allow_redirects=True,
                )
                self._dedupe_cookies()
                print(f"[Login] 登录成功! cookies: "
                      f"{ {c.name: c.value for c in self.session.cookies} }")
                return True

            # 检查响应中的错误提示
            t = resp.text.lower()
            if "用户名或密码不能为空" in t or "密码错误" in t:
                self.last_error = "用户名或密码错误"
            elif "验证码" in t and ("错误" in t or "不正确" in t):
                self.last_error = "验证码不正确"
            else:
                self.last_error = "登录失败"
            return False

        except Exception as e:
            print(f"[Login] 异常: {e}")
            return False

    # ================================================================
    # 方式2: Web 登录 + OCR
    # ================================================================

    def _try_web_auto(self, student_id: str, password: str) -> bool:
        """自动 OCR 识别验证码登录"""
        try:
            import ddddocr
            self._init_logon_session()
            ocr = ddddocr.DdddOcr(show_ad=False)

            for i in range(5):
                img = self._fetch_captcha()
                if not img:
                    break
                code = self._ocr_with_preprocess(ocr, img)
                if not code:
                    continue
                print(f"[OCR] #{i+1}: '{code}'")

                if self._try_simple_login(student_id, password, code):
                    self.logged_in = True
                    self.login_method = "web-auto"
                    return True

            self.last_error = "验证码自动识别失败，请使用手动输入（点「显示验证码」）"
            return False
        except ImportError:
            self.last_error = "缺少 ddddocr"
            return False
        except requests.exceptions.ConnectionError:
            self.last_error = "无法连接教务服务器（请检查校园网/VPN）"
            return False
        except Exception as e:
            self.last_error = str(e)
            return False

    # ================================================================
    # 手动验证码流程
    # ================================================================

    def get_captcha_base64(self) -> Tuple[str, str]:
        self._captcha_ready = False
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        try:
            self._init_logon_session()
            img = self._fetch_captcha()
            if not img:
                return "", "获取验证码失败"
            self._captcha_ready = True
            return base64.b64encode(img).decode(), ""
        except Exception as e:
            return "", str(e)

    def login_with_manual_captcha(self, sid: str, pw: str, captcha: str) -> bool:
        self.student_id = sid
        self.last_error = ""
        self.logged_in = False
        self.token = None

        if not self._captcha_ready:
            self.last_error = "会话过期，请重新获取验证码"
            return False

        if self._try_simple_login(sid, pw, captcha.strip()):
            self.logged_in = True
            self.login_method = "web-manual"
            self._captcha_ready = False
            return True

        self.last_error = "验证码不正确，请刷新重试"
        self._captcha_ready = False
        return False

    # ================================================================
    # 核心方法
    # ================================================================

    def _init_logon_session(self):
        self.session.cookies.clear()
        self.session.get(URL_LOGON_PAGE, timeout=TIMEOUT)
        self.session.headers.update({"Referer": URL_LOGON_PAGE})
        self._dedupe_cookies()
        self._detect_captcha_url_from_page()
        try:
            self.session.get(URL_LOGON_SESS, timeout=TIMEOUT)
            self._dedupe_cookies()
        except Exception:
            pass

    def _detect_captcha_url_from_page(self):
        try:
            resp = self.session.get(URL_LOGON_PAGE, timeout=TIMEOUT)
            m = re.search(
                r'<img[^>]+src=["\']([^"\']*(?:verifycode|checkcode|code)[^"\']*)["\']',
                resp.text, re.IGNORECASE)
            if m:
                src = m.group(1)
                self._active_captcha_url = src if src.startswith("http") else f"{BASE_URL}{src}"
                logger.debug("CaptchaURL: %s", self._active_captcha_url)
        except Exception:
            pass

    def _fetch_captcha(self) -> bytes:
        for url in [self._active_captcha_url] + URL_CAPTCHA_CANDIDATES:
            try:
                r = self.session.get(url, timeout=TIMEOUT)
                self._dedupe_cookies()
                if r.status_code == 200 and len(r.content) > 100:
                    self._active_captcha_url = url
                    return r.content
            except Exception:
                continue
        return b""

    def _dedupe_cookies(self):
        jar = self.session.cookies
        js = [c for c in jar if c.name == "JSESSIONID"]
        if len(js) > 1:
            last = js[-1]
            jar.clear()
            jar.set_cookie(last)

    def _ocr_with_preprocess(self, ocr, data: bytes) -> str:
        cands = [data]
        try:
            from PIL import Image
            from io import BytesIO
            img = Image.open(BytesIO(data)).convert("L")
            bw = img.point(lambda x: 0 if x < 140 else 255, "1")
            b = BytesIO(); bw.save(b, format="PNG"); cands.append(b.getvalue())
            big = img.resize((img.width*2, img.height*2), Image.LANCZOS)
            b2 = BytesIO(); big.save(b2, format="PNG"); cands.append(b2.getvalue())
        except Exception:
            pass
        for c in cands:
            r = ocr.classification(c).strip()
            if r: return r
        return ""

    def _check_success(self, resp) -> bool:
        t = resp.text
        for kw in ["验证码错误", "密码错误", "账号错误", "用户不存在"]:
            if kw in t:
                return False
        for kw in ["课程表", "学期理论课表", "学生首页", "学生个人中心",
                    "xs_main", "framemain", "安全退出", "退出系统"]:
            if kw in t:
                return True
        return URL_LOGON_PAGE.rstrip("/") not in resp.url.rstrip("/")

    def _page_title(self, resp) -> str:
        m = re.search(r'<title>([^<]*)</title>', resp.text)
        return m.group(1) if m else "无"

    def _extract_name(self, html: str):
        for p in [r'([^\s<]{2,4})[，,]\s*同学', r'姓名[：:]\s*([^\s<]{2,4})']:
            m = re.search(p, html)
            if m:
                self.student_name = m.group(1)
                return

    # ================================================================
    # 课表
    # ================================================================

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
            resp = self.session.post(
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
            print(f"[课表] 请求前 cookies: {dict(self.session.cookies)}")

            # 先访问主页，提取课表链接中的 Ves632DSdyV 参数
            main_resp = self.session.get(
                URL_MAIN_PAGE,
                timeout=TIMEOUT, allow_redirects=True,
            )
            print(f"[课表] 主页 GET → status={main_resp.status_code} "
                  f"title={self._page_title(main_resp)}")
            real_schedule_url = URL_SCHEDULE_HTML  # 默认
            m = re.search(r'xskb/xskb_list\.do\?([^"\']+)', main_resp.text)
            if m:
                real_schedule_url = f"{BASE_9080}/njlgdx/xskb/xskb_list.do?{m.group(1)}"
                print(f"[课表] 从主页提取真实URL参数: {m.group(1)[:50]}")

            resp = self.session.get(real_schedule_url, timeout=TIMEOUT, allow_redirects=True)
            print(f"[课表] GET → status={resp.status_code} len={len(resp.text)} title={self._page_title(resp)}")

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
                    print(f"[课表] 合并解析完成: {len(courses)} 条")
                    return courses

            # 降级
            if data_table:
                courses = self._parse_datalist(data_table)
                if courses: return courses
            if grid:
                courses = self._parse_kbtable(grid, {})
                if courses: return courses

            self.last_error = "课表表格未找到"
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
            resp = self.session.post(
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
            resp = self.session.get(URL_EXAM_QUERY, timeout=TIMEOUT)
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
                resp = self.session.post(target_url, data=form_data, timeout=TIMEOUT)
            else:
                # 没有表单，可能直接重定向了
                resp = self.session.get(URL_EXAM_LIST, timeout=TIMEOUT)

            soup = BeautifulSoup(resp.text, "lxml")
            result = _parse_table(soup)
            if result:
                return result

            # 策略2：直接 POST 学期参数到列表页
            resp = self.session.post(URL_EXAM_LIST,
                data={"xnxqid": semester, "method": "query"},
                timeout=TIMEOUT)
            soup = BeautifulSoup(resp.text, "lxml")
            result = _parse_table(soup)
            if result:
                return result

            # 策略3：GET 列表页（可能查询页已设置会话状态）
            resp = self.session.get(URL_EXAM_LIST, timeout=TIMEOUT)
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
            print(f"[考试HTML] 未找到数据表格")
            print(f"  页面标题: {page_title}")
            print(f"  响应长度: {len(resp.text)}")
            print(f"  表单数量: {form_count}, 表格数量: {table_count}")
            print(f"  疑似登录页: {has_login}")
            if has_login:
                self.last_error = "考试页面需要重新登录，请先在设置页登录"
            else:
                self.last_error = f"考试页面解析失败（表格数={table_count}），可能本学期暂无考试"
            return []
        except Exception as e:
            self.last_error = f"考试HTML解析失败: {e}"
            return []

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
            resp = self.session.get(URL_EVAL_PAGE, timeout=TIMEOUT)
            soup = BeautifulSoup(resp.text, "lxml")
            table = soup.find("table", class_="Nsb_r_list")
            if not table:
                self.last_error = "评价页面未找到数据表格"
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

    def test_connection(self) -> Tuple[bool, str]:
        try:
            r = self.session.get(URL_LOGON_PAGE, timeout=TIMEOUT)
            return (True, "连接正常") if r.status_code == 200 else (False, f"{r.status_code}")
        except requests.exceptions.ConnectionError:
            return False, "无法连接，请确认校园网/VPN"
        except Exception as e:
            return False, str(e)

    def logout(self):
        try:
            self.session.get(f"{BASE_9080}/njlgdx/xk/LoginToXk?method=exit", timeout=5)
        except Exception:
            pass
        self.logged_in = False
        self.token = None
        self.student_name = None
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
