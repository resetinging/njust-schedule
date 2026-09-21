# -*- coding: utf-8 -*-
"""FreeClassMixin(Phase 2 从 jwc_client.py 拆出)。"""
from wxcloudrun.jwc.common import *  # noqa: F401,F403
from wxcloudrun.jwc.common import (  # noqa: F401
    _DedupCookieJar, _encrypt_sso_password, _dedupe_schedule_courses, _HAS_CRYPTO)


class FreeClassMixin:
    # ============================================================
    # 空教室查询(数据源: 「教室借用查询」→ 状态"空闲"的教室清单)
    # ============================================================
    BORROW_OPTS_TTL = 600   # 查询页选项(学期/校区)会话内缓存 10 分钟

    def _borrow_page_opts(self, force: bool = False):
        """教室借用查询页选项(学期列表/校区码/表单 action), 会话内缓存 10 分钟。

        返回 None 表示会话过期或页面结构异常(已设置 last_error)。
        """
        cache = getattr(self, "_borrow_opts_cache", None)
        if not force and cache and time.time() - cache["ts"] < self.BORROW_OPTS_TTL:
            return cache
        try:
            page = self.session.get(URL_BORROW_QUERY, timeout=TIMEOUT,
                                    allow_redirects=True)
        except Exception as e:
            logger.warning("[教室借用] 查询页获取失败: %s", e)
            self.last_error = f"教室借用查询失败: {e}"
            return None
        if self._is_jw_login_page(page):
            self.last_error = "登录已过期，请重新登录"
            return None
        soup = BeautifulSoup(page.text, "lxml")
        form = soup.find("form", {"name": "Form1"}) or soup.find("form")
        sem_sel = soup.find("select", {"name": "xnxqh"})
        if form is None or sem_sel is None:
            self.last_error = "教室借用页解析失败: 未找到查询表单/学期选项"
            return None
        xq_sel = soup.find("select", {"name": "xqbh"})
        sem_opts = sem_sel.find_all("option")
        sem_vals = [o.get("value") or "" for o in sem_opts
                    if (o.get("value") or "")]
        # 教务把"当前学期"标成 selected; 用户学期不在选项里时回退它, 而不是
        # 取首个选项(首个是最新/未来学期)
        cur_sem = next((o.get("value") or "" for o in sem_opts
                        if o.has_attr("selected") and (o.get("value") or "")), "")
        xq_map = {}
        if xq_sel is not None:
            for o in xq_sel.find_all("option"):
                v = o.get("value") or ""
                if v:
                    xq_map[o.get_text(" ", strip=True)] = v
        opts = {"ts": time.time(), "sem_vals": sem_vals,
                "cur_sem": cur_sem or (sem_vals[0] if sem_vals else ""),
                "xq_map": xq_map,
                "action": form.get("action") or "/njlgdx/kbxx/jsjy_query2"}
        self._borrow_opts_cache = opts
        return opts

    def get_free_classrooms(self, campus: str = "孝陵卫", weekday: int = 1,
                            slot: str = "6-7", jc1: int = None, jc2: int = None,
                            week: int = None, semester: str = "",
                            building: str = "") -> dict:
        """查询空闲教室(数据源: 教务「教室借用查询」, 状态=空闲)。

        与旧"全校性教室课表"数据源的区别: 借用页按状态直接返回教室清单,
        覆盖整学期无排课(因此课表页会漏报)的教室; 状态语义由教务定义
        (jszt=5 → 空闲)。只保留有楼名映射的教室(四大教学楼 + 地图楼名),
        未映射资产编号/非实体条目在解析时被过滤。

        campus: 孝陵卫 | 江阴; weekday: 1-7(周一=1);
        jc1/jc2: 节次范围起止(1-13), 缺省时按 slot 大节映射;
        week: 周次; semester: 学年学期(不在教务选项内时回退当前学期);
        building: 教学楼显示名前缀(可选, 如 "Ⅳ教学楼"/"东区平房")。
        成功返回 {"rooms": [...], "jc1":, "jc2":, "building_name": "",
        "buildings": []}; 失败/会话过期时设置 last_error 并返回 []。
        """
        self.last_error = ""     # 清掉上一次调用(含登录重试)残留的错误信息
        slot_map = {s[0]: s for s in CLASSROOM_SLOTS}
        # 节次范围: jc1/jc2 显式优先, 否则按大节 slot 映射; 非法回退 第6-7节
        if isinstance(jc1, int) and isinstance(jc2, int):
            a, b = jc1, jc2
        elif slot in slot_map:
            a, b = slot_map[slot][2], slot_map[slot][3]
        else:
            a, b = 6, 7
        if not (1 <= a <= 13 and 1 <= b <= 13 and a <= b):
            a, b = 6, 7
        try:
            # 1) 选项(10 分钟缓存): 学期列表 / 校区码 / 表单 action
            opts = self._borrow_page_opts()
            if opts is None:
                return []
            xnxqh = semester if (semester and semester in opts["sem_vals"]) \
                else opts.get("cur_sem", "")
            xqid = next((v for t, v in opts["xq_map"].items()
                         if campus and t.startswith(campus)),
                        {"孝陵卫": "01", "江阴": "4y"}.get(campus, "01"))
            wk = max(1, min(int(week or 1), 30))
            action = opts["action"] or URL_BORROW_LIST
            if action.startswith("http"):
                # 页面 action 只允许留在教务主机上(防改版/篡改把请求带向别处)
                from urllib.parse import urlsplit
                if urlsplit(action).netloc != urlsplit(URL_BORROW_QUERY).netloc:
                    action = URL_BORROW_LIST
            url = action if action.startswith("http") else f"{BASE_9080}{action}"

            # 2) 提交查询(字段名取自借用页表单实测; jszt=5 → 空闲)
            data = {
                "typewhere": "jszq",
                "xnxqh": xnxqh,
                "xqbh": xqid,
                "jxqbh": "",
                "jxlbh": "",
                "jsbh": "",
                "bjfh": "=",
                "rnrs": "",
                "jszt": "5",
                "zc": str(wk), "zc2": str(wk),
                "xq": str(weekday), "xq2": str(weekday),
                "jc": "%02d" % a, "jc2": "%02d" % b,
            }
            resp = self.session.post(url, data=data, timeout=TIMEOUT,
                                     allow_redirects=True,
                                     headers={"Referer": URL_BORROW_QUERY})
            if self._is_jw_login_page(resp):
                self.last_error = "登录已过期，请重新登录"
                return []
            try:
                rooms = self.parse_borrow_free_list(resp.text)
            except ClassroomBorrowError as e:
                # 结构异常 → 明确失败, 绝不退化成"0 间空闲"
                self.last_error = "教室借用页解析失败: %s" % e
                logger.warning("[教室借用] 解析失败 %s xqid=%s xnxqh=%s 周%s 星期%s "
                               "第%d-%d节: %s(%d 字节)",
                               campus, xqid, xnxqh, wk, weekday, a, b,
                               e, len(resp.text))
                return []
            building_name = ""
            if building and building.strip():
                building_name = building.strip()
                rooms = [r for r in rooms if r.startswith(building_name)]
            logger.info("[教室借用] %s xqid=%s xnxqh=%s 周%s 星期%s 第%d-%d节 空闲 %d 间",
                        campus, xqid, xnxqh, wk, weekday, a, b, len(rooms))
            return {"rooms": rooms, "jc1": a, "jc2": b,
                    "building_name": building_name, "buildings": []}
        except Exception as e:
            logger.warning("[教室借用] 查询异常: %s", e)
            self.last_error = f"教室借用查询失败: {e}"
            return []

    @staticmethod
    def parse_borrow_free_list(html: str) -> list:
        """解析 jsjy_query2 返回的空闲教室清单(2026-09 教务实测结构)。

        <form> 条件回显 + <table id="dataList">: 2 行表头, 之后每间教室
        一行(行内含 <input name="jsids">)。单个大节查询时每行 1 个状态列;
        跨大节时段查询时教务返回多列, 且命中条件是"任一大节空闲"(并集),
        因此这里要求**所有状态列都为空/空闲**才算该教室在整段时段空闲。
        无数据行 = 合法空清单; 无表单/无结果表 → ClassroomBorrowError。
        返回教室显示名(去容量后缀 + 楼名映射; 未映射/非实体条目被过滤)。
        """
        try:
            soup = BeautifulSoup(html or "", "lxml")
        except Exception as e:
            raise ClassroomBorrowError("结果 HTML 无法解析: %s" % e)
        form = soup.find("form", {"id": "Form1"}) or soup.find("form")
        table = soup.find("table", {"id": "dataList"})
        if form is None or table is None:
            raise ClassroomBorrowError("未找到结果表单/表格(可能返回了错误页或登录页)")
        rows = table.find_all("tr")
        if len(rows) < 2:
            raise ClassroomBorrowError("结果表行数不足(%d 行)" % len(rows))
        rooms = []
        for tr in rows:
            cb = tr.find("input", {"name": "jsids"})
            if cb is None:
                continue
            cells = tr.find_all(["td", "th"])
            texts = [" ".join(c.get_text(" ", strip=True).split()) for c in cells]
            name_idx = next((i for i, c in enumerate(cells)
                             if c.find("input", {"name": "jsids"}) is not None), 0)
            # 跨大节: 任一状态列非空且不是"空闲"字样 → 该时段被占用, 排除
            busy = [t for i, t in enumerate(texts)
                    if i != name_idx and t and t not in ("空闲", "空")]
            if busy:
                continue
            raw = texts[name_idx] if name_idx < len(texts) else ""
            name = format_room_name(raw)
            if name:
                rooms.append(name)
        return rooms

    def logout(self):
        try:
            self.session.get(f"{BASE_9080}/njlgdx/xk/LoginToXk?method=exit", timeout=5)
        except Exception:
            pass
        self.logged_in = False
        self.token = None
        self.student_name = None
        self._setup_session()
