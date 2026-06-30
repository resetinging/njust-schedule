"""
NJUST 课表 — Flask 路由
=======================
包含：页面路由 + 全量 API + 批量评教后台
"""
import json
import re
import time
import uuid
import threading
from datetime import datetime
from flask import render_template, request, jsonify, g, Response
from bs4 import BeautifulSoup

from wxcloudrun import app, db
from wxcloudrun.jwc_client import JWCClient
from wxcloudrun import dao
from wxcloudrun.response import make_succ_response, make_err_response
from config import DEBUG_EVAL

# ============================================================
# 全局教务客户端
# ============================================================
jwc_client = JWCClient()
jwc_lock = threading.Lock()

_batch_progress = {}
_batch_progress_lock = threading.Lock()

_auto_login_attempted = False
_last_auto_login_time = 0.0

EVAL_HEADERS = {
    "Referer": "http://202.119.81.112:9080/njlgdx/xspj/xspj_find.do",
    "Host": "202.119.81.112:9080",
    "Origin": "http://202.119.81.112:9080",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "max-age=0",
}


def _warm_eval_session():
    jwc_client.session.get(
        "http://202.119.81.112:9080/njlgdx/xspj/xspj_find.do",
        headers={"Referer": "http://202.119.81.112:9080/njlgdx/framework/main.jsp"},
        timeout=10)


# ============================================================
# 页面路由
# ============================================================
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/exams')
def exams_page():
    return render_template('exams.html')


@app.route('/evaluations')
def evaluations_page():
    return render_template('evaluations.html')


@app.route('/settings')
def settings_page():
    return render_template('settings.html')


@app.route('/proxy/jw/<path:target_path>', methods=['GET', 'POST'])
def proxy_jw(target_path):
    if not jwc_client.logged_in:
        return "请先登录教务系统", 401
    target_url = f"http://202.119.81.112:9080/njlgdx/{target_path}"
    qs = request.query_string.decode()
    if qs:
        target_url += "?" + qs
    try:
        if request.method == 'POST':
            resp = jwc_client.session.post(target_url, data=request.form,
                                           headers=EVAL_HEADERS, timeout=15)
        else:
            _warm_eval_session()
            resp = jwc_client.session.get(target_url, headers=EVAL_HEADERS, timeout=15)
    except Exception as e:
        return f"代理请求失败: {e}", 502
    if "text/html" in (resp.headers.get("content-type") or ""):
        content = resp.text
        if "非法访问" in content or "非法操作" in content:
            return Response(f"""
                <html><body style="padding:40px;text-align:center;font-family:sans-serif;">
                <h2>⚠️ 教务系统拒绝了请求</h2><p>{target_path}</p>
                <p><a href="/evaluations">返回评价列表</a></p>
                <p><a href="/settings">重新登录教务系统</a></p>
                </body></html>
            """, status=403)
        for old, new in [
            ('src="/njlgdx/', 'src="/proxy/jw/'),
            ('href="/njlgdx/', 'href="/proxy/jw/'),
            ("src='/njlgdx/", "src='/proxy/jw/"),
            ("href='/njlgdx/", "href='/proxy/jw/"),
            ('action="/njlgdx/', 'action="/proxy/jw/'),
            ("action='/njlgdx/", "action='/proxy/jw/"),
            ('"/njlgdx/js/', '"/proxy/jw/js/'),
            ("'/njlgdx/js/", "'/proxy/jw/js/"),
        ]:
            content = content.replace(old, new)
        return Response(content, status=resp.status_code,
                        content_type="text/html; charset=utf-8")
    return Response(resp.content, status=resp.status_code,
                    content_type=resp.headers.get("content-type", "text/html"))


