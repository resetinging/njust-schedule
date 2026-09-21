# -*- coding: utf-8 -*-
"""ExamsMixin(Phase 2 从 jwc_client.py 拆出)。"""
from wxcloudrun.jwc.common import *  # noqa: F401,F403
from wxcloudrun.jwc.common import (  # noqa: F401
    _DedupCookieJar, _encrypt_sso_password, _dedupe_schedule_courses, _HAS_CRYPTO)


class ExamsMixin:
    # ================================================================
    # 考试
    # ================================================================

    def get_exams(self, semester: str = "") -> list[dict]:
        if not self.logged_in:
            self.last_error = "未登录"
            return []
        # 先尝试 API，失败则降级到 HTML（API 空结果也降级, HTML 能识别"暂无考试"）
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
            """返回 None=未找到考试表格; list=找到标准表格(可能为空, 空即"暂无考试")"""
            # 候选表格: 优先标准 id/class, 其次任意表头匹配考试关键字的表格
            candidates = []
            t = soup.find("table", id="dataList")
            if t:
                candidates.append(t)
            t = soup.find("table", class_="Nsb_r_list")
            if t:
                candidates.append(t)
            for tbl in soup.find_all("table"):
                if tbl in candidates:
                    continue
                head_text = " ".join(
                    c.get_text(strip=True) for c in (tbl.find("tr") or []) if c)
                if any(kw in head_text for kw in ("考试", "课程名称", "考场")):
                    candidates.append(tbl)

            for t in candidates:
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
                # 找到标准考试表格: 无论有无数据行都算解析成功(空=暂无考试)
                return exams
            return None

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
            if result is not None:
                return result

            # 策略2：直接 POST 学期参数到列表页
            resp = self.session.post(URL_EXAM_LIST,
                data={"xnxqid": semester, "method": "query"},
                timeout=TIMEOUT)
            soup = BeautifulSoup(resp.text, "lxml")
            result = _parse_table(soup)
            if result is not None:
                return result

            # 策略3：GET 列表页（可能查询页已设置会话状态）
            resp = self.session.get(URL_EXAM_LIST, timeout=TIMEOUT)
            soup = BeautifulSoup(resp.text, "lxml")
            result = _parse_table(soup)
            if result is not None:
                return result

            # 全部失败，诊断（记录各表格结构, 便于排查"暂无考试"还是"解析失败"）
            title = soup.find("title")
            page_title = title.get_text(strip=True) if title else "无标题"
            has_login = "logon" in resp.text.lower() or "登录" in resp.text
            form_count = len(soup.find_all("form"))
            table_count = len(soup.find_all("table"))
            logger.info("[考试HTML] 未找到数据表格")
            logger.info("  页面标题: %s", page_title)
            logger.info("  响应长度: %d", len(resp.text))
            logger.info("  表单数量: %d, 表格数量: %d", form_count, table_count)
            logger.info("  疑似登录页: %s", has_login)
            diag_parts = []
            for ti, tbl in enumerate(soup.find_all("table")):
                trs = tbl.find_all("tr")
                head = " | ".join(
                    c.get_text(strip=True) for c in trs[0].find_all(["td", "th"])
                )[:80] if trs else "(空表)"
                rows_text = " | ".join(
                    c.get_text(strip=True)
                    for c in (trs[1].find_all(["td", "th"]) if len(trs) > 1 else [])
                )[:80]
                logger.info("  表格#%d id=%s class=%s 行数=%d 表头=[%s] 首行=[%s]",
                            ti, tbl.get("id", "-"), tbl.get("class", "-"),
                            len(trs), head, rows_text)
                diag_parts.append(
                    f"表格#{ti} id={tbl.get('id', '-')} 行数={len(trs)} 表头=[{head}]")
            if has_login:
                self.last_error = "考试页面需要重新登录，请先在设置页登录"
            else:
                # 诊断摘要随错误返回, 前端 toast 可见
                self.last_error = ("考试解析失败（页面标题=%s）：%s" % (
                    page_title, "；".join(diag_parts))) if diag_parts else \
                    f"考试页面解析失败（表格数={table_count}），可能本学期暂无考试"
            return []
        except Exception as e:
            self.last_error = f"考试HTML解析失败: {e}"
            return []

