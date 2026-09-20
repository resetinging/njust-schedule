# -*- coding: utf-8 -*-
"""GradesMixin(Phase 2 从 jwc_client.py 拆出)。"""
from wxcloudrun.jwc.common import *  # noqa: F401,F403
from wxcloudrun.jwc.common import (  # noqa: F401
    _DedupCookieJar, _encrypt_sso_password, _dedupe_schedule_courses)


class GradesMixin:
    # ================================================================
    # 成绩查询
    # ================================================================

    def get_grades(self, semester: str = "") -> list[dict]:
        """获取成绩数据"""
        if not self.logged_in:
            self.last_error = "未登录"
            return []
        # 先尝试 API，失败则降级到 HTML（API 空结果也降级）
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
            resp = self.session.post(
                URL_APP_DO,
                params={"method": "getCjcx", "xh": self.student_id, "xnxqid": semester},
                headers={"token": self.token} if self.token else {},
                timeout=TIMEOUT,
            )
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
            candidates = []
            candidates.append(soup.find("table", id="dataList"))
            candidates.append(soup.find("table", class_="Nsb_r_list"))
            candidates.extend(soup.find_all("table", class_=lambda c: c and "Nsb" in c if c else False))
            for tbl in soup.find_all("table"):
                if tbl not in candidates:
                    candidates.append(tbl)

            for t in candidates:
                if t is None:
                    continue
                rows = t.find_all("tr")
                if len(rows) < 2:
                    continue
                hdr_cells = rows[0].find_all(["td", "th"])
                hdr_texts = [c.get_text(strip=True) for c in hdr_cells]
                logger.info(f"[成绩] {label} 候选表格: {len(rows)}行, 表头: {hdr_texts[:12]}")

                hdr_joined = " ".join(hdr_texts)
                if not any(kw in hdr_joined for kw in ("课程名称", "课程", "成绩", "学分", "绩点", "分数")):
                    continue

                # 建立列映射
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

                # 兜底：强智教务常见布局
                if "course_name" not in col:
                    col = {"course_name": 3, "score": 4, "credit": 6,
                           "grade_point": None, "course_type": 9, "exam_type": 8,
                           "course_nature": 10, "course_code": 2, "semester": 1}
                    logger.info(f"[成绩] {label} 表头匹配失败，使用固定位置")
                else:
                    logger.info(f"[成绩] {label} 表头映射: {col}")

                if "grade_point" not in col:
                    col["grade_point"] = None
                break
            else:
                logger.info(f"[成绩] {label} 未找到合适的表格")
                return None

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

            logger.info(f"[成绩] {label} 解析完成: {len(grades)} 条")
            # 找到标准成绩表格即算解析成功: 空列表 = 暂无成绩(正常场景)
            return grades

        # 策略执行
        strategies = []

        # 策略1: GET 查询页
        try:
            resp = self.session.get(URL_GRADE_QUERY, timeout=TIMEOUT)
            soup = BeautifulSoup(resp.text, "lxml")
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
                if action:
                    if action.startswith("/"):
                        target = f"{BASE_9080}{action}"
                    elif action.startswith("http"):
                        target = action
                    else:
                        target = f"{BASE_9080}/njlgdx/kscj/{action}"
                else:
                    target = URL_GRADE_LIST
                strategies.append(("POST表单", lambda t=target, d=form_data: self.session.post(t, data=d, timeout=TIMEOUT)))

            result = _parse_table(soup, "策略1直接")
            if result is not None:
                return result
        except Exception as e:
            logger.info(f"[成绩] 策略1异常: {e}")

        # 策略2: 直接 POST 列表页
        strategies.append(("POST列表页", lambda: self.session.post(
            URL_GRADE_LIST, data={"xnxqid": semester}, timeout=TIMEOUT)))

        # 策略3: GET 列表页
        strategies.append(("GET列表页", lambda: self.session.get(
            URL_GRADE_LIST, timeout=TIMEOUT)))

        # 执行策略
        last_soup = None
        for sname, sfn in strategies:
            logger.info(f"[成绩] {sname}...")
            try:
                resp = sfn()
                soup = BeautifulSoup(resp.text, "lxml")
                last_soup = soup
                result = _parse_table(soup, sname)
                if result is not None:
                    return result
            except Exception as e:
                logger.info(f"[成绩]   {sname} 异常: {e}")

        # 全部失败
        if last_soup:
            has_login = "logon" in str(last_soup).lower() or "登录" in str(last_soup)
            if has_login:
                self.last_error = "成绩页面需要重新登录，请先在设置页登录"
            else:
                self.last_error = "成绩解析失败"
        else:
            self.last_error = "无法访问成绩页面"
        return []

