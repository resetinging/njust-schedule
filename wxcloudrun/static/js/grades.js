/**
 * 成绩查询页面 — 桌面端同款 UI
 * 方案 A: GPA/折算等计算全部在前端完成(与小程序 utils/gpa.js 同逻辑)
 */

let allGrades = [];          // 全部学期成绩(后端原始数据)
let displayGrades = [];      // 当前视图的成绩
let currentSemester = '';    // '' / '__all__' / 具体学期
let availableSemesters = [];
let currentGpaMode = '';     // '' = 标准, 'baoyan' = 保研推免
let cetData = null;          // CET 原始数据(前端折算)

// ============================================================
// GPA 计算工具(与小程序 utils/gpa.js 同逻辑)
// ============================================================
const NON_GRADE_STATUS = ['缓考', '缺考', '免修', '作弊', '违纪', '取消', '旷考', '休学'];
const NON_GPA_NATURES = ['通识教育选修课'];
const LEVEL_MAP = {
    '优': 4.0, '优秀': 4.0, '优+': 4.0, '优秀+': 4.0,
    '优-': 3.7, '优秀-': 3.7,
    '良+': 3.3, '良好+': 3.3, '良': 3.0, '良好': 3.0, '良-': 2.7, '良好-': 2.7,
    '中+': 2.3, '中等+': 2.3, '中': 2.0, '中等': 2.0, '中-': 1.5, '中等-': 1.5,
    '及格': 1.0, '通过': 1.0, '不及格': 0, '不通过': 0
};

function isNonGpaCourse(g) {
    return NON_GPA_NATURES.includes((g.course_nature || '').trim());
}

function scoreToGp(score) {
    const s = String(score == null ? '' : score).trim();
    if (s in LEVEL_MAP) return LEVEL_MAP[s];
    if (NON_GRADE_STATUS.includes(s)) return -1;
    const v = parseFloat(s);
    if (isNaN(v)) return -1;
    if (v >= 90) return 4.0;
    if (v >= 85) return 3.7;
    if (v >= 82) return 3.3;
    if (v >= 78) return 3.0;
    if (v >= 75) return 2.7;
    if (v >= 72) return 2.3;
    if (v >= 68) return 2.0;
    if (v >= 64) return 1.5;
    if (v >= 60) return 1.0;
    return 0;
}

function isEnglishCourse(name) {
    return name === '通用英语' || name.startsWith('专用英语-');
}

function cetToPercentage(cetScore, cetType) {
    const score = parseFloat(cetScore) || 0;
    if (score < 425) return 0;
    let base = (score - 425) / 285 * 40 + 60;
    if (cetType === 'CET6') base = Math.min(base + 5, 100);
    return Math.round(base * 10) / 10;
}

function calcGpa(grades, gpaOnly) {
    let totalWeighted = 0, totalCredits = 0;
    for (const g of grades || []) {
        if (gpaOnly && isNonGpaCourse(g)) continue;
        const credit = parseFloat(g.credit) || 0;
        if (credit <= 0) continue;
        let gp = parseFloat(g.grade_point) || 0;
        if (gp === 0) gp = scoreToGp(g.score);
        if (gp >= 0) { totalWeighted += credit * gp; totalCredits += credit; }
    }
    return totalCredits > 0 ? Math.round(totalWeighted / totalCredits * 100) / 100 : 0;
}

function calcSemesterGpas(grades) {
    const groups = {};
    for (const r of grades || []) {
        const key = (r.academic_year || '') + '-' + (r.semester || '');
        if (!groups[key]) groups[key] = [];
        groups[key].push(r);
    }
    const result = [];
    for (const sem of Object.keys(groups)) {
        const items = groups[sem];
        const counted = items.filter(g => !isNonGpaCourse(g));
        result.push({
            semester: sem,
            gpa: calcGpa(items, true),
            gpaAll: calcGpa(items, false),
            credits: Math.round(counted.reduce((s, g) => s + (parseFloat(g.credit) || 0), 0) * 10) / 10,
            count: counted.length
        });
    }
    result.sort((a, b) => String(b.semester).localeCompare(String(a.semester)));
    return result;
}