# ============================================================
# API — 状态 / 连接测试
# ============================================================
@app.route('/api/status')
def api_status():
    student_id = dao.get_setting("student_id")
    student_name = dao.get_setting("student_name")
    semester = dao.get_setting("semester", jwc_client._current_semester())

    has_courses = False
    has_exams = False
    if student_id and semester:
        has_courses = dao.count_courses(semester) > 0
        has_exams = dao.count_exams(semester) > 0

    auto_login_error = ""
    global _auto_login_attempted, _last_auto_login_time
    if not jwc_client.logged_in and student_id:
        if not _auto_login_attempted or (time.time() - _last_auto_login_time) > 30:
            if _auto_login():
                auto_login_error = ""
            else:
                auto_login_error = jwc_client.last_error or "登录失败"

    return jsonify({
        "logged_in": jwc_client.logged_in,
        "student_id": student_id,
        "student_name": student_name or jwc_client.student_name or "",
        "semester": semester or jwc_client._current_semester(),
        "has_courses": has_courses,
        "has_exams": has_exams,
        "login_method": jwc_client.login_method or "",
        "auto_login_attempted": _auto_login_attempted,
        "auto_login_error": auto_login_error,
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.route('/api/connect-test')
def api_connect_test():
    ok, msg = jwc_client.test_connection()
    return jsonify({"ok": ok, "message": msg})


# ============================================================
# API — 登录
# ============================================================
import base64


def _encode_pwd(pwd: str) -> str:
    return base64.b64encode(pwd.encode()).decode()


def _decode_pwd(encoded: str) -> str:
    try:
        return base64.b64decode(encoded.encode()).decode()
    except Exception:
        return ""


def _auto_login() -> bool:
    global _auto_login_attempted, _last_auto_login_time
    _auto_login_attempted = True
    _last_auto_login_time = time.time()
    # 检查 Session 是否真实有效（而非仅信任 logged_in 标志位）
    if jwc_client.logged_in and jwc_client.is_session_valid():
        return True
    # Session 已过期或未登录 → 强制重新登录
    jwc_client.logged_in = False
    sid = dao.get_setting("student_id")
    pwd = _decode_pwd(dao.get_setting("password_enc", ""))
    if not sid or not pwd:
        return False
    jwc_client.login(sid, pwd)
    return jwc_client.logged_in


def _on_login_success(student_id: str, password: str = ""):
    dao.set_setting("student_id", student_id)
    if password:
        dao.set_setting("password_enc", _encode_pwd(password))
    if jwc_client.student_name:
        dao.set_setting("student_name", jwc_client.student_name)
    semester = dao.get_setting("semester")
    if not semester:
        semester = jwc_client._current_semester()
        dao.set_setting("semester", semester)
    return jsonify({
        "success": True,
        "message": f"登录成功！欢迎 {jwc_client.student_name or student_id}",
        "student_name": jwc_client.student_name or student_id,
        "login_method": jwc_client.login_method,
    })


@app.route('/api/get-captcha')
def api_get_captcha():
    with jwc_lock:
        b64, error = jwc_client.get_captcha_base64()
    if error or not b64:
        return jsonify({
            "success": False,
            "message": error or "获取验证码失败",
        }), 500
    return jsonify({
        "success": True,
        "captcha_b64": b64,
        "message": "验证码获取成功",
    })


@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    student_id = (data.get("student_id") or "").strip()
    password = data.get("password") or ""
    if not student_id or not password:
        return jsonify({"success": False, "message": "学号和密码不能为空"}), 400
    with jwc_lock:
        success = jwc_client.login(student_id, password)
    if success:
        return _on_login_success(student_id, password)
    else:
        return jsonify({
            "success": False,
            "message": jwc_client.last_error or "登录失败",
            "need_captcha": "验证码" in (jwc_client.last_error or ""),
        }), 401


@app.route('/api/login-manual', methods=['POST'])
def api_login_manual():
    data = request.get_json()
    student_id = (data.get("student_id") or "").strip()
    password = data.get("password") or ""
    captcha_text = (data.get("captcha") or "").strip()
    if not student_id or not password:
        return jsonify({"success": False, "message": "学号和密码不能为空"}), 400
    if not captcha_text:
        return jsonify({"success": False, "message": "请先输入验证码"}), 400
    with jwc_lock:
        success = jwc_client.login_with_manual_captcha(student_id, password, captcha_text)
    if success:
        return _on_login_success(student_id, password)
    else:
        return jsonify({
            "success": False,
            "message": jwc_client.last_error or "登录失败",
        }), 401


# ============================================================
# API — 数据刷新
# ============================================================
def _require_login():
    if not jwc_client.logged_in or not jwc_client.is_session_valid():
        jwc_client.logged_in = False
        auto_ok = _auto_login()
        student_id = dao.get_setting("student_id")
        if not student_id:
            return jsonify({
                "success": False,
                "message": "尚未登录，请先在设置页面登录",
            }), 401
        if not auto_ok:
            err = jwc_client.last_error or "教务系统不可达"
            return jsonify({
                "success": False,
                "message": f"自动登录失败: {err}",
            }), 401
    return None


def _retry_with_relogin(fetch_func, error_msg: str):
    """执行数据获取，若失败则重新登录后重试一次"""
    result = fetch_func()
    if result:
        return result, None
    # 失败 → 强制重新登录
    jwc_client.logged_in = False
    if not _auto_login():
        return [], jsonify({
            "success": False,
            "message": f"{error_msg}: 自动重新登录失败 — {jwc_client.last_error}",
        }), 500
    # 重试
    result = fetch_func()
    if result:
        return result, None
    return [], jsonify({
        "success": False,
        "message": jwc_client.last_error or error_msg,
    }), 500


@app.route('/api/refresh-schedule', methods=['POST'])
def api_refresh_schedule():
    semester = dao.get_setting("semester", jwc_client._current_semester())
    err = _require_login()
    if err:
        return err
    with jwc_lock:
        courses, retry_err = _retry_with_relogin(
            lambda: jwc_client.get_schedule(semester),
            "获取课表失败",
        )
    if retry_err:
        return retry_err
    dao.save_courses(courses, semester)
    dao.set_setting("semester", semester)
    return jsonify({
        "success": True,
        "message": f"成功获取 {len(courses)} 门课程",
        "count": len(courses),
        "semester": semester,
    })


@app.route('/api/refresh-exams', methods=['POST'])
def api_refresh_exams():
    semester = dao.get_setting("semester", jwc_client._current_semester())
    err = _require_login()
    if err:
        return err
    with jwc_lock:
        exams, retry_err = _retry_with_relogin(
            lambda: jwc_client.get_exams(semester),
            "获取考试失败",
        )
    if retry_err:
        return retry_err
    dao.save_exams(exams, semester)
    return jsonify({
        "success": True,
        "message": f"成功获取 {len(exams)} 场考试",
        "count": len(exams),
    })


@app.route('/api/refresh-all', methods=['POST'])
def api_refresh_all():
    semester = dao.get_setting("semester", jwc_client._current_semester())
    err = _require_login()
    if err:
        return err
    results = {"schedule": None, "exams": None}
    with jwc_lock:
        courses, sched_err = _retry_with_relogin(
            lambda: jwc_client.get_schedule(semester),
            "获取课表失败",
        )
        if not sched_err:
            dao.save_courses(courses, semester)
            results["schedule"] = {"count": len(courses), "ok": True}
        else:
            results["schedule"] = {"count": 0, "ok": False, "error": jwc_client.last_error}

        exams, exam_err = _retry_with_relogin(
            lambda: jwc_client.get_exams(semester),
            "获取考试失败",
        )
        if not exam_err:
            dao.save_exams(exams, semester)
            results["exams"] = {"count": len(exams), "ok": True}
        else:
            results["exams"] = {"count": 0, "ok": False, "error": jwc_client.last_error}

    dao.set_setting("semester", semester)
    return jsonify({
        "success": True,
        "semester": semester,
        "schedule": results["schedule"],
        "exams": results["exams"],
        "message": f"课表: {results['schedule']['count']}门, 考试: {results['exams']['count']}场",
    })


# ============================================================
# API — 数据查询
# ============================================================
@app.route('/api/courses')
def api_get_courses():
    semester = request.args.get("semester", dao.get_setting("semester", jwc_client._current_semester()))
    courses = dao.get_courses(semester)
    return jsonify({
        "semester": semester,
        "count": len(courses),
        "courses": courses,
    })


@app.route('/api/exams')
def api_get_exams():
    semester = request.args.get("semester", dao.get_setting("semester", jwc_client._current_semester()))
    exams = dao.get_exams(semester)
    return jsonify({
        "semester": semester,
        "count": len(exams),
        "exams": exams,
    })


@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'GET':
        settings = {
            "student_id": dao.get_setting("student_id"),
            "student_name": dao.get_setting("student_name"),
            "semester": dao.get_setting("semester"),
            "auto_refresh": dao.get_setting("auto_refresh", "false"),
            "refresh_interval": dao.get_setting("refresh_interval", "3600"),
            "semester_list": jwc_client.get_semester_list(),
            "current_semester": jwc_client._current_semester(),
            "has_password": bool(dao.get_setting("password_enc", "")),
        }
        return jsonify(settings)
    else:
        data = request.get_json()
        for key, value in data.items():
            if key in ("student_id", "student_name", "semester",
                       "auto_refresh", "refresh_interval"):
                dao.set_setting(key, str(value))
        return jsonify({"success": True, "message": "设置已保存"})


@app.route('/api/semesters')
def api_get_semesters():
    """获取可用学期列表"""
    try:
        semesters = jwc_client.get_semester_list()
        current = jwc_client._current_semester()
        return jsonify({"success": True, "semesters": semesters, "current": current})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/semester', methods=['POST'])
def api_set_semester():
    data = request.get_json()
    semester = (data.get("semester") or "").strip()
    if not semester:
        return jsonify({"success": False, "message": "学期不能为空"}), 400
    dao.set_setting("semester", semester)
    return jsonify({"success": True, "message": f"已切换到学期: {semester}"})


@app.route('/api/evaluations')
def api_get_evaluations():
    semester = request.args.get("semester", dao.get_setting("semester", jwc_client._current_semester()))
    evals = dao.get_evaluations(semester)
    return jsonify({
        "semester": semester,
        "count": len(evals),
        "evaluations": evals,
    })


@app.route('/api/refresh-evaluations', methods=['POST'])
def api_refresh_evaluations():
    semester = dao.get_setting("semester", jwc_client._current_semester())
    err = _require_login()
    if err:
        return err
    with jwc_lock:
        evals, retry_err = _retry_with_relogin(
            lambda: jwc_client.get_evaluations(semester),
            "获取评价数据失败",
        )
    if retry_err:
        return retry_err
    dao.save_evaluations(evals, semester)
    undone = sum(1 for e in evals if not e.get("is_done"))
    return jsonify({
        "success": True,
        "message": f"成功获取 {len(evals)} 条评价" + (f"，{undone} 条待完成" if undone > 0 else ""),
        "count": len(evals),
        "undone": undone,
    })


# ============================================================
# 评教 — 页面解析
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


# ============================================================
# 评教 — 自动填写算法
# ============================================================
def _auto_fill_eval_indicators(indicators: list, target_score: float = 95.0) -> dict:
    if not indicators:
        return {"_total": 0}
    indicator_scores = []
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
        indicator_scores.append({"seq": ind.get("seq", ""), "max_score": ind_max, "options": scored_opts})
    if total_max <= 0:
        return {"_total": 0}

    # 贪心
    selections = []
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
            "seq": iscore["seq"], "colIndex": best_idx, "score": chosen["score"],
            "name": chosen["name"], "value": chosen["value"], "options": iscore["options"],
        })

    def _all_same_column(sels):
        if len(sels) <= 1:
            return False
        return all(s["colIndex"] == sels[0]["colIndex"] for s in sels)

    # 防作弊
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
                    best_combo = {"sacrifice_idx": sacrifice_idx, "colIndex": alt_opt["idx"],
                                  "score": alt_opt["score"], "name": alt_opt["name"], "value": alt_opt["value"]}
        if best_combo:
            idx = best_combo["sacrifice_idx"]
            selections[idx]["colIndex"] = best_combo["colIndex"]
            selections[idx]["score"] = best_combo["score"]
            selections[idx]["name"] = best_combo["name"]
            selections[idx]["value"] = best_combo["value"]

    # 单指标微调
    no_improve = 0
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
                saved_col, saved_score = selections[i]["colIndex"], selections[i]["score"]
                selections[i]["colIndex"], selections[i]["score"] = alt_opt["idx"], alt_opt["score"]
                all_same = _all_same_column(selections)
                selections[i]["colIndex"], selections[i]["score"] = saved_col, saved_score
                if all_same:
                    continue
                if new_penalty < best_penalty:
                    best_penalty = new_penalty
                    best_swap = {"idx": i, "colIndex": alt_opt["idx"], "score": alt_opt["score"],
                                 "name": alt_opt["name"], "value": alt_opt["value"]}
        if best_swap and best_penalty < current_penalty:
            idx = best_swap["idx"]
            selections[idx]["colIndex"] = best_swap["colIndex"]
            selections[idx]["score"] = best_swap["score"]
            selections[idx]["name"] = best_swap["name"]
            selections[idx]["value"] = best_swap["value"]
            no_improve = 0
        else:
            no_improve += 1
            if no_improve >= 3:
                break

    result = {}
    for s in selections:
        result[s["seq"]] = (s["name"], s["value"])
    result["_total"] = sum(s["score"] for s in selections)
    return result


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
# API — 评教操作
# ============================================================
@app.route('/api/eval-courses')
def api_eval_courses():
    url = request.args.get("url", "")
    if not url:
        return jsonify({"success": False, "message": "缺少 URL"}), 400
    if not jwc_client.logged_in:
        return jsonify({"success": False, "message": "请先登录"}), 401
    target = f"http://202.119.81.112:9080{url}" if url.startswith("/") else url
    try:
        _warm_eval_session()
        resp = jwc_client.session.get(target, headers=EVAL_HEADERS, timeout=15)
        if "非法访问" in resp.text or "非法操作" in resp.text:
            return jsonify({"success": False, "message": "教务系统拒绝了请求"}), 403
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


