"""
南理工课表管理系统 — 绩点计算模块
==============================
成绩→绩点换算（NJUST 4.0 量表）和加权平均 GPA 计算。
"""
from collections import OrderedDict

# 非正式成绩状态（不参与绩点计算）
_NON_GRADE_STATUS = {"缓考", "缺考", "免修", "作弊", "违纪", "取消", "旷考", "休学"}

# 不计入 GPA 的课程性质（NJUST 教务统一口径：通识公共选修课不参与评奖/保研绩点）
_NON_GPA_NATURES = {"通识教育选修课"}


def is_gpa_course(course_nature: str) -> bool:
    """判断课程是否计入平均学分绩点（评奖、保研、学籍审核）

    不计入：通识教育选修课（校公选、素质拓展类）
    计入：必修课、专业选修课、专业限选课等所有其他课程
    """
    return (course_nature or "").strip() not in _NON_GPA_NATURES


def score_to_gp(score) -> float:
    """将百分制成绩或等级制成绩转换为绩点（NJUST 4.0 量表）

    返回值：
    - 正数 / 0：有效绩点（0 = 不及格，仍计入加权平均）
    - -1：非正式成绩（缓考/缺考/免修等，不参与计算）
    """
    # 文字等级（NJUST 五级制 + 带加减的扩展等级）
    level_map = {
        # 优秀档（90-100）
        "优": 4.0, "优秀": 4.0,
        "优-": 3.7, "优秀-": 3.7,
        # 良好档（80-89）
        "良+": 3.3, "良好+": 3.3,
        "良": 3.0, "良好": 3.0,
        "良-": 2.7, "良好-": 2.7,
        # 中等档（70-79）
        "中+": 2.3, "中等+": 2.3,
        "中": 2.0, "中等": 2.0,
        "中-": 1.5, "中等-": 1.5,
        # 及格档（60-69）
        "及格": 1.0, "通过": 1.0,
        # 不及格
        "不及格": 0, "不通过": 0,
    }
    s = str(score).strip()
    if s in level_map:
        return level_map[s]
    # 非正式成绩状态 → 排除
    if s in _NON_GRADE_STATUS:
        return -1.0
    # 百分制 → 绩点（NJUST 官方换算表，.0/.5 精度）
    try:
        v = float(s)
    except (ValueError, TypeError):
        return -1.0  # 无法识别的文字（如教务系统特殊标记），排除
    if v >= 90:
        return 4.0   # 90.0~100.0 → 优
    if v >= 85:
        return 3.7   # 85.0~89.5  → 优-
    if v >= 82:
        return 3.3   # 82.0~84.5  → 良+
    if v >= 78:
        return 3.0   # 78.0~81.5  → 良
    if v >= 75:
        return 2.7   # 75.0~77.5  → 良-
    if v >= 72:
        return 2.3   # 72.0~74.5  → 中+
    if v >= 68:
        return 2.0   # 68.0~71.5  → 中
    if v >= 64:
        return 1.5   # 64.0~67.5  → 中-
    if v >= 60:
        return 1.0   # 60.0~63.5  → 及格
    return 0                   # < 60.0     → 不及格


def calc_gpa(grades: list[dict], gpa_only: bool = True) -> float:
    """计算加权平均绩点 Σ(学分×绩点) / Σ学分

    不及格课程（绩点=0）计入分母，拉低平均；
    缓考/缺考/免修等非正式成绩（绩点=-1）不计入。

    参数:
        grades: 成绩列表，每项含 credit, grade_point, score
        gpa_only: True 时排除通识教育选修课（评奖/保研口径）
    """
    total_weighted = 0.0
    total_credits = 0.0
    for g in grades:
        if gpa_only and not is_gpa_course(g.get("course_nature", "")):
            continue
        credit = float(g.get("credit", 0) or 0)
        if credit <= 0:
            continue
        gp = float(g.get("grade_point", 0) or 0)
        if gp == 0:
            # 数据库无绩点，从成绩换算（可能返回 -1 表示排除）
            gp = score_to_gp(g.get("score", ""))
        if gp >= 0:
            total_weighted += credit * gp
            total_credits += credit
    return round(total_weighted / total_credits, 2) if total_credits > 0 else 0.0


