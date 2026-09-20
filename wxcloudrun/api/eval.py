# -*- coding: utf-8 -*-
"""教学评价路由与页面解析(Phase 1b 从 views.py 拆出)。"""
import json
import re

from flask import Blueprint, jsonify, request

import config
from wxcloudrun import app, dao
from wxcloudrun.core.auth import _require_login, _retry_with_relogin
from wxcloudrun.core.cache import _cache_get, _cache_set, invalidate_user_cache
from wxcloudrun.core.pool import _jwc_request
from wxcloudrun.core.stats import _invalidate_stats
from wxcloudrun.core.web import _rid
from wxcloudrun.jwc_client import JWCClient

eval_bp = Blueprint("eval_api", __name__)
jwc_client = JWCClient()


def _current_semester() -> str:
    """当前学期(views 实现, 延迟导入避免循环)"""
    from wxcloudrun.views import _current_semester as _impl
    return _impl()


def _warm_eval_session(client):
    """评教会话预热(views 实现, 延迟引用)"""
    from wxcloudrun.views import _warm_eval_session as _impl
    return _impl(client)


@eval_bp.route('/api/evaluations')
def api_get_evaluations():
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""
    cache_key = f"{sid}:evaluations"
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)
    # 评教是待办事项: 返回该账号全部批次(不过滤学期), 批次自带 semester 字段
    evals = dao.get_evaluations("", sid)
    resp = {
        "success": True,
        "count": len(evals),
        "evaluations": evals,
    }
    _cache_set(cache_key, resp)
    return jsonify(resp)


@eval_bp.route('/api/refresh-evaluations', methods=['POST'])
def api_refresh_evaluations():
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""
    with _jwc_request(client):
        evals, retry_err = _retry_with_relogin(
            client, lambda: client.get_evaluations(""), "获取评价数据失败")
    if retry_err:
        return retry_err
    dao.save_evaluations(evals, "", sid)
    invalidate_user_cache(sid, "evaluations")
    undone = sum(1 for e in evals if not e.get("is_done"))
    return jsonify({
        "success": True,
        "message": f"成功获取 {len(evals)} 条评价" + (f"，{undone} 条待完成" if undone > 0 else ""),
        "count": len(evals),
        "undone": undone,
    })


# ============================================================
# 评教 — 页面解析（网关层，评分由前端完成）
# ============================================================
def _parse_eval_courses_page(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    title_el = soup.select_one(".Nsb_r_title")
    batch_title = title_el.get_text(strip=True) if title_el else "评教课程"
    form = soup.find("form", id="Form1")
    hidden_fields = {}
    if form:
        for inp in form.find_all("input", type="hidden"):
            name = inp.get("name", "")
            value = inp.get("value", "")
            if name:
                hidden_fields[name] = value
    courses = []
    data_table = soup.find("table", id="dataList")
    if data_table:
        for row in data_table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) < 8:
                continue
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


