# -*- coding: utf-8 -*-
"""CetMixin(Phase 2 从 jwc_client.py 拆出)。"""
from wxcloudrun.jwc.common import *  # noqa: F401,F403
from wxcloudrun.jwc.common import (  # noqa: F401
    _DedupCookieJar, _encrypt_sso_password, _dedupe_schedule_courses)


class CetMixin:
    # ================================================================
    # 四六级
    # ================================================================

    def get_cet_scores(self) -> list[dict]:
        """获取四六级成绩"""
        try:
            resp = self.session.get(URL_CET_LIST, timeout=TIMEOUT)
            if resp.status_code != 200:
                logger.info(f"[CET] 请求失败: {resp.status_code}")
                return []
        except Exception as e:
            logger.info(f"[CET] 请求异常: {e}")
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        table = soup.find("table", id="dataList")
        if not table:
            logger.info("[CET] 未找到 #dataList 表格")
            return []

        rows = table.find_all("tr")
        if len(rows) < 3:
            return []

        cet_records = []
        for row in rows[2:]:
            cells = row.find_all("td")
            if len(cells) < 9:
                continue
            course_name = cells[1].get_text(strip=True)
            total_score_text = cells[4].get_text(strip=True)
            exam_date = cells[8].get_text(strip=True)

            if "CET6" in course_name:
                cet_type = "CET6"
            elif "CET4" in course_name:
                cet_type = "CET4"
            else:
                continue

            try:
                score = float(total_score_text)
            except (ValueError, TypeError):
                continue
            if score <= 0:
                continue

            cet_records.append((cet_type, score, exam_date))

        if not cet_records:
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

        logger.info(f"[CET] 汇总: {result}")
        return result

    @staticmethod
    def _to_float(val) -> float:
        """安全转换为 float"""
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0