@app.route('/api/eval-form')
def api_eval_form():
    url = request.args.get("url", "")
    if not url:
        return jsonify({"success": False, "message": "缺少评教 URL"}), 400
    if not jwc_client.logged_in:
        return jsonify({"success": False, "message": "请先登录"}), 401
    target = f"http://202.119.81.112:9080{url}" if url.startswith("/") else url
    try:
        _warm_eval_session()
        resp = jwc_client.session.get(target, headers=EVAL_HEADERS, timeout=15)
        if "非法访问" in resp.text or "非法操作" in resp.text:
            return jsonify({"success": False, "message": "教务系统拒绝了请求"}), 403
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


@app.route('/api/submit-eval', methods=['POST'])
def api_submit_eval():
    if not jwc_client.logged_in:
        return jsonify({"success": False, "message": "请先登录"}), 401
    data = request.get_json()
    form_data = data.get("form_data", {})
    submit_type = data.get("submit_type", "0")
    action_path = data.get("action", "/njlgdx/xspj/xspj_save.do")
    form_data["issubmit"] = submit_type
    target_url = f"http://202.119.81.112:9080{action_path}"
    try:
        _warm_eval_session()
        post_data = _build_ordered_eval_post_data(form_data, submit_type=submit_type)
        resp = jwc_client.session.post(target_url, data=post_data, headers=EVAL_HEADERS, timeout=15)
        if "评价成功" in resp.text or "提交成功" in resp.text or "保存成功" in resp.text:
            return jsonify({"success": True, "message": "评教提交成功！"})
        return jsonify({"success": True, "message": "已提交（请返回教务确认）"})
    except Exception as e:
        return jsonify({"success": False, "message": f"提交失败: {e}"}), 500


