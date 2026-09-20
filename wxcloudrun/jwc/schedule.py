# -*- coding: utf-8 -*-
"""ScheduleMixin(Phase 2 从 jwc_client.py 拆出)。"""
from wxcloudrun.jwc.common import *  # noqa: F401,F403
from wxcloudrun.jwc.common import (  # noqa: F401
    _DedupCookieJar, _encrypt_sso_password, _dedupe_schedule_courses)


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
        """NJUST 课表 HTML 解析 — 从主页链接获取正确的 Ves632DSdyV 参数

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

        # 表头解析星期列映射
        hdr = rows[0].find_all(["td", "th"])
        day_map = {}
        for i, c in enumerate(hdr):
            for d, n in enumerate("一二三四五六日", 1):
                if n in c.get_text():
                    day_map[i] = d
                    break
        logger.debug("[kbtable] 列映射: %s", day_map)

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

