let allGrades = [];
let currentSemester = '';
let availableSemesters = [];
let currentGpaMode = '';  // '' = standard, 'baoyan' = 保研推免
let cetData = null;       // CET scores from /api/cet-scores

document.addEventListener('DOMContentLoaded', () => {
    loadStatus();
    loadCet();
    loadGrades();
});

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

/** 判断是否不计入绩点（通识教育选修课） */
function isNonGpaCourse(g) {
    return g.course_nature === '通识教育选修课';
}

/** 判断是否为英语课（保研模式中被 CET 替换） */
function isEnglishCourse(name) {
    return name === '通用英语' || name.startsWith('专用英语-');
}

// ============================================================
// CET 四六级
// ============================================================

async function loadCet() {
    try {
        const resp = await fetch('/api/cet-scores');
        const data = await resp.json();
        cetData = data;
        renderCetBar(data);
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
        const resp = await fetch('/api/refresh-cet', { method: 'POST' });
        const data = await resp.json();
        hideLoading();
        if (data.success) {
            showToast(`✅ ${data.message}`, 'success');
            await loadCet();
            // 如果当前是保研模式，重新加载成绩
            if (currentGpaMode === 'baoyan') {
                await loadGrades();
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
    // 更新按钮状态
    document.querySelectorAll('.gpa-mode-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });
    loadGrades();
}

// ============================================================
// 成绩加载
// ============================================================

async function loadGrades() {
    showLoading('正在加载成绩...');
    try {
        const urlSemester = getUrlParam('semester');
        let apiUrl = urlSemester ? `/api/grades?semester=${encodeURIComponent(urlSemester)}` : '/api/grades';
        if (currentGpaMode === 'baoyan') {
            apiUrl += (urlSemester ? '&' : '?') + 'gpa_mode=baoyan';
        }
        const resp = await fetch(apiUrl);
        const data = await resp.json();
        allGrades = data.grades || [];
        currentSemester = data.semester || '';
        availableSemesters = data.available_semesters || [];
        window.currentSemester = currentSemester;
        document.getElementById('semester-badge').textContent = currentSemester;

        // 学期选择器
        const sel = document.getElementById('semester-select');
        const viewAll = (currentSemester === '__all__');
        if (availableSemesters.length >= 1) {
            sel.style.display = 'inline-block';
            let options = '';
            const allSelected = viewAll ? ' selected' : '';
            options += `<option value="__all__"${allSelected}>📋 全部学期</option>`;
            for (const s of availableSemesters) {
                const selected = (s === currentSemester && !viewAll) ? ' selected' : '';
                options += `<option value="${s}"${selected}>${s}</option>`;
            }
            sel.innerHTML = options;
        } else {
            sel.style.display = 'none';
        }

        if (viewAll) {
            document.getElementById('semester-badge').textContent = '全部学期';
            // 保研推免模式仅在看全部学期时可用
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
            renderSummary(data);
            renderGrades(allGrades);
        }
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

function renderSummary(data) {
    const viewAll = (data.semester === '__all__');
    const isBaoyan = (currentGpaMode === 'baoyan');

    let gpa, gpaAll, credits, count, countTotal;
    if (viewAll) {
        gpa = isBaoyan ? (data.all_gpa_baoyan || 0) : (data.all_gpa || 0);
        gpaAll = data.all_gpa_all || 0;
        credits = data.all_credits || 0;
        count = data.all_count || 0;
        countTotal = data.all_count_total || 0;
    } else {
        gpa = isBaoyan ? (data.gpa_baoyan || 0) : (data.gpa || 0);
        gpaAll = data.gpa_all || 0;
        credits = data.total_credits || 0;
        count = data.count || 0;
        countTotal = allGrades.length;
    }

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
        labelEl.innerHTML = isBaoyan
            ? '加权平均绩点（保研·CET折算）<span class="gpa-note" id="gpa-note" style="display:none;"></span>'
            : '加权平均绩点（计内）<span class="gpa-note" id="gpa-note" style="display:none;"></span>';
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

    renderSemesterGpas(data.semester_gpas || [], data.semester);
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
        const resp = await fetch('/api/refresh-grades', { method: 'POST' });
        const data = await resp.json();
        hideLoading();

        if (data.success) {
            showToast(`✅ ${data.message}`, 'success');
            await loadGrades();
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