# ============================================================
# 批量评教
# ============================================================
def _run_batch_eval(batch_id, courses, action_path, batch_hidden_fields, target_score, submit_type):
    total = len(courses)
    action_verb = "提交" if submit_type == "1" else "保存"
    for i, course in enumerate(courses):
        with _batch_progress_lock:
            _batch_progress[batch_id].update({
                "current": i + 1, "course": course["name"],
                "status": "fetching_form", "message": f"正在加载 {course['name']}...",
            })
        try:
            eval_target = f"http://202.119.81.112:9080{course['eval_url']}" if course["eval_url"].startswith("/") else course["eval_url"]
            with jwc_lock:
                _warm_eval_session()
                form_resp = jwc_client.session.get(eval_target, headers=EVAL_HEADERS, timeout=15)
            if "非法访问" in form_resp.text or "非法操作" in form_resp.text:
                with _batch_progress_lock:
                    _batch_progress[batch_id]["results"].append({"course": course["name"], "status": "failed", "error": "教务拒绝"})
                continue
            parsed = _parse_eval_form_page(form_resp.text)
            if not parsed or not parsed.get("indicators"):
                with _batch_progress_lock:
                    _batch_progress[batch_id]["results"].append({"course": course["name"], "status": "failed", "error": "无法解析表单"})
                continue
            with _batch_progress_lock:
                _batch_progress[batch_id].update({"status": "auto_filling", "message": f"正在为 {course['name']} 自动评分..."})
            selections = _auto_fill_eval_indicators(parsed["indicators"], target_score)
            with _batch_progress_lock:
                _batch_progress[batch_id].update({"status": "submitting", "message": f"正在{action_verb} {course['name']}..."})
            form_data = dict(parsed["hidden_fields"])
            form_data["issubmit"] = submit_type
            action = parsed.get("action") or action_path
            target_url = f"http://202.119.81.112:9080{action}"
            post_data = _build_ordered_eval_post_data(form_data, batch_hidden_fields=batch_hidden_fields,
                                                      auto_fill_selections=selections, submit_type=submit_type)
            with jwc_lock:
                _warm_eval_session()
                resp = jwc_client.session.post(target_url, data=post_data, headers=EVAL_HEADERS, timeout=15)
            if "评价成功" in resp.text or "提交成功" in resp.text or "保存成功" in resp.text:
                with _batch_progress_lock:
                    _batch_progress[batch_id]["results"].append({
                        "course": course["name"], "status": "success",
                        "score": round(selections.get("_total", 0), 1),
                    })
            else:
                with _batch_progress_lock:
                    _batch_progress[batch_id]["results"].append({"course": course["name"], "status": "failed", "error": "教务未确认"})
        except Exception as e:
            with _batch_progress_lock:
                _batch_progress[batch_id]["results"].append({"course": course["name"], "status": "failed", "error": str(e)})
    with _batch_progress_lock:
        _batch_progress[batch_id].update({"status": "completed", "message": f"批量{action_verb}完成", "done": True, "course": ""})


