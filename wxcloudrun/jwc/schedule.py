# -*- coding: utf-8 -*-
"""ScheduleMixin(Phase 2 从 jwc_client.py 拆出)。"""
from wxcloudrun.jwc.common import *  # noqa: F401,F403
from wxcloudrun.jwc.common import (  # noqa: F401
    _DedupCookieJar, _encrypt_sso_password, _dedupe_schedule_courses, _HAS_CRYPTO)
from urllib.parse import urljoin


class ScheduleMixin:
    # ================================================================
    # 课表
    # ================================================================

    def get_schedule(self, semester: str = "", week: int = 0) -> list[dict]:
        if not self.logged_in:
            self.last_error = "未登录"
            return []
        courses = self._schedule_api(semester, week) or self._schedule_html(semester)
        if courses:
            self.last_error = ""   # 成功获取后清除 API 失败的残留错误
        return _dedupe_schedule_courses(courses)

    def fetch_course_schedule(self, semester: str = "", keyword: str = "",
                              course_type: str = "") -> list[dict]:
        """全校课程课表查询: 只返回页面实际提供的课程名/教师/周次/教室/时间。"""
        if not self.logged_in:
            self.last_error = "未登录"
            return []
        try:
            if not semester:
                semester = self._current_semester()
            page_url = f"{BASE_9080}{JW_PATH_PREFIX}/kbcx/kbxx_kc"
            page_resp = self.session.get(
                page_url, timeout=TIMEOUT, allow_redirects=True)
            if self._is_jw_login_page(page_resp):
                self.logged_in = False
                self.last_error = "登录状态已失效，请重新登录"
                return []
            page_soup = BeautifulSoup(page_resp.text, "lxml")
            form = page_soup.find("form", id="Form1")
            if form is None:
                form = next(
                    (item for item in page_soup.find_all("form")
                     if item.find("select", attrs={"name": "xnxqh"})),
                    None,
                )
            if form is None:
                self.last_error = "课程课表查询未找到 Form1"
                return []
            action = urljoin(
                page_resp.url, form.get("action") or page_resp.url)
            data = self._course_schedule_form_data(
                form, semester, keyword, course_type)
            resp = self.session.post(
                action, data=data, timeout=TIMEOUT, allow_redirects=True,
                headers={"Referer": page_resp.url})
            if self._is_jw_login_page(resp):
                self.logged_in = False
                self.last_error = "登录状态已失效，请重新登录"
                return []
            soup = BeautifulSoup(resp.text, "lxml")
            table = soup.find("table", id="kbtable")
            if table is None:
                self.last_error = "课程课表查询未找到 kbtable"
                return []
            courses = self._parse_kbtable(table, {})
            seen = set()
            result = []
            for course in courses:
                course["weeks"] = re.sub(
                    r'[（(]?周[）)]?$', '',
                    str(course.get("weeks") or "").strip()).strip()
                key = (course.get("name", ""), course.get("class_info", ""),
                       course.get("teacher", ""),
                       course.get("classroom", ""), course.get("day", 0),
                       course.get("start", 0), course.get("end", 0),
                       course.get("weeks", ""))
                if key in seen:
                    continue
                seen.add(key)
                result.append(course)
            self.last_error = ""
            return result
        except Exception as e:  # noqa: BLE001
            self.last_error = f"课程课表查询失败: {e}"
            return []

    @staticmethod
    def _course_schedule_form_data(form, semester: str, keyword: str,
                                   course_type: str) -> dict:
        """按查询页 Form1 的真实字段构造提交数据。"""
        data = {}
        for item in form.find_all("input"):
            name = item.get("name", "")
            if name:
                data[name] = item.get("value", "")
        for select in form.find_all("select"):
            name = select.get("name", "")
            if not name:
                continue
            options = select.find_all("option")
            if name == "xnxqh":
                matched = next(
                    (opt.get("value", "") for opt in options
                     if opt.get("value", "") == semester), "",
                )
                if not matched:
                    matched = next(
                        (opt.get("value", "") for opt in options
                         if semester in opt.get("value", "")), "",
                    )
                data[name] = matched or semester
                continue
            selected = next(
                (opt for opt in options if opt.has_attr("selected")),
                options[0] if options else None,
            )
            data[name] = selected.get("value", "") if selected else ""
        data["kc"] = str(keyword or "").strip()
        if "zzdKcSX" in data:
            data["zzdKcSX"] = str(course_type or "")
        return data

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
            if not isinstance(items, list):
                self.last_error = "课表API返回格式异常"
                return []
            return self._parse_schedule(items)
        except Exception as e:
            # 记录失败原因(供诊断: API 经常失败导致降级 HTML, 而 HTML 默认学期)
            self.last_error = f"课表API失败: {e}"
            return []

    def _post_schedule_semester(self, soup, url: str, semester: str):
        """通过课表页 Form1 的学期下拉提交目标学期, 返回响应或 None。

        课表页实际是 form id="Form1"(含 select name="xnxq01id" 学期下拉);
        首个 form 是打印表单, 不能抓。POST xnxq01id 后教务返回对应学期课表。
        """
        try:
            target_form = None
            for f in soup.find_all("form"):
                if f.get("id") == "Form1":
                    target_form = f
                    break
            if target_form is None:
                return None
            form_data = {}
            for inp in target_form.find_all("input"):
                n, v = inp.get("name", ""), inp.get("value", "")
                if n and n != "pageIndex":   # 排除分页参数
                    form_data[n] = v
            has_sem = False
            for sel in target_form.find_all("select"):
                n = sel.get("name", "")
                if n == "xnxq01id":
                    matched = None
                    for opt in sel.find_all("option"):
                        ov = opt.get("value", "")
                        if semester and semester in ov:
                            matched = ov
                            break
                    form_data[n] = matched or semester
                    has_sem = True
                elif n == "zc":
                    form_data[n] = ""   # 全部周
            if not has_sem:
                return None
            action = target_form.get("action", "")
            if action:
                if action.startswith("/"):
                    target = f"{BASE_9080}{action}"
                elif action.startswith("http"):
                    target = action
                else:
                    target = f"{BASE_9080}/njlgdx/xskb/{action}"
            else:
                target = url
            logger.debug("[课表] 提交学期 %s → %s", semester, target[:80])
            resp = self.session.post(target, data=form_data, timeout=TIMEOUT,
                                     allow_redirects=True, headers={"Referer": url})
            if resp.status_code == 200 and len(resp.text) > 2000:
                return resp
            return None
        except Exception as e:
            logger.debug("[课表] 学期表单提交失败: %s", e)
            return None

    def _schedule_html(self, semester: str) -> list[dict]:
        """课表 HTML 解析 — 从主页链接获取正确的 Ves632DSdyV 参数

        指定学期时优先通过页面学期下拉提交目标学期, 避免拿到
        教务默认学期的课表(不同学期内容相同的问题)。
        """
        def _parse_soup(soup):
            # 合并两个表格：kbtable(周次/教室) + dataList(精确小节)
            grid = soup.find("table", id="kbtable")
            data_table = soup.find("table", id="dataList")
            if grid and data_table:
                courses = self._parse_merged(grid, data_table)
                if courses:
                    return courses
            if data_table:
                courses = self._parse_datalist(data_table)
                if courses:
                    return courses
            if grid:
                courses = self._parse_kbtable(grid, {})
                if courses:
                    return courses
            return None

        try:
            # Debug: 看看当前 cookie 状态（含域名，不含值）
            cks = [(c.name, c.domain) for c in self.session.cookies]
            logger.debug("[课表] 请求前 cookies (%d个): %s", len(cks), cks)

            # 先访问主页，提取课表链接中的 Ves632DSdyV 参数
            main_resp = self.session.get(
                URL_MAIN_PAGE,
                timeout=TIMEOUT, allow_redirects=True,
            )
            logger.debug("[课表] 主页 GET → status=%s title=%s",
                         main_resp.status_code, self._page_title(main_resp))
            real_schedule_url = URL_SCHEDULE_HTML  # 默认
            m = re.search(r'xskb/xskb_list\.do\?([^"\']+)', main_resp.text)
            if m:
                real_schedule_url = f"{BASE_9080}/njlgdx/xskb/xskb_list.do?{m.group(1)}"
                logger.debug("[课表] 从主页提取真实URL参数: %s", m.group(1)[:50])

            resp = self.session.get(real_schedule_url, timeout=TIMEOUT, allow_redirects=True)
            logger.debug("[课表] GET → status=%s len=%d title=%s",
                         resp.status_code, len(resp.text), self._page_title(resp))

            if resp.status_code != 200 or len(resp.text) < 2000:
                self.last_error = "课表页面访问失败，请重新登录"
                return []

            soup = BeautifulSoup(resp.text, "lxml")

            # ★ 指定学期时: 优先通过页面学期下拉提交目标学期
            #   (直接 GET 只显示教务默认学期, 会导致不同学期拿到同一份课表)
            if semester:
                posted = self._post_schedule_semester(soup, real_schedule_url, semester)
                if posted is not None:
                    resp = posted
                    soup = BeautifulSoup(resp.text, "lxml")

            courses = _parse_soup(soup)
            if courses:
                logger.debug("[课表] 解析完成: %d 条 (semester=%s)", len(courses), semester)
                return courses

            self.last_error = "课表表格未找到"
            return []
        except Exception as e:
            logger.debug("[课表HTML] %s", e, exc_info=True)
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

        logger.debug("[课表] dataList 解析完成: %d 条", len(courses))
        return courses

    @staticmethod
    def _pick_period_slot(slots, rough):
        """同一课程同一天可能有多个上课时段(不同周次上课时间不同)。

        按"大节位置"挑选对应的时段: kbtable 中每个包含该课的大节格都会产生一条
        条目, 若用 (课程名, 星期) 单键存时段, 后解析到的会覆盖先前的, 导致所有
        条目都被写成同一个时间(表现为"课表只显示第一个时间")。
        slots: [(start, end, ...), ...]; rough: (大节起始, 大节结束)
        """
        if not slots:
            return None
        rough_start, rough_end = rough
        for slot in slots:
            if rough_start <= slot[0] <= rough_end:      # 时段起点落在本大节内
                return slot
        # 兜底: 取与本大节重叠最大的时段
        return max(slots, key=lambda s: min(s[1], rough_end) - max(s[0], rough_start))

    def _parse_merged(self, grid, data_table) -> list[dict]:
        """
        合并 kbtable（周次/教室/教师） + dataList（精确小节/学分/类型）
        kbtable 有正确的周次和教室分配，dataList 有精准的小节号
        """
        # Step 1: 从 dataList 提取精确小节信息
        day_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7}
        # {(name, day): [(start, end, credits, course_type), ...]}
        # 值用列表: 同一门课同一天可能有两个时段(不同周次时间不同), 不能互相覆盖
        period_info = {}
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
                period_info.setdefault((name, d), []).append(
                    (int(s), int(e), credits, ctype))

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

                        # ★ 从 period_info 获取精确小节(按大节位置匹配, 支持同课多时段)
                        p_start, p_end = rough
                        credits = ctype = ""
                        exact = self._pick_period_slot(period_info.get((name, day)), rough)
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
        if self._looks_like_course_catalog(rows):
            return self._parse_course_catalog_table(rows)

        # 表头解析星期列映射
        hdr = rows[0].find_all(["td", "th"])
        day_map = {}
        for i, c in enumerate(hdr):
            day = 0
            for d, n in enumerate("一二三四五六日", 1):
                if n in c.get_text():
                    day = d
                    break
            if day:
                try:
                    colspan = max(1, int(c.get("colspan", "1") or "1"))
                except ValueError:
                    colspan = 1
                for offset in range(colspan):
                    day_map[i + offset] = day
        logger.debug("[kbtable] 列映射: %s", day_map)

        # 大节 → 小节映射（从 th 文本提取）
        # 大节 → 小节映射
        # 上午8:00起, 下午14:00起, 晚上19:00起
        # 大节内小节间隔5min, 大节间隔15min
        period_map = BIG_PERIOD_MAP
        period_code_map = {
            "010203": (1, 3),
            "0405": (4, 5),
            "0607": (6, 7),
            "080910": (8, 10),
            "111213": (11, 13),
            "14": (14, 14),
        }

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
                period_range = period_code_map.get(period_label.replace(" ", ""))
            if not period_range:
                continue
            p_start, p_end = period_range

            # 遍历每天
            for ci, cell in enumerate(cells[1:], 1):
                if ci not in day_map:
                    continue
                day = day_map[ci]

                # 取详细 div（class="kbcontent"，不是 kbcontent1）
                detail_divs = cell.find_all(
                    "div",
                    class_=lambda value: value in ("kbcontent", "kbcontent1"),
                )
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

                        if not teacher and len(lines) > 1:
                            teacher = lines[1]
                        if not weeks:
                            for line in lines[1:]:
                                if ScheduleMixin._looks_like_schedule_week(line):
                                    weeks = re.sub(
                                        r'[（()）\s]|周$', '', line).strip()
                                    break
                        if not classroom and len(lines) > 1:
                            classroom = lines[-1]

                        if name and name != '\xa0':
                            # 从 dataList 获取精确小节号(按大节位置匹配, 支持同课多时段)
                            if period_info:
                                slot = self._pick_period_slot(
                                    period_info.get((name, day)), period_range)
                                if slot:
                                    p_start, p_end = slot[0], slot[1]

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

    @staticmethod
    def _looks_like_course_catalog(rows) -> bool:
        """识别全校课程目录表: 星期表头 colspan=6, 数据行为 43 列。"""
        header = rows[0].find_all(["td", "th"])
        if not any(
            str(cell.get("colspan", "1")).strip() == "6"
            for cell in header
        ):
            return False
        data_cells = rows[1].find_all(["td", "th"]) if len(rows) > 1 else []
        return len(data_cells) > 13

    def _parse_course_catalog_table(self, rows) -> list[dict]:
        """解析全校课程目录表(行=课程, 列=星期×大节)。"""
        period_codes = (
            (1, 3), (4, 5), (6, 7), (8, 10), (11, 13), (14, 14),
        )
        courses = []
        for row in rows[2:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            course_name = cells[0].get_text(" ", strip=True).strip()
            if not course_name:
                continue
            for cell_index, cell in enumerate(cells[1:], 1):
                slot_index = (cell_index - 1) % 6
                if slot_index >= len(period_codes):
                    continue
                day = (cell_index - 1) // 6 + 1
                if day > 7:
                    continue
                detail_divs = cell.find_all(
                    "div",
                    class_=lambda value: value in ("kbcontent", "kbcontent1"),
                )
                for div in detail_divs:
                    parsed = self._parse_catalog_course(
                        div, course_name, day, period_codes[slot_index])
                    courses.extend(parsed)
        return courses

    @staticmethod
    def _parse_catalog_course(div, course_name: str, day: int,
                              period_range: tuple):
        soup = BeautifulSoup(str(div), "lxml")
        lines = [
            line.strip() for line in soup.get_text("\n", strip=True).split("\n")
            if line.strip()
        ]
        week_re = re.compile(r'[（(]([^()（）]*?\d[^()（）]*?周)[）)]')
        result = []
        cursor = 0
        while cursor < len(lines):
            week_index = None
            week_match = None
            for index in range(cursor, len(lines)):
                found = week_re.search(lines[index])
                if found:
                    week_index = index
                    week_match = found
                    break
            if week_index is None or week_match is None:
                break

            before = [line.strip() for line in lines[cursor:week_index]
                      if line.strip()]
            inline_teacher = lines[week_index][:week_match.start()].strip(
                " ,，;；")
            if inline_teacher:
                before.append(inline_teacher)
            if not before:
                cursor = week_index + 1
                continue

            class_info = before[0].strip()
            classroom = ""
            classroom_before_week = ""
            for value in before[1:]:
                if ScheduleMixin._looks_like_catalog_classroom(value):
                    classroom_before_week = value
                    break
            teachers = [
                value.strip(" ,，;；")
                for value in before[1:]
                if value.strip(" ,，;；")
                and value.strip(" ,，;；") != classroom_before_week
            ]
            teacher = ",".join(teachers)

            next_index = week_index + 1
            if next_index < len(lines):
                candidate = lines[next_index].strip()
                if (not week_re.search(candidate)
                        and not ScheduleMixin._looks_like_class_info(candidate)):
                    classroom = candidate
                    next_index += 1
            if not classroom:
                classroom = classroom_before_week

            result.append({
                "name": course_name or class_info,
                "class_info": class_info,
                "teacher": teacher,
                "classroom": classroom,
                "day": day,
                "start": period_range[0],
                "end": period_range[1],
                "weeks": re.sub(
                    r'[（()）\s]', '', week_match.group(1)
                ).replace('周', '').strip(),
                "week_type": 0,
                "credits": "",
                "course_type": "",
                "raw": {},
            })
            cursor = max(next_index, week_index + 1)
        return result

    @staticmethod
    def _looks_like_class_info(value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        if re.fullmatch(r'(?:临班|班)?\s*\d+', text):
            return True
        if (re.fullmatch(r'[0-9A-Za-z]{6,}', text)
                and any(ch.isdigit() for ch in text)):
            return True
        values = [part.strip() for part in re.split(r'[,，]', text)
                  if part.strip()]
        return (
            len(values) > 1
            and all(
                re.fullmatch(r'[0-9A-Za-z]{4,}', part)
                and any(ch.isdigit() for ch in part)
                for part in values
            )
        )

    @staticmethod
    def _looks_like_classroom(value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        if any(word in text for word in ("教室", "楼", "校区", "线上", "其它")):
            return True
        if text.startswith(("江阴", "孝陵卫", "紫金", "汤山")):
            return True
        return bool(
            re.match(r'^[ⅠⅡⅢⅣIVX]+[-—]?[A-Za-z0-9]', text)
            or re.fullmatch(r'[A-Za-z]?[-—]?\d{2,4}[A-Za-z]?', text)
        )

    @staticmethod
    def _looks_like_schedule_week(value: str) -> bool:
        return bool(re.search(r'\d[\d,，\-–~至]*\s*周', str(value or "")))

    @staticmethod
    def _looks_like_catalog_classroom(value: str) -> bool:
        """识别课程目录单元格中位于周次前的教室写法。"""
        text = str(value or "").strip()
        if not text:
            return False
        # 设计类外教课程会把教室写成"设传外教01"等场地编号。
        if re.fullmatch(r'(?:设传外教|设传教室|设传实验)\s*\d+', text):
            return True
        return ScheduleMixin._looks_like_classroom(text)

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
