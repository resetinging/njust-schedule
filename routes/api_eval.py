"""
南理工课表管理系统 — 教学评价 API 路由
======================================
评价列表、表单解析、单次/批量提交、进度查询。
"""
import json
import os
import time
import threading
import uuid

from flask import Blueprint, request, jsonify

from routes import (
    jwc_client, jwc_lock,
    _batch_progress, _batch_progress_lock,
    _require_login,
)
from database import get_setting, save_evaluations_to_db
from config import DEBUG_EVAL
from eval_helpers import (
    EVAL_HEADERS, warm_eval_session,
    parse_eval_courses_page, parse_eval_form_page,
    auto_fill_eval_indicators, build_ordered_eval_post_data,
)

eval_bp = Blueprint("api_eval", __name__)


# ============================================================
# 评价数据获取
# ============================================================

@eval_bp.route("/api/evaluations")
def api_get_evaluations():
    """获取已存储的教学评价"""
    from database import get_db
    semester = request.args.get(
        "semester", get_setting("semester", jwc_client._current_semester())
    )
    db = get_db()
    rows = db.execute(
        "SELECT * FROM evaluations WHERE semester = ? ORDER BY end_date",
        (semester,),
    ).fetchall()

    evals = []
    for r in rows:
        evals.append({
            "id": r["id"],
            "semester": r["semester"],
            "category": r["category"],
            "batch": r["batch"],
            "start_date": r["start_date"],
            "end_date": r["end_date"],
            "is_done": bool(r["is_done"]),
            "items": json.loads(r["items_json"]) if r["items_json"] else [],
        })

    return jsonify({
        "semester": semester,
        "count": len(evals),
        "evaluations": evals,
    })


@eval_bp.route("/api/refresh-evaluations", methods=["POST"])
def api_refresh_evaluations():
    """刷新教学评价数据"""
    semester = get_setting("semester", jwc_client._current_semester())

    err = _require_login()
    if err:
        return err

    with jwc_lock:
        evals = jwc_client.get_evaluations(semester)

    if not evals and jwc_client.last_error:
        return jsonify({
            "success": False,
            "message": jwc_client.last_error or "获取评价数据失败",
        }), 500

    save_evaluations_to_db(evals, semester)

    undone = sum(1 for e in evals if not e.get("is_done"))
    return jsonify({
        "success": True,
        "message": f"成功获取 {len(evals)} 条评价" + (
            f"，{undone} 条待完成" if undone > 0 else "，全部已完成"
        ),
        "count": len(evals),
        "undone": undone,
    })


# ============================================================
# 评价表单解析
# ============================================================

@eval_bp.route("/api/eval-courses")
def api_eval_courses():
    """解析评教课程列表页（批次点击后的第二级页面）"""
    url = request.args.get("url", "")
    if not url:
        return jsonify({"success": False, "message": "缺少 URL"}), 400
    if not jwc_client.logged_in:
        return jsonify({"success": False, "message": "请先登录"}), 401

    target = f"http://202.119.81.112:9080{url}" if url.startswith("/") else url

    try:
        warm_eval_session()
        resp = jwc_client.session.get(target, headers=EVAL_HEADERS, timeout=15)
        if "非法访问" in resp.text or "非法操作" in resp.text:
            return jsonify({"success": False, "message": "教务系统拒绝了请求"}), 403
    except Exception as e:
        return jsonify({"success": False, "message": f"请求失败: {e}"}), 500

    parsed = parse_eval_courses_page(resp.text)
    if not parsed or not parsed.get("courses"):
        return jsonify({"success": False, "message": "未找到课程列表"}), 500

    return jsonify({
        "success": True,
        "batch_title": parsed["batch_title"],
        "courses": parsed["courses"],
        "hidden_fields": parsed["hidden_fields"],
    })


@eval_bp.route("/api/eval-form")
def api_eval_form():
    """解析评教表单为结构化 JSON（xspj_edit.do 页面）"""
    url = request.args.get("url", "")
    if not url:
        return jsonify({"success": False, "message": "缺少评教 URL"}), 400
    if not jwc_client.logged_in:
        return jsonify({"success": False, "message": "请先登录"}), 401

    target = f"http://202.119.81.112:9080{url}" if url.startswith("/") else url

    try:
        warm_eval_session()
        resp = jwc_client.session.get(target, headers=EVAL_HEADERS, timeout=15)
        if "非法访问" in resp.text or "非法操作" in resp.text:
            return jsonify({"success": False, "message": "教务系统拒绝了请求，请重新登录后重试"}), 403
    except Exception as e:
        return jsonify({"success": False, "message": f"请求失败: {e}"}), 500

    parsed = parse_eval_form_page(resp.text)
    if not parsed or (not parsed.get("course_name") and not parsed.get("indicators")):
        return jsonify({"success": False, "message": "未找到评价表单内容，请返回课程列表重试"}), 500

    return jsonify({
        "success": True,
        "course_name": parsed["course_name"],
        "hidden_fields": parsed["hidden_fields"],
        "indicators": parsed["indicators"],
        "action": parsed["action"],
    })