@app.route('/api/batch-submit-eval', methods=['POST'])
def api_batch_submit_eval():
    if not jwc_client.logged_in:
        return jsonify({"success": False, "message": "请先登录"}), 401
    data = request.get_json()
    batch_url = data.get("batch_url", "")
    target_score = float(data.get("target_score", 95))
    submit_type = str(data.get("submit_type", "1"))
    mode = data.get("mode", "")
    if not batch_url:
        return jsonify({"success": False, "message": "缺少批次 URL"}), 400
    if not (0 < target_score <= 100):
        return jsonify({"success": False, "message": "目标分数需在 1~100 之间"}), 400
    target = f"http://202.119.81.112:9080{batch_url}" if batch_url.startswith("/") else batch_url
    try:
        with jwc_lock:
            _warm_eval_session()
            resp = jwc_client.session.get(target, headers=EVAL_HEADERS, timeout=15)
    except Exception as e:
        return jsonify({"success": False, "message": f"获取课程列表失败: {e}"}), 500
    if "非法访问" in resp.text or "非法操作" in resp.text:
        return jsonify({"success": False, "message": "教务系统拒绝了请求"}), 403
    parsed = _parse_eval_courses_page(resp.text)
    if not parsed or not parsed.get("courses"):
        return jsonify({"success": False, "message": "未找到课程列表"}), 500
    if mode == "save":
        targets = [c for c in parsed["courses"] if not c.get("evaluated") and not c.get("submitted")]
        action_desc, empty_msg = "保存", "所有课程均已保存或提交"
    elif mode == "submit":
        targets = [c for c in parsed["courses"] if c.get("evaluated") and not c.get("submitted")]
        action_desc, empty_msg = "提交", "没有已保存待提交的课程"
    else:
        targets = [c for c in parsed["courses"] if not c.get("submitted")]
        action_desc, empty_msg = "评教", "所有课程已提交"
    if not targets:
        return jsonify({"success": True, "message": empty_msg, "total": 0})
    batch_id = str(uuid.uuid4())[:8]
    action_path = data.get("action_path", "/njlgdx/xspj/xspj_save.do")
    batch_hidden_fields = parsed.get("hidden_fields", {})
    if data.get("hidden_fields"):
        batch_hidden_fields.update(data["hidden_fields"])
    with _batch_progress_lock:
        _batch_progress[batch_id] = {
            "current": 0, "total": len(targets), "course": "", "status": "starting",
            "message": f"准备{action_desc} {len(targets)} 门课程...", "done": False, "results": [],
            "created_at": time.time(), "mode": mode,
        }
    thread = threading.Thread(target=_run_batch_eval, args=(
        batch_id, targets, action_path, batch_hidden_fields, target_score, submit_type), daemon=True)
    thread.start()
    return jsonify({
        "success": True, "batch_id": batch_id, "total": len(targets),
        "message": f"已开始批量{action_desc}，共 {len(targets)} 门课程",
    })


@app.route('/api/batch-progress/<batch_id>')
def api_batch_progress(batch_id):
    with _batch_progress_lock:
        now = time.time()
        stale_ids = [bid for bid, p in _batch_progress.items()
                     if p.get("done") and now - p.get("created_at", 0) > 600]
        for bid in stale_ids:
            del _batch_progress[bid]
        progress = _batch_progress.get(batch_id)
        if not progress:
            return jsonify({"success": False, "message": "未找到此批次"}), 404
        return jsonify({
            "success": True, "batch_id": batch_id,
            "current": progress["current"], "total": progress["total"],
            "course": progress.get("course", ""), "status": progress["status"],
            "message": progress["message"], "done": progress["done"],
            "results": progress.get("results", []),
        })


# ============================================================
# API — 清除数据
# ============================================================
@app.route('/api/clear-data', methods=['POST'])
def api_clear_data():
    semester = dao.get_setting("semester", jwc_client._current_semester())
    dao.clear_data(semester)
    return jsonify({"success": True, "message": "数据已清除"})


# ============================================================
# 错误处理
# ============================================================
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "页面不存在"}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "服务器内部错误"}), 500
