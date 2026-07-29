"""
南理工课表管理系统 — 评教辅助模块
===============================
教学评价的 HTML 解析、自动评分算法、POST 数据构建。
从 desktop 移植，适配 Flask 云托管环境。
"""
import re
from bs4 import BeautifulSoup

from config import JW_BASE_9080, JW_PATH_PREFIX

# NJUST 教务评教页面核心 URL
JW_EVAL_BASE = f"{JW_BASE_9080}{JW_PATH_PREFIX}"

# 评教相关请求的公共头部（避免教务拦截）
EVAL_HEADERS = {
    "Referer": f"{JW_EVAL_BASE}/xspj/xspj_find.do",
    "Host": f"{JW_BASE_9080.replace('http://', '')}",
    "Origin": JW_BASE_9080,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "max-age=0",
}


def warm_eval_session(session):
    """访问评教列表页建立会话状态，避免后续请求被教务拒绝

    参数:
        session: requests.Session 对象
    """
    try:
        session.get(
            f"{JW_EVAL_BASE}/xspj/xspj_find.do",
            headers={"Referer": f"{JW_EVAL_BASE}/framework/main.jsp"},
            timeout=10)
    except Exception:
        pass  # 预热失败不阻塞后续流程


# ================================================================
# 评价课程列表页解析
# ================================================================

def parse_eval_courses_page(html: str) -> dict:
    """从评教课程列表页 HTML 解析课程、批次标题和隐藏字段
    返回 {"batch_title": str, "courses": list, "hidden_fields": dict} 或 None
    """
    soup = BeautifulSoup(html, "lxml")

    # 提取批次标题
    title_el = soup.select_one(".Nsb_r_title")
    batch_title = title_el.get_text(strip=True) if title_el else "评教课程"

    # 提取 Form1 中的隐藏字段（后续提交需要）
    form = soup.find("form", id="Form1")
    hidden_fields = {}
    if form:
        for inp in form.find_all("input", type="hidden"):
            name = inp.get("name", "")
            value = inp.get("value", "")
            if name:
                hidden_fields[name] = value

    # 解析课程列表 (#dataList)
    courses = []
    data_table = soup.find("table", id="dataList")
    if data_table:
        for row in data_table.find_all("tr")[1:]:  # 跳过表头
            cells = row.find_all("td")
            if len(cells) < 8:
                continue
            # 提取评价链接（javascript:openWindow('...',1000,700)）
            eval_url = ""
            eval_link = cells[7].find("a")
            if eval_link:
                href = eval_link.get("href", "")
                m = re.search(r"openWindow\('([^']+)'", href)
                if m:
                    eval_url = m.group(1)

            courses.append({
                "seq": cells[0].get_text(strip=True),
                "code": cells[1].get_text(strip=True),
                "name": cells[2].get_text(strip=True),
                "teacher": cells[3].get_text(strip=True),
                "score": cells[4].get_text(strip=True),
                "evaluated": cells[5].get_text(strip=True) == "是",
                "submitted": cells[6].get_text(strip=True) == "是",
                "eval_url": eval_url,
            })

    return {"batch_title": batch_title, "courses": courses, "hidden_fields": hidden_fields}


# ================================================================
# 评价表单页解析
# ================================================================