def calc_semester_gpas(grades: list[dict]) -> list[dict]:
    """计算每个学期的绩点汇总

    参数:
        grades: 成绩字典列表，每项含 academic_year, semester, course_name,
                score, credit, grade_point, course_nature

    返回按学期排序的列表: [{semester, gpa, gpa_all, credits, count}, ...]
    其中 gpa 为排除通识选修课后的计内绩点（评奖/保研口径）
    """
    # 按学期分组
    groups = OrderedDict()
    for r in grades:
        key = f"{r.get('academic_year', '')}-{r.get('semester', '')}"
        if key not in groups:
            groups[key] = []
        groups[key].append({
            "course_name": r.get("course_name", ""),
            "score": r.get("score", ""),
            "credit": r.get("credit", 0),
            "grade_point": r.get("grade_point", 0),
            "course_nature": r.get("course_nature", "") or "",
        })

    result = []
    for sem, items in groups.items():
        # 补充绩点
        for g in items:
            if float(g.get("grade_point", 0) or 0) == 0:
                g["grade_point"] = score_to_gp(g.get("score", ""))

        gpa_all = calc_gpa(items, gpa_only=False)
        gpa_counted = calc_gpa(items, gpa_only=True)

        counted_items = [g for g in items if is_gpa_course(g.get("course_nature", ""))]
        counted_credits = round(sum(
            float(g.get("credit", 0) or 0) for g in counted_items
        ), 1)

        result.append({
            "semester": sem,
            "gpa": gpa_counted,
            "gpa_all": gpa_all,
            "credits": counted_credits,
            "count": len(counted_items),
        })

    return result


# ================================================================
# 四六级折算 & 保研 GPA 模式
# ================================================================

def cet_to_percentage(cet_score: float, cet_type: str) -> float:
    """四六级分数 → 百分制折算（NJUST 官方公式）

    CET4: 基础分 = (分数 - 425) / 285 × 40 + 60
    CET6: 基础分 + 5（封顶 100）

    返回: 百分制分数（60~100），< 425 返回 0 表示不可用
    """
    if cet_score < 425:
        return 0.0
    base = (cet_score - 425) / 285.0 * 40 + 60
    if cet_type == "CET6":
        base = min(base + 5, 100.0)
    return round(base, 1)


def is_english_course(course_name: str) -> bool:
    """判断是否为英语课（保研模式中被 CET 替换）

    匹配: "通用英语" 或 "专用英语-*"
    """
    name = course_name.strip()
    return name == "通用英语" or name.startswith("专用英语-")


def calc_gpa_baoyan(grades: list[dict], cet_scores: list[dict] = None,
                     gpa_only: bool = True) -> float:
    """保研/推免模式绩点：用四六级折算分替换英语模块（8学分）

    规则:
    1. 从 grades 中移除所有英语课（通用英语 + 专用英语-*）
    2. 取最高可用 CET 分折算成百分制，按 8 学分插入
    3. 优先级: CET6 > CET4，都不可用则回退到原始英语课成绩

    参数:
        grades: 成绩列表
        cet_scores: 四六级成绩 [{type, score}, ...]，None 表示不替换
        gpa_only: 是否排除通识选修课
    """
    if not grades:
        return 0.0

    # 分离英语课和非英语课
    english_grades = []
    non_english = []
    for g in grades:
        if is_english_course(g.get("course_name", "")):
            english_grades.append(g)
        else:
            non_english.append(g)

    # 选择最佳 CET 分数
    cet4_score = 0.0
    cet6_score = 0.0
    if cet_scores:
        for cs in cet_scores:
            if cs.get("type") == "CET4":
                cet4_score = max(cet4_score, float(cs.get("score", 0) or 0))
            elif cs.get("type") == "CET6":
                cet6_score = max(cet6_score, float(cs.get("score", 0) or 0))

    # 优先 CET6，其次 CET4
    pct = 0.0
    if cet6_score >= 425:
        pct = cet_to_percentage(cet6_score, "CET6")
    elif cet4_score >= 425:
        pct = cet_to_percentage(cet4_score, "CET4")

    if pct > 0:
        # 有可用 CET 分数 → 用 CET 折算分替换英语模块
        gp = score_to_gp(pct)
        cet_entry = {
            "course_name": "CET折算(英语模块)",
            "score": str(pct),
            "credit": 8.0,
            "grade_point": gp,
            "course_nature": "CET替换",
        }
        calc_grades = non_english + [cet_entry]
    else:
        # 无可用 CET 分数 → 回退原始英语课成绩
        calc_grades = list(grades)

    return calc_gpa(calc_grades, gpa_only=gpa_only)