function calcGpaBaoyan(grades, cetScores, gpaOnly) {
    const list = grades || [];
    if (list.length === 0) return 0;
    const nonEnglish = list.filter(g => !isEnglishCourse(g.course_name));
    let cet4 = 0, cet6 = 0;
    for (const cs of (cetScores || [])) {
        const score = parseFloat(cs.score) || 0;
        if (cs.type === 'CET4') cet4 = Math.max(cet4, score);
        else if (cs.type === 'CET6') cet6 = Math.max(cet6, score);
    }
    let pct = 0;
    if (cet6 >= 425) pct = cetToPercentage(cet6, 'CET6');
    else if (cet4 >= 425) pct = cetToPercentage(cet4, 'CET4');

    let calcGrades = list;
    if (pct > 0) {
        calcGrades = nonEnglish.concat([{
            course_name: 'CET折算(英语模块)',
            score: String(pct),
            credit: 8,
            grade_point: scoreToGp(pct),
            course_nature: 'CET替换'
        }]);
    }
    return calcGpa(calcGrades, gpaOnly === undefined ? true : gpaOnly);
}

// ============================================================
// 展示辅助
// ============================================================

/** 成绩数值的颜色类名 */
function scoreClass(score) {
    const n = parseFloat(score);
    if (!isNaN(n)) {
        if (n >= 90) return 'score-high';
        if (n >= 60) return 'score-pass';
        return 'score-fail';
    }
    if (/^(优|良|A|B)/.test(score)) return 'score-high';
    if (/^(不及格|差|F)/.test(score)) return 'score-fail';
    return 'score-pass';
}

function getUrlParam(name) {
    const params = new URLSearchParams(window.location.search);
    return params.get(name) || '';
}

function creditsOf(grades) {
    return Math.round(grades
        .filter(g => !isNonGpaCourse(g))
        .reduce((s, g) => s + (parseFloat(g.credit) || 0), 0) * 10) / 10;
}

document.addEventListener('DOMContentLoaded', () => {
    loadStatus();
    loadCet();
    loadGrades();
});

// ============================================================
// CET 四六级
// ============================================================

async function loadCet(forceRefresh = false) {
    // 缓存优先：打开页面时若有缓存直接渲染
    if (!forceRefresh) {
        const cached = getLocalCache(CET_CACHE_KEY);
        if (cached && cached.d && cached.d.scores && cached.d.scores.length > 0) {
            cetData = cached.d;
            renderCetBar(cetData);
            return;
        }
    }
    try {
        const resp = await apiFetch('/api/cet-scores');
        const data = await resp.json();
        // 原始数据 → 前端折算
        const scores = (data.scores || []).map(s => ({
            ...s,
            percentage: cetToPercentage(s.score, s.type),
            usable: s.score >= 425
        }));
        let best = null;
        for (const s of scores) {
            if (s.usable && (!best || s.percentage > best.percentage)) best = s;
        }
        cetData = {
            scores: scores,
            has_usable: !!best,
            best_type: best ? best.type : '',
            best_percentage: best ? best.percentage : 0
        };
        if (scores.length > 0) {
            setLocalCache(CET_CACHE_KEY, cetData);
        }
        renderCetBar(cetData);
    } catch (e) {
        console.error('加载CET失败:', e);
    }
}

function renderCetBar(data) {
    const bar = document.getElementById('cet-bar');
    const itemsEl = document.getElementById('cet-items');
    const bestEl = document.getElementById('cet-best');

    if (!data.scores || data.scores.length === 0) {
        bar.style.display = 'none';
        return;
    }

    bar.style.display = '';
    let html = '';
    for (const s of data.scores) {
        const usableBadge = s.usable ? '✅' : '❌';
        html += `<span class="cet-item">${usableBadge} ${s.type}: <strong>${s.score}</strong>分 → ${s.percentage > 0 ? s.percentage.toFixed(1) : '---'}分</span>`;
    }
    itemsEl.innerHTML = html;

    if (data.has_usable) {
        bestEl.innerHTML = `保研折算：<strong>${data.best_type}</strong> → <strong>${data.best_percentage.toFixed(1)}</strong> 分（8学分）`;
        bestEl.style.display = '';
        document.getElementById('btn-mode-baoyan').style.display = '';
    } else {
        bestEl.textContent = '无可用四六级成绩（均 < 425），保研模式将使用校内英语课成绩';
        bestEl.style.display = '';
        document.getElementById('btn-mode-baoyan').style.display = 'none';
    }
}