def parse_eval_form_page(html: str) -> dict:
    """从评教表单页 HTML 解析评价指标和隐藏字段
    返回 {"course_name": str, "hidden_fields": dict, "indicators": list, "action": str} 或 None
    """
    soup = BeautifulSoup(html, "lxml")

    # 提取课程信息（教务用 &nbsp; 分隔字段）
    th = soup.find("th", class_="Nsb_r_list_thb")
    course_info = th.get_text() if th else ""
    course_name = ""
    m = re.search(r'课程名称[：:]\s*(.+?)(?:\s{2,}|\xa0|$)', course_info)
    if m:
        course_name = m.group(1).strip()

    # 提取隐藏字段
    form = soup.find("form", id="Form1")
    hidden_fields = {}
    if form:
        for inp in form.find_all("input", type="hidden"):
            name = inp.get("name", "")
            value = inp.get("value", "")
            if name:
                hidden_fields[name] = value

    # 提取评价指标（同时收集所有 pj0601fz_* 分值隐藏字段）
    indicators = []
    for row in soup.select("#table1 tr"):
        tds = row.find_all("td")
        if len(tds) < 2:
            continue
        # 第一个 td: 指标标签 + <input type="hidden" name="pj06xh">
        label = tds[0].get_text(strip=True)
        if not label or "评价指标" in label:
            continue
        seq_input = tds[0].find("input", attrs={"name": "pj06xh"})
        seq = seq_input.get("value", "") if seq_input else ""

        # 第二个 td: radio 选项 + 隐藏分值字段交替排列
        # 先构建分值映射: {radio_uuid: score}，同时将 pj0601fz_* 存入 hidden_fields
        fz_map = {}
        for inp in tds[1].find_all("input", type="hidden"):
            fz_name = inp.get("name", "")
            fz_value = inp.get("value", "")
            if fz_name.startswith("pj0601fz_"):
                hidden_fields[fz_name] = fz_value  # ★ 批量评教提交时需要这些分值字段
                parts = fz_name.rsplit("_", 1)
                if len(parts) == 2:
                    fz_map[parts[1]] = fz_value

        options = []
        for radio in tds[1].find_all("input", type="radio"):
            opt_name = radio.get("name", "")
            opt_value = radio.get("value", "")
            opt_score = fz_map.get(opt_value, "")
            opt_checked = radio.has_attr("checked")
            # 直接取 radio 后面的 NavigableString 文本节点
            opt_label = ""
            sib = radio.next_sibling
            if sib:
                try:
                    txt = str(sib).strip()
                    if txt:
                        opt_label = txt
                except Exception:
                    pass
            if not opt_label:
                opt_label = radio.parent.get_text().strip() if radio.parent else ""
            options.append({
                "name": opt_name,
                "value": opt_value,
                "label": opt_label.strip(),
                "score": opt_score,
                "checked": opt_checked,
            })
        indicators.append({"seq": seq, "label": label, "options": options})

    # 提取表单 action URL
    form_action = form.get("action", "") if form else ""

    return {
        "course_name": course_name,
        "hidden_fields": hidden_fields,
        "indicators": indicators,
        "action": form_action,
    }


# ================================================================
# 自动填写算法（从 desktop eval_helpers.py 移植，增强版）
# ================================================================

