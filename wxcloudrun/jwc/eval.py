# -*- coding: utf-8 -*-
"""EvalMixin(Phase 2 从 jwc_client.py 拆出)。"""
from wxcloudrun.jwc.common import *  # noqa: F401,F403
from wxcloudrun.jwc.common import (  # noqa: F401
    _DedupCookieJar, _encrypt_sso_password, _dedupe_schedule_courses, _HAS_CRYPTO)


class EvalMixin:
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

    def is_session_valid(self, cache_ttl: float = 300.0) -> bool:
        """检测 教务 Session 是否仍然有效（轻量级检查）。

        - 结果缓存: 明确结论缓存 5 分钟; 探测无结论(网络/网关异常)
          只缓存 60 秒, 尽快重试
        - 只有「页面明确显示登录表单」才判定会话过期;
          网络故障/网关异常不踢人(实际数据请求失败时再提示重新登录)
        """
        if not self.logged_in:
            return False
        now = time.time()
        ttl = getattr(self, "_validity_cache_ttl", cache_ttl)
        if now - self._validity_cache_ts < ttl:
            return self._validity_cache_ok
        decided = True
        try:
            # 短超时探测: 教务无响应时保守信任现有会话(不踢人), 不拖慢数据请求
            resp = self.session.get(URL_MAIN_PAGE, timeout=5, allow_redirects=True)
            self._dedupe_cookies()
            if resp.status_code == 200:
                t = resp.text.lower()
                # 注意: 判定串必须是小写("userrname"/"randmcode" 是历史拼写错误,
                # 永远匹配不到, 导致会话过期被判成有效)
                if ("logon.do" in t or "username" in t or "randomcode" in t
                        or "verifycode" in t or "请先登录" in t):
                    ok = False   # 明确过期: 返回了登录表单
                else:
                    ok = True
            else:
                ok = True        # 网关/服务器异常: 探测无结论, 保守不踢人
                decided = False
        except Exception:
            ok = True            # 网络故障: 探测无结论, 保守不踢人
            decided = False
        self._validity_cache_ts = now
        self._validity_cache_ok = ok
        self._validity_cache_ttl = 300.0 if decided else 60.0
        return ok

    def test_connection(self, timeout: float = None) -> Tuple[bool, str]:
        """探测智慧理工 SSO 与教务入口连通性。

        教务旧 Logon.do 表单登录已下线，默认只探测智慧理工统一认证
        和 /njlgdx/indexsso.jsp；仅显式开启 JW_ALLOW_FORM_FALLBACK 时
        才回退旧的 8080 登录入口。
        """
        if self.webvpn is not None and self.webvpn.remap_to:
            try:
                r = self.session.get(f"{JW_SSO_BASE}{JW_PATH_PREFIX}/framework/main.jsp",
                                     timeout=timeout or TIMEOUT,
                                     allow_redirects=True)
                return (True, "连接正常") if r.status_code == 200 else (False, f"{r.status_code}")
            except Exception as e:  # noqa: BLE001
                return False, f"{JW_SSO_BASE} 无法连接: {e}"

        sso_checks = (
            ("智慧理工统一认证", SSO_LOGIN_URL),
            ("教务 SSO 入口", JW_SSO_ENTRY),
        )
        sso_error = ""
        for label, url in sso_checks:
            try:
                r = self.session.get(
                    url, timeout=timeout or TIMEOUT, allow_redirects=True)
                if r.status_code == 200:
                    continue
                sso_error = f"{label}返回 {r.status_code}"
            except requests.exceptions.ConnectionError:
                sso_error = f"{label}无法连接，请确认校园网/VPN"
            except Exception as e:  # noqa: BLE001
                sso_error = f"{label}探测失败: {e}"
            break
        else:
            return True, "智慧理工 SSO 与教务入口连接正常"

        if not JW_ALLOW_FORM_FALLBACK:
            return False, sso_error or "智慧理工 SSO 或教务入口不可达"

        bases = JW_LOGON_BASES or [BASE_URL]
        last_err = "无法连接，请确认校园网/VPN"
        for idx, base in enumerate(bases):
            try:
                r = self.session.get(f"{base}/Logon.do?method=logon",
                                     timeout=timeout or TIMEOUT)
                if r.status_code == 200:
                    self._use_logon_base(idx)
                    return True, "连接正常"
                last_err = f"{r.status_code}"
            except requests.exceptions.ConnectionError:
                last_err = f"{base} 无法连接，请确认校园网/VPN"
            except Exception as e:  # noqa: BLE001
                last_err = str(e)
        return False, last_err