async function refreshCet() {
    showLoading('正在获取四六级成绩...');
    try {
        const resp = await apiFetch('/api/refresh-cet', { method: 'POST' });
        const data = await resp.json();
        hideLoading();
        if (data.success) {
            showToast(`✅ ${data.message}`, 'success');
            await loadCet(true);
            if (currentGpaMode === 'baoyan') {
                await loadGrades(true);
            }
        } else {
            showToast(`❌ ${data.message}`, 'error');
        }
    } catch (e) {
        hideLoading();
        showToast('❌ 刷新失败: ' + e.message, 'error');
    }
}

// ============================================================
// GPA 模式切换
// ============================================================

function switchGpaMode(mode) {
    currentGpaMode = mode;
    document.querySelectorAll('.gpa-mode-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });
    loadGrades();
}

// ============================================================
// 成绩加载(原始数据 + 前端计算)
// ============================================================

const GRADES_CACHE_KEY = 'grades_cache';
const CET_CACHE_KEY = 'cet_cache';

async function loadGrades(forceRefresh = false) {
    // 缓存优先：打开页面时若有缓存直接渲染，后端请求仅发生在主动刷新时
    if (!forceRefresh) {
        const cached = getLocalCache(GRADES_CACHE_KEY);
        if (cached && cached.d && cached.d.grades && cached.d.grades.length > 0) {
            applyGradesData({ grades: cached.d.grades, available_semesters: cached.d.available_semesters || [] });
            showCacheToast(GRADES_CACHE_KEY);
            return;
        }
    }

    showLoading('正在加载成绩...');
    try {
        const urlSemester = getUrlParam('semester');
        // 方案 A: 后端只返回原始数据, 始终取全部并前端过滤
        const resp = await apiFetch('/api/grades');
        const data = await resp.json();
        if (data.grades && data.grades.length > 0) {
            setLocalCache(GRADES_CACHE_KEY, {
                grades: data.grades,
                available_semesters: data.available_semesters || [],
            });
        }
        applyGradesData(data);
    } catch (e) {
        console.error('加载成绩失败:', e);
        document.getElementById('empty-grade-message').textContent = '加载失败: ' + e.message;
        document.getElementById('grade-empty').style.display = 'flex';
        document.getElementById('grade-summary').style.display = 'none';
        document.getElementById('grade-table-wrapper').style.display = 'none';
        document.getElementById('semester-gpa-section').style.display = 'none';
    } finally {
        hideLoading();
    }
}

function applyGradesData(data) {
    const urlSemester = getUrlParam('semester');
    allGrades = data.grades || [];
    availableSemesters = data.available_semesters || [];

    const viewSem = (urlSemester && urlSemester !== '__all__') ? urlSemester : '';
    currentSemester = viewSem || '__all__';
    displayGrades = viewSem
        ? allGrades.filter(g => (g.academic_year || '') + '-' + (g.semester || '') === viewSem)
        : allGrades;

    window.currentSemester = currentSemester;
    const badge = document.getElementById('semester-badge');
    badge.textContent = currentSemester === '__all__' ? '全部学期' : currentSemester;

    // 学期选择器
    const sel = document.getElementById('semester-select');
    if (availableSemesters.length >= 1) {
        sel.style.display = 'inline-block';
        let options = `<option value="__all__"${currentSemester === '__all__' ? ' selected' : ''}>📋 全部学期</option>`;
        for (const s of availableSemesters) {
            options += `<option value="${s}"${s === currentSemester ? ' selected' : ''}>${s}</option>`;
        }
        sel.innerHTML = options;
    } else {
        sel.style.display = 'none';
    }

    // 保研推免模式仅在看全部学期时可用
    if (currentSemester === '__all__') {
        if (cetData && cetData.scores && cetData.scores.length > 0) {
            document.getElementById('gpa-mode-bar').style.display = '';
        }
    } else {
        document.getElementById('gpa-mode-bar').style.display = 'none';
        if (currentGpaMode === 'baoyan') {
            currentGpaMode = '';
            document.querySelectorAll('.gpa-mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === ''));
        }
    }

    if (allGrades.length === 0) {
        document.getElementById('grade-empty').style.display = 'flex';
        document.getElementById('grade-summary').style.display = 'none';
        document.getElementById('grade-table-wrapper').style.display = 'none';
        document.getElementById('semester-gpa-section').style.display = 'none';
        if (window.isLoggedIn) {
            document.getElementById('empty-grade-message').textContent =
                '暂无成绩数据，请点击「刷新成绩」从教务系统获取';
        } else {
            document.getElementById('empty-grade-message').textContent =
                '请先在「设置」页面登录教务系统，然后刷新成绩';
            document.getElementById('grade-empty').querySelector('.btn-primary').style.display = 'inline-flex';
        }
    } else {
        document.getElementById('grade-empty').style.display = 'none';
        document.getElementById('grade-summary').style.display = 'flex';
        document.getElementById('grade-table-wrapper').style.display = 'block';
        renderSummary();
        renderGrades(displayGrades);
    }
}

function renderSummary() {
    const viewAll = (currentSemester === '__all__');
    const isBaoyan = (currentGpaMode === 'baoyan');
    const viewGrades = displayGrades;

    const gpa = isBaoyan
        ? calcGpaBaoyan(viewGrades, cetData ? cetData.scores : null, true)
        : calcGpa(viewGrades, true);
    const gpaAll = calcGpa(viewGrades, false);
    const credits = creditsOf(viewGrades);
    const count = viewGrades.filter(g => !isNonGpaCourse(g)).length;
    const countTotal = viewGrades.length;

    document.getElementById('stat-gpa').textContent = gpa > 0 ? gpa.toFixed(2) : '---';
    document.getElementById('stat-credits').textContent = credits || 0;
    document.getElementById('stat-count').textContent = count || 0;

    const gpaEl = document.getElementById('stat-gpa');
    gpaEl.classList.remove('gpa-high', 'gpa-mid', 'gpa-low');
    if (gpa >= 3.0) gpaEl.classList.add('gpa-high');
    else if (gpa >= 2.0) gpaEl.classList.add('gpa-mid');
    else if (gpa > 0) gpaEl.classList.add('gpa-low');

    // GPA 模式标签
    const labelEl = document.querySelector('#grade-summary .stat-card:first-child .stat-label');
    if (labelEl) {
        const firstLine = isBaoyan
            ? '加权平均绩点（保研·CET折算）'
            : '加权平均绩点（计内）';
        labelEl.innerHTML = firstLine + '<span class="gpa-note" id="gpa-note" style="display:none;"></span>';
    }

    // 排除提示
    const excludedCount = countTotal - count;
    const noteEl = document.getElementById('gpa-note');
    if (noteEl && excludedCount > 0) {
        const parts = [`已排除 ${excludedCount} 门通识选修课`];
        if (!isBaoyan && gpaAll > 0 && gpaAll !== gpa) {
            parts.push(`含全部课程绩点: ${gpaAll.toFixed(2)}`);
        }
        if (isBaoyan && cetData && cetData.best_type) {
            parts.push(`英语→CET折算 ${cetData.best_percentage.toFixed(1)}分`);
        }
        noteEl.textContent = `（${parts.join('，')}）`;
        noteEl.style.display = '';
    } else if (noteEl && isBaoyan && cetData && cetData.best_type) {
        noteEl.textContent = `（英语→CET折算 ${cetData.best_percentage.toFixed(1)}分）`;
        noteEl.style.display = '';
    } else if (noteEl) {
        noteEl.style.display = 'none';
    }

    renderSemesterGpas(calcSemesterGpas(allGrades), currentSemester);
}

function renderSemesterGpas(semesterGpas, currentSem) {
    const section = document.getElementById('semester-gpa-section');
    const grid = document.getElementById('semester-gpa-grid');

    if (!semesterGpas || semesterGpas.length === 0) {
        section.style.display = 'none';
        return;
    }

    section.style.display = 'block';
    grid.innerHTML = '';

    for (const s of semesterGpas) {
        const isActive = (currentSem === '__all__' || s.semester === currentSem);
        let gpaClass = '';
        if (s.gpa >= 3.0) gpaClass = 'gpa-high';
        else if (s.gpa >= 2.0) gpaClass = 'gpa-mid';
        else if (s.gpa > 0) gpaClass = 'gpa-low';

        const card = document.createElement('div');
        card.className = 'semester-gpa-card' + (isActive ? ' active' : '');
        card.onclick = () => {
            if (s.semester !== currentSem) {
                window.location.href = `/grades?semester=${encodeURIComponent(s.semester)}`;
            }
        };
        card.innerHTML = `
            <div class="sgpa-semester">${escapeHtml(s.semester)}</div>
            <div class="sgpa-value ${gpaClass}">${s.gpa > 0 ? s.gpa.toFixed(2) : '---'}</div>
            <div class="sgpa-detail">
                <span>${s.credits} 学分</span>
                <span>·</span>
                <span>${s.count} 门课</span>
            </div>
        `;
        grid.appendChild(card);
    }
}

function renderGrades(grades) {
    const tbody = document.getElementById('grade-body');
    tbody.innerHTML = '';
    const isBaoyan = (currentGpaMode === 'baoyan');

    for (const g of grades) {
        const tr = document.createElement('tr');
        const scoreCls = scoreClass(g.score);
        const credit = parseFloat(g.credit) || 0;
        const gp = parseFloat(g.grade_point) || 0;
        const excluded = isNonGpaCourse(g);
        const engReplaced = isBaoyan && isEnglishCourse(g.course_name);

        let tagHtml = '';
        if (excluded) {
            tagHtml = ' <span class="gpa-excluded-tag" title="通识教育选修课不计入绩点">不计入</span>';
        } else if (engReplaced) {
            tagHtml = ' <span class="gpa-excluded-tag cet-replaced" title="保研模式：英语课已被CET折算分替换">已替换</span>';
        }

        tr.innerHTML = `
            <td>
                <div class="grade-course-name">${escapeHtml(g.course_name)}${tagHtml}</div>
                ${g.course_code ? `<div class="grade-course-code">${escapeHtml(g.course_code)}</div>` : ''}
            </td>
            <td><span class="${scoreCls}">${escapeHtml(String(g.score))}</span></td>
            <td>${credit || '-'}</td>
            <td>${gp > 0 ? gp.toFixed(1) : (gp === 0 ? '0' : '-')}</td>
            <td>${escapeHtml(g.course_type || '-')}</td>
            <td>${escapeHtml(g.course_nature || '-')}</td>
            <td>${escapeHtml(g.exam_type || '正常考试')}</td>
        `;
        if (excluded || engReplaced) tr.classList.add('row-excluded');
        tbody.appendChild(tr);
    }
}

async function refreshGrades() {
    showLoading('正在从教务系统获取成绩...');
    document.getElementById('loading-text').textContent =
        '正在连接教务系统，可能需要十几秒钟...';

    try {
        const resp = await apiFetch('/api/refresh-grades', { method: 'POST' });
        const data = await resp.json();
        hideLoading();

        if (data.success) {
            showToast(`✅ ${data.message}`, 'success');
            await loadGrades(true);   // 刷新后强制重新查询并更新缓存
        } else {
            showToast(`❌ ${data.message}`, 'error');
            if (data.message.includes('登录')) {
                window.location.href = '/settings';
            }
        }
    } catch (e) {
        hideLoading();
        showToast('❌ 刷新失败: ' + e.message, 'error');
    }
}

function onSemesterChange() {
    const sel = document.getElementById('semester-select');
    const semester = sel.value;
    if (semester === '__all__') {
        window.location.href = '/grades?semester=__all__';
    } else if (semester && semester !== currentSemester) {
        window.location.href = `/grades?semester=${encodeURIComponent(semester)}`;
    }
}