# ============================================================
# 评价提交
# ============================================================

@eval_bp.route("/api/submit-eval", methods=["POST"])
def api_submit_eval():
    """提交评教数据到教务系统"""
    if not jwc_client.logged_in:
        return jsonify({"success": False, "message": "请先登录"}), 401
    data = request.get_json()
    form_data = data.get("form_data", {})
    submit_type = data.get("submit_type", "0")
    action_path = data.get("action", "/njlgdx/xspj/xspj_save.do")

    form_data["issubmit"] = submit_type
    target_url = f"http://202.119.81.112:9080{action_path}"

    submit_headers = dict(EVAL_HEADERS)

    try:
        radio_keys = [k for k in form_data if k.startswith("pj0601id_")]
        if DEBUG_EVAL:
            debug_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "debug_submit.json")
            with open(debug_path, "w", encoding="utf-8") as f:
                json.dump({
                    "radio_count": len(radio_keys),
                    "radio_keys": radio_keys,
                    "radio_values": {k: form_data[k] for k in radio_keys},
                    "total_keys": len(form_data),
                    "all_keys": list(form_data.keys()),
                }, f, ensure_ascii=False, indent=2)

        warm_eval_session()

        post_data = build_ordered_eval_post_data(form_data, submit_type=submit_type)

        resp = jwc_client.session.post(target_url, data=post_data, headers=submit_headers, timeout=15)

        if DEBUG_EVAL:
            debug_path2 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "debug_submit.json")
            try:
                with open(debug_path2, "r", encoding="utf-8") as f:
                    dbg = json.load(f)
            except Exception:
                dbg = {}
            dbg["post_param_order"] = [k for k, v in post_data]
            dbg["jw_status"] = resp.status_code
            dbg["jw_response_len"] = len(resp.text)
            dbg["jw_response_preview"] = resp.text[:500]
            for kw in ["评价成功", "提交成功", "保存成功", "alert", "错误", "失败", "成功", "不能", "必须"]:
                if kw in resp.text:
                    dbg.setdefault("jw_keywords_found", {})[kw] = True
            with open(debug_path2, "w", encoding="utf-8") as f:
                json.dump(dbg, f, ensure_ascii=False, indent=2)

        if "评价成功" in resp.text or "提交成功" in resp.text or "保存成功" in resp.text:
            return jsonify({"success": True, "message": "评教提交成功！"})
        return jsonify({"success": True, "message": "已提交（请返回教务确认）"})
    except Exception as e:
        return jsonify({"success": False, "message": f"提交失败: {e}"}), 500


# ============================================================
# 批量评教 — 后台 worker + API 端点
# ============================================================

def _run_batch_eval(batch_id: str, courses: list, action_path: str,
                    batch_hidden_fields: dict, target_score: float,
                    submit_type: str):
    """后台线程：逐个课程自动填写并提交评教"""
    total = len(courses)

    for i, course in enumerate(courses):
        with _batch_progress_lock:
            _batch_progress[batch_id].update({
                "current": i + 1,
                "course": course["name"],
                "status": "fetching_form",
                "message": f"正在加载 {course['name']} 的评价表单...",
            })

        try:
            eval_target = f"http://202.119.81.112:9080{course['eval_url']}" if course["eval_url"].startswith("/") else course["eval_url"]

            with jwc_lock:
                warm_eval_session()
                form_resp = jwc_client.session.get(eval_target, headers=EVAL_HEADERS, timeout=15)

            if "非法访问" in form_resp.text or "非法操作" in form_resp.text:
                with _batch_progress_lock:
                    _batch_progress[batch_id]["results"].append({
                        "course": course["name"],
                        "status": "failed",
                        "error": "教务系统拒绝了请求",
                    })
                continue

            parsed = parse_eval_form_page(form_resp.text)
            if not parsed or not parsed.get("indicators"):
                with _batch_progress_lock:
                    _batch_progress[batch_id]["results"].append({
                        "course": course["name"],
                        "status": "failed",
                        "error": "无法解析评价表单",
                    })
                continue

            with _batch_progress_lock:
                _batch_progress[batch_id].update({
                    "status": "auto_filling",
                    "message": f"正在为 {course['name']} 自动评分...",
                })

            selections = auto_fill_eval_indicators(parsed["indicators"], target_score)

            with _batch_progress_lock:
                _batch_progress[batch_id].update({
                    "status": "submitting",
                    "message": f"正在提交 {course['name']} 的评价...",
                })

            form_data = dict(parsed["hidden_fields"])
            form_data["issubmit"] = submit_type
            action = parsed.get("action") or action_path
            target_url = f"http://202.119.81.112:9080{action}"

            post_data = build_ordered_eval_post_data(
                form_data,
                batch_hidden_fields=batch_hidden_fields,
                auto_fill_selections=selections,
                submit_type=submit_type,
            )

            with jwc_lock:
                warm_eval_session()
                resp = jwc_client.session.post(target_url, data=post_data,
                                               headers=EVAL_HEADERS, timeout=15)

            if "评价成功" in resp.text or "提交成功" in resp.text or "保存成功" in resp.text:
                with _batch_progress_lock:
                    _batch_progress[batch_id]["results"].append({
                        "course": course["name"],
                        "status": "success",
                        "score": round(selections.get("_total", 0), 1),
                    })
            else:
                with _batch_progress_lock:
                    _batch_progress[batch_id]["results"].append({
                        "course": course["name"],
                        "status": "failed",
                        "error": "教务未确认提交",
                    })

        except Exception as e:
            with _batch_progress_lock:
                _batch_progress[batch_id]["results"].append({
                    "course": course["name"],
                    "status": "failed",
                    "error": str(e),
                })

    with _batch_progress_lock:
        _batch_progress[batch_id].update({
            "status": "completed",
            "message": "批量评教完成",
            "done": True,
            "course": "",
        })