def _parse_eval_form_page(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    th = soup.find("th", class_="Nsb_r_list_thb")
    course_info = th.get_text() if th else ""
    course_name = ""
    m = re.search(r'课程名称[：:]\s*(.+?)(?:\s{2,}|\xa0|$)', course_info)
    if m:
        course_name = m.group(1).strip()
    form = soup.find("form", id="Form1")
    hidden_fields = {}
    if form:
        for inp in form.find_all("input", type="hidden"):
            name = inp.get("name", "")
            value = inp.get("value", "")
            if name:
                hidden_fields[name] = value
    indicators = []
    for row in soup.select("#table1 tr"):
        tds = row.find_all("td")
        if len(tds) < 2:
            continue
        label = tds[0].get_text(strip=True)
        if not label or "评价指标" in label:
            continue
        seq_input = tds[0].find("input", attrs={"name": "pj06xh"})
        seq = seq_input.get("value", "") if seq_input else ""
        fz_map = {}
        for inp in tds[1].find_all("input", type="hidden"):
            fz_name = inp.get("name", "")
            fz_value = inp.get("value", "")
            if fz_name.startswith("pj0601fz_"):
                hidden_fields[fz_name] = fz_value
                parts = fz_name.rsplit("_", 1)
                if len(parts) == 2:
                    fz_map[parts[1]] = fz_value
        options = []
        for radio in tds[1].find_all("input", type="radio"):
            opt_name = radio.get("name", "")
            opt_value = radio.get("value", "")
            opt_score = fz_map.get(opt_value, "")
            opt_checked = radio.has_attr("checked")
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
    form_action = form.get("action", "") if form else ""
    return {
        "course_name": course_name,
        "hidden_fields": hidden_fields,
        "indicators": indicators,
        "action": form_action,
    }


def _build_ordered_eval_post_data(form_data: dict, batch_hidden_fields=None,
                                  auto_fill_selections=None, submit_type: str = "1") -> list:
    merged = dict(form_data)
    if batch_hidden_fields:
        for k, v in batch_hidden_fields.items():
            if k not in merged:
                merged[k] = v
    if auto_fill_selections:
        for seq, val in auto_fill_selections.items():
            if seq == "_total":
                continue
            name, value = val
            merged[name] = value
    indicator_groups = {}
    form_level_pairs = []
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
            continue
        else:
            form_level_pairs.append((k, v))
    sorted_seqs = sorted(indicator_groups.keys(), key=int)
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


# ============================================================
# API — 评教操作（多用户：使用请求 token 对应的会话）
# ============================================================
def _fetch_with_client(client: JWCClient, url: str):
    """用用户会话 GET 教务页面，检查非法访问"""
    target = f"http://202.119.81.112:9080{url}" if url.startswith("/") else url
    _warm_eval_session(client)
    resp = client.session.get(target, headers=EVAL_HEADERS, timeout=15)
    if "非法访问" in resp.text or "非法操作" in resp.text:
        return None, jsonify({"success": False, "message": "教务系统拒绝了请求"}), 403
    return resp, None, None


@eval_bp.route('/api/eval-courses')
def api_eval_courses():
    url = request.args.get("url", "")
    if not url:
        return jsonify({"success": False, "message": "缺少 URL"}), 400
    client, err = _require_login()
    if err:
        return err
    try:
        resp, err_resp, status = _fetch_with_client(client, url)
        if err_resp is not None:
            return err_resp, status
    except Exception as e:
        return jsonify({"success": False, "message": f"请求失败: {e}"}), 500
    parsed = _parse_eval_courses_page(resp.text)
    if not parsed or not parsed.get("courses"):
        return jsonify({"success": False, "message": "未找到课程列表"}), 500
    return jsonify({
        "success": True,
        "batch_title": parsed["batch_title"],
        "courses": parsed["courses"],
        "hidden_fields": parsed["hidden_fields"],
    })


@eval_bp.route('/api/eval-form')
def api_eval_form():
    url = request.args.get("url", "")
    if not url:
        return jsonify({"success": False, "message": "缺少评教 URL"}), 400
    client, err = _require_login()
    if err:
        return err
    try:
        resp, err_resp, status = _fetch_with_client(client, url)
        if err_resp is not None:
            return err_resp, status
    except Exception as e:
        return jsonify({"success": False, "message": f"请求失败: {e}"}), 500
    parsed = _parse_eval_form_page(resp.text)
    if not parsed or (not parsed.get("course_name") and not parsed.get("indicators")):
        return jsonify({"success": False, "message": "未找到评价表单"}), 500
    return jsonify({
        "success": True,
        "course_name": parsed["course_name"],
        "hidden_fields": parsed["hidden_fields"],
        "indicators": parsed["indicators"],
        "action": parsed["action"],
    })


@eval_bp.route('/api/submit-eval', methods=['POST'])
def api_submit_eval():
    client, err = _require_login()
    if err:
        return err
    data = request.get_json()
    form_data = data.get("form_data", {})
    submit_type = data.get("submit_type", "0")
    action_path = data.get("action", "/njlgdx/xspj/xspj_save.do")
    form_data["issubmit"] = submit_type
    target_url = f"http://202.119.81.112:9080{action_path}"
    try:
        _warm_eval_session(client)
        post_data = _build_ordered_eval_post_data(form_data, submit_type=submit_type)
        resp = client.session.post(target_url, data=post_data, headers=EVAL_HEADERS, timeout=15)
        if "评价成功" in resp.text or "提交成功" in resp.text or "保存成功" in resp.text:
            return jsonify({"success": True, "message": "评教提交成功！"})
        return jsonify({"success": True, "message": "已提交（请返回教务确认）"})
    except Exception as e:
        return jsonify({"success": False, "message": f"提交失败: {e}"}), 500


@eval_bp.route('/api/jw-proxy', methods=['POST'])
def api_jw_proxy():
    """通用教务网关: 用当前用户会话转发任意 9080 请求,返回原始内容。

    方案 A(薄后端)核心接口: 前端负责业务逻辑,后端只做认证 + 转发。

    参数:
        method: "GET" | "POST"
        path: 教务路径,如 "/njlgdx/xskb/xskb_list.do?Ves632DSdyV=..."
              (query 可拼在 path 里,或单独传 query)
        data: POST 表单参数 {key: value}
    返回:
        success/status/content_type/text(文本) 或 data_b64(二进制)
    """
    client, err = _require_login()
    if err:
        return err
    data = request.get_json() or {}
    method = (data.get("method") or "GET").upper()
    path = (data.get("path") or "").strip()
    if not path:
        return jsonify({"success": False, "message": "缺少 path"}), 400
    if method not in ("GET", "POST"):
        return jsonify({"success": False, "message": "method 仅支持 GET/POST"}), 400
    if not path.startswith("/"):
        path = "/" + path

    target = f"http://202.119.81.112:9080{path}"
    qs = data.get("query")
    if qs and isinstance(qs, str):
        target += "?" + qs.lstrip("?")
    form_data = data.get("data") or {}
    if not isinstance(form_data, dict):
        form_data = {}

    try:
        with _jwc_request(client):
            _warm_eval_session(client)
            if method == "POST":
                resp = client.session.post(target, data=form_data,
                                           headers=EVAL_HEADERS, timeout=15)
            else:
                resp = client.session.get(target, headers=EVAL_HEADERS, timeout=15)
    except Exception as e:
        return jsonify({"success": False, "message": f"请求失败: {e}"}), 502

    content_type = resp.headers.get("content-type") or ""
    if content_type.startswith(("text/", "application/json", "application/javascript")):
        return jsonify({
            "success": True,
            "status": resp.status_code,
            "content_type": content_type,
            "text": resp.text,
        })
    # 二进制内容(图片等) → base64
    return jsonify({
        "success": True,
        "status": resp.status_code,
        "content_type": content_type,
        "data_b64": base64.b64encode(resp.content).decode(),
    })


# ============================================================
# API — 清除数据（按用户隔离）
# ============================================================