def auto_fill_eval_indicators(indicators: list, target_score: float = 95.0) -> dict:
    """根据目标分数自动选择每个指标的 radio 选项
    算法：贪心选择 + 防同列作弊 + 微调优化 + 双指标组合交换 + 兜底放松

    参数:
        indicators: 指标列表，每项含 seq, label, options（options 中含 name/value/score/checked）
        target_score: 目标总分（满分通常为指标数*各指标最高分之和）

    返回:
        {seq: (radio_name, radio_value)} 映射 + {"_total": 实际总分}
    """
    if not indicators:
        return {"_total": 0}

    # 步骤 0: 计算满分和各指标的目标分
    indicator_scores = []  # [{seq, max_score, options_with_idx}]
    total_max = 0
    for ind in indicators:
        opts = ind.get("options", [])
        ind_max = 0
        scored_opts = []
        for i, opt in enumerate(opts):
            s = float(opt.get("score", 0) or 0)
            scored_opts.append({"idx": i, "score": s, "name": opt["name"], "value": opt["value"]})
            if s > ind_max:
                ind_max = s
        total_max += ind_max
        indicator_scores.append({
            "seq": ind.get("seq", ""),
            "max_score": ind_max,
            "options": scored_opts,
        })

    if total_max <= 0:
        return {"_total": 0}

    # 步骤 1: 贪心选择 — 每个指标选最接近目标比例的选项
    selections = []  # [{seq, colIndex, score}]
    for iscore in indicator_scores:
        ind_target = (target_score / total_max) * iscore["max_score"] if total_max > 0 else 0
        best_idx = 0
        best_dist = float('inf')
        for opt in iscore["options"]:
            dist = abs(opt["score"] - ind_target)
            if dist < best_dist:
                best_dist = dist
                best_idx = opt["idx"]
        chosen = iscore["options"][best_idx]
        selections.append({
            "seq": iscore["seq"],
            "colIndex": best_idx,
            "score": chosen["score"],
            "name": chosen["name"],
            "value": chosen["value"],
            "options": iscore["options"],  # 保留完整选项供微调
        })

    # 辅助：检查是否所有指标在同一列
    def _all_same_column(sels):
        if len(sels) <= 1:
            return False
        return all(s["colIndex"] == sels[0]["colIndex"] for s in sels)

    # 步骤 2: 防作弊 — 不能所有指标选同一列
    if len(selections) > 1 and _all_same_column(selections):
        current_total = sum(s["score"] for s in selections)
        best_penalty = abs(current_total - target_score)
        best_combo = None

        for sacrifice_idx in range(len(selections)):
            for alt_opt in selections[sacrifice_idx]["options"]:
                if alt_opt["idx"] == selections[sacrifice_idx]["colIndex"]:
                    continue
                new_total = current_total - selections[sacrifice_idx]["score"] + alt_opt["score"]
                penalty = abs(new_total - target_score)
                if penalty < best_penalty:
                    best_penalty = penalty
                    best_combo = {
                        "sacrifice_idx": sacrifice_idx,
                        "colIndex": alt_opt["idx"],
                        "score": alt_opt["score"],
                        "name": alt_opt["name"],
                        "value": alt_opt["value"],
                    }

        if best_combo:
            idx = best_combo["sacrifice_idx"]
            selections[idx]["colIndex"] = best_combo["colIndex"]
            selections[idx]["score"] = best_combo["score"]
            selections[idx]["name"] = best_combo["name"]
            selections[idx]["value"] = best_combo["value"]

    # 步骤 3: 单指标微调（最多 10 轮，连续 3 轮无改善则进入双指标阶段）
    no_improve_rounds = 0
    for _ in range(10):
        current_total = sum(s["score"] for s in selections)
        current_penalty = abs(current_total - target_score)
        if current_penalty < 0.5:
            break

        best_swap = None
        best_penalty = current_penalty

        for i in range(len(selections)):
            for alt_opt in selections[i]["options"]:
                if alt_opt["idx"] == selections[i]["colIndex"]:
                    continue
                new_total = current_total - selections[i]["score"] + alt_opt["score"]
                new_penalty = abs(new_total - target_score)

                # 模拟应用后检查是否全同列
                saved_col = selections[i]["colIndex"]
                saved_score = selections[i]["score"]
                selections[i]["colIndex"] = alt_opt["idx"]
                selections[i]["score"] = alt_opt["score"]
                all_same = _all_same_column(selections)
                selections[i]["colIndex"] = saved_col
                selections[i]["score"] = saved_score

                if all_same:
                    continue

                if new_penalty < best_penalty:
                    best_penalty = new_penalty
                    best_swap = {
                        "idx": i,
                        "colIndex": alt_opt["idx"],
                        "score": alt_opt["score"],
                        "name": alt_opt["name"],
                        "value": alt_opt["value"],
                    }

        if best_swap and best_penalty < current_penalty:
            idx = best_swap["idx"]
            selections[idx]["colIndex"] = best_swap["colIndex"]
            selections[idx]["score"] = best_swap["score"]
            selections[idx]["name"] = best_swap["name"]
            selections[idx]["value"] = best_swap["value"]
            no_improve_rounds = 0
        else:
            no_improve_rounds += 1
            if no_improve_rounds >= 3:
                break

    # 步骤 4: 双指标组合交换 — 突破单指标局部最优
    current_total = sum(s["score"] for s in selections)
    current_penalty = abs(current_total - target_score)
    if current_penalty >= 0.5:
        best_pair = None
        best_penalty = current_penalty

        for i in range(len(selections)):
            for j in range(i + 1, len(selections)):
                for alt_i in selections[i]["options"]:
                    if alt_i["idx"] == selections[i]["colIndex"]:
                        continue
                    for alt_j in selections[j]["options"]:
                        if alt_j["idx"] == selections[j]["colIndex"]:
                            continue
                        new_total = (current_total
                                     - selections[i]["score"] - selections[j]["score"]
                                     + alt_i["score"] + alt_j["score"])
                        new_penalty = abs(new_total - target_score)

                        if new_penalty >= best_penalty:
                            continue

                        # 模拟应用后检查防作弊
                        saved_i_col = selections[i]["colIndex"]
                        saved_j_col = selections[j]["colIndex"]
                        selections[i]["colIndex"] = alt_i["idx"]
                        selections[j]["colIndex"] = alt_j["idx"]
                        all_same = _all_same_column(selections)
                        selections[i]["colIndex"] = saved_i_col
                        selections[j]["colIndex"] = saved_j_col

                        if all_same:
                            continue

                        best_penalty = new_penalty
                        best_pair = [
                            {"idx": i, "colIndex": alt_i["idx"], "score": alt_i["score"],
                             "name": alt_i["name"], "value": alt_i["value"]},
                            {"idx": j, "colIndex": alt_j["idx"], "score": alt_j["score"],
                             "name": alt_j["name"], "value": alt_j["value"]},
                        ]

        if best_pair:
            for swap in best_pair:
                idx = swap["idx"]
                selections[idx]["colIndex"] = swap["colIndex"]
                selections[idx]["score"] = swap["score"]
                selections[idx]["name"] = swap["name"]
                selections[idx]["value"] = swap["value"]

    # 步骤 5: 兜底 — 如果误差仍超过 5% 且前面都没能收敛，放松防作弊
    final_total = sum(s["score"] for s in selections)
    final_penalty = abs(final_total - target_score)
    if final_penalty > max(2.0, total_max * 0.05):
        for i in range(len(selections)):
            best_cost = float('inf')
            best_opt = None
            saved_col = selections[i]["colIndex"]
            saved_score = selections[i]["score"]
            for alt_opt in selections[i]["options"]:
                new_total = final_total - saved_score + alt_opt["score"]
                new_penalty = abs(new_total - target_score)
                if new_penalty < best_cost:
                    selections[i]["colIndex"] = alt_opt["idx"]
                    is_ok = not _all_same_column(selections)
                    if is_ok:
                        best_cost = new_penalty
                        best_opt = alt_opt
            selections[i]["colIndex"] = saved_col
            selections[i]["score"] = saved_score
            if best_opt and best_cost < final_penalty * 0.8:
                selections[i]["colIndex"] = best_opt["idx"]
                selections[i]["score"] = best_opt["score"]
                selections[i]["name"] = best_opt["name"]
                selections[i]["value"] = best_opt["value"]
                final_total = sum(s["score"] for s in selections)
                final_penalty = abs(final_total - target_score)
            if final_penalty < 1.0:
                break

    # 构建返回结果
    result = {}
    for s in selections:
        result[s["seq"]] = (s["name"], s["value"])
    result["_total"] = sum(s["score"] for s in selections)
    return result