@eval_bp.route("/api/batch-submit-eval", methods=["POST"])
def api_batch_submit_eval():
    """一键评教：自动完成某个批次下所有未提交课程的评价"""
    if not jwc_client.logged_in:
        return jsonify({"success": False, "message": "请先登录"}), 401

    data = request.get_json()
    batch_url = data.get("batch_url", "")
    target_score = float(data.get("target_score", 95))
    submit_type = str(data.get("submit_type", "1"))

    if not batch_url:
        return jsonify({"success": False, "message": "缺少批次 URL"}), 400
    if not (0 < target_score <= 100):
        return jsonify({"success": False, "message": "目标分数需在 1~100 之间"}), 400

    # 获取批次课程列表
    target = f"http://202.119.81.112:9080{batch_url}" if batch_url.startswith("/") else batch_url

    try:
        with jwc_lock:
            warm_eval_session()
            resp = jwc_client.session.get(target, headers=EVAL_HEADERS, timeout=15)
    except Exception as e:
        return jsonify({"success": False, "message": f"获取课程列表失败: {e}"}), 500

    if "非法访问" in resp.text or "非法操作" in resp.text:
        return jsonify({"success": False, "message": "教务系统拒绝了请求，请重新登录后重试"}), 403

    parsed = parse_eval_courses_page(resp.text)
    if not parsed or not parsed.get("courses"):
        return jsonify({"success": False, "message": "未找到课程列表"}), 500

    # 过滤未提交的课程
    unsubmitted = [c for c in parsed["courses"] if not c.get("submitted")]
    if not unsubmitted:
        return jsonify({
            "success": True,
            "message": "所有课程已提交，无需评价",
            "total": 0,
        })

    # 生成 batch_id，初始化进度，启动后台线程
    batch_id = str(uuid.uuid4())[:8]

    # 从已有 api_eval_form 调用中获知 action_path（默认值）
    action_path = data.get("action_path", "/njlgdx/xspj/xspj_save.do")
    batch_hidden_fields = parsed.get("hidden_fields", {})
    # 合并请求中额外传入的隐藏字段
    if data.get("hidden_fields"):
        batch_hidden_fields.update(data["hidden_fields"])

    with _batch_progress_lock:
        _batch_progress[batch_id] = {
            "current": 0,
            "total": len(unsubmitted),
            "course": "",
            "status": "starting",
            "message": f"准备评价 {len(unsubmitted)} 门课程...",
            "done": False,
            "results": [],
            "created_at": time.time(),
        }

    thread = threading.Thread(
        target=_run_batch_eval,
        args=(batch_id, unsubmitted, action_path, batch_hidden_fields,
              target_score, submit_type),
        daemon=True,
    )
    thread.start()

    return jsonify({
        "success": True,
        "batch_id": batch_id,
        "total": len(unsubmitted),
        "message": f"已开始批量评教，共 {len(unsubmitted)} 门课程",
    })


@eval_bp.route("/api/batch-progress/<batch_id>")
def api_batch_progress(batch_id):
    """查询批量评教进度"""
    with _batch_progress_lock:
        # 清理超过 10 分钟的已完成条目
        now = time.time()
        stale_ids = [
            bid for bid, p in _batch_progress.items()
            if p.get("done") and now - p.get("created_at", 0) > 600
        ]
        for bid in stale_ids:
            del _batch_progress[bid]

        progress = _batch_progress.get(batch_id)
        if not progress:
            return jsonify({"success": False, "message": "未找到此批次"}), 404

        return jsonify({
            "success": True,
            "batch_id": batch_id,
            "current": progress["current"],
            "total": progress["total"],
            "course": progress.get("course", ""),
            "status": progress["status"],
            "message": progress["message"],
            "done": progress["done"],
            "results": progress.get("results", []),
        })
