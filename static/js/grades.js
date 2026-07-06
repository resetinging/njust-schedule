let allGrades = [];
let currentSemester = '';
let availableSemesters = [];

document.addEventListener('DOMContentLoaded', () => {
    loadStatus();
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
    // 文字成绩：优/良 = high, 不及格 = fail
    if (/^(优|良|A|B)/.test(score)) return 'score-high';
    if (/^(不及格|差|F)/.test(score)) return 'score-fail';
    return 'score-pass';
}

function getUrlParam(name) {
    const params = new URLSearchParams(window.location.search);
    return params.get(name) || '';
}

async function loadGrades() {
    showLoading('正在加载成绩...');
    try {
        const urlSemester = getUrlParam('semester');
        const apiUrl = urlSemester ? `/api/grades?semester=${encodeURIComponent(urlSemester)}` : '/api/grades';
        const resp = await fetch(apiUrl);
        const data = await resp.json();
        allGrades = data.grades || [];
        currentSemester = data.semester || '';
        availableSemesters = data.available_semesters || [];
        window.currentSemester = currentSemester;
        document.getElementById('semester-badge').textContent = currentSemester;

        // 学期选择器
        const sel = document.getElementById('semester-select');
        if (availableSemesters.length > 1) {
            sel.style.display = 'inline-block';
            sel.innerHTML = availableSemesters.map(s => {
                const selected = s === currentSemester ? ' selected' : '';
                return `<option value="${s}"${selected}>${s}</option>`;
            }).join('');
        } else {
            sel.style.display = 'none';
        }

        if (allGrades.length === 0) {
            document.getElementById('grade-empty').style.display = 'flex';
            document.getElementById('grade-summary').style.display = 'none';
            document.getElementById('grade-table-wrapper').style.display = 'none';
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
    } finally {
        hideLoading();
    }
}

function renderSummary(data) {
    document.getElementById('stat-gpa').textContent = data.gpa || '---';
    document.getElementById('stat-credits').textContent = data.total_credits || 0;
    document.getElementById('stat-count').textContent = data.count || 0;
}

function renderGrades(grades) {
    const tbody = document.getElementById('grade-body');
    tbody.innerHTML = '';

    for (const g of grades) {
        const tr = document.createElement('tr');
        const scoreCls = scoreClass(g.score);
        const credit = parseFloat(g.credit) || 0;
        const gp = parseFloat(g.grade_point) || 0;

        tr.innerHTML = `
            <td>
                <div class="grade-course-name">${escapeHtml(g.course_name)}</div>
                ${g.course_code ? `<div class="grade-course-code">${escapeHtml(g.course_code)}</div>` : ''}
            </td>
            <td><span class="${scoreCls}">${escapeHtml(String(g.score))}</span></td>
            <td>${credit || '-'}</td>
            <td>${gp > 0 ? gp.toFixed(1) : (gp === 0 ? '0' : '-')}</td>
            <td>${escapeHtml(g.course_type || '-')}</td>
            <td>${escapeHtml(g.exam_type || '正常考试')}</td>
        `;
        tbody.appendChild(tr);
    }
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
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
    if (semester && semester !== currentSemester) {
        window.location.href = `/grades?semester=${encodeURIComponent(semester)}`;
    }
}