# ================================================================
# POST 数据有序构建（从 api_submit_eval 提取，批量评教复用）
# ================================================================

def build_ordered_eval_post_data(form_data: dict, batch_hidden_fields: dict = None,
                                  auto_fill_selections: dict = None,
                                  submit_type: str = "1") -> list:
    """构建有序 POST 数据，模拟浏览器原生表单提交顺序。

    教务原始表单每个指标行都有 <input name="pj06xh" value="N">，
    浏览器会提交 N 个 pj06xh=N。必须为每个指标插入 pj06xh 作为行分隔符，
    否则教务只保存最后一项。

    参数:
        form_data: 表单隐藏字段 + 指标数据（与前端提交格式一致）
        batch_hidden_fields: 课程列表页的隐藏字段（如 cj0701id），会合并进去
        auto_fill_selections: 自动填写的选择 {seq: (name, value)}，如果提供则覆盖 form_data 中的 radio 值
        submit_type: "0"=保存, "1"=提交

    返回: [(key, value), ...] 有序参数列表
    """
    # 合并批次级隐藏字段
    merged = dict(form_data)
    if batch_hidden_fields:
        for k, v in batch_hidden_fields.items():
            if k not in merged:
                merged[k] = v

    # 如果提供了自动填写结果，覆盖 radio 值
    if auto_fill_selections:
        for seq, val in auto_fill_selections.items():
            if seq == "_total":
                continue
            name, value = val  # val 是 (radio_name, radio_value) 元组
            merged[name] = value

    # 按指标序号分组
    indicator_groups = {}  # {seq: [(key, value), ...]}
    form_level_pairs = []  # 非指标级字段

    for k, v in merged.items():
        if k.startswith("pj0601fz_"):
            parts = k.split("_", 2)
            if len(parts) >= 2:
                seq = parts[1]
                indicator_groups.setdefault(seq, []).append((k, v))
                continue
        elif k.startswith("pj0601id_"):
            seq = k.replace("pj0601id_", "")
            indicator_groups.setdefault(seq, []).append((k, v))
            continue
        elif k == "pj06xh":
            continue  # 丢弃，随后为每个指标重新生成
        else:
            form_level_pairs.append((k, v))

    # 按 seq 数值排序
    sorted_seqs = sorted(indicator_groups.keys(), key=int)

    # 构建 POST 数据：表单头部 → 每个指标(pj06xh + 分值 + radio) → 尾部(issubmit)
    post_data = []
    head_keys = {"issubmit"}
    for k, v in form_level_pairs:
        if k not in head_keys:
            post_data.append((k, v))

    for seq in sorted_seqs:
        post_data.append(("pj06xh", seq))
        for k, v in indicator_groups[seq]:
            post_data.append((k, v))

    for k, v in form_level_pairs:
        if k in head_keys:
            post_data.append((k, v))

    return post_data
