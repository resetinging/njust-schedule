/* 南理工课表管理 - 教学评价页面逻辑 */

let allEvaluations = [];
let currentSemester = '';
let isLoggedIn = false;

document.addEventListener('DOMContentLoaded', () => {
    loadStatus();
    loadEvaluations();
});

// 日期解析（本地时间）
function parseDate(str) {
    if (!str) return null;
    const cleaned = str.replace(/[年月]/g, '-').replace(/[日号]/g, '').replace(/\//g, '-').trim();
    const m = cleaned.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
    if (m) return new Date(parseInt(m[1]), parseInt(m[2]) - 1, parseInt(m[3]));
    return null;
}

function formatDate(str) {
    const d = parseDate(str);
    if (!d) return str || '';
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}

// 计算距截止日期的可读时间
function timeUntilDeadline(endDateStr) {
    const end = parseDate(endDateStr);
    if (!end) return { text: '未知', cls: '' };
    end.setHours(23, 59, 59, 0); // 截止到当天结束
    const now = new Date();
    const diffMs = end - now;
    const totalHours = diffMs / (1000 * 60 * 60);
    const totalDays = Math.floor(totalHours / 24);

    if (totalHours < 0) {
        return { text: '已截止', cls: 'done' };
    }
    if (totalHours < 24) {
        return { text: `${Math.floor(totalHours)}小时后截止`, cls: 'urgent' };
    }
    if (totalDays <= 3) {
        return { text: `还有 ${totalDays} 天截止`, cls: 'urgent' };
    }
    if (totalDays <= 7) {
        return { text: `还有 ${totalDays} 天`, cls: 'warning' };
    }
    return { text: `还有 ${totalDays} 天`, cls: '' };
}

async function loadStatus() {
    try {
        const resp = await fetch('/api/status');
        const data = await resp.json();
        currentSemester = data.semester;
        isLoggedIn = data.logged_in;
        document.getElementById('semester-badge').textContent = data.semester;
        updateNavStatus(data);
    } catch (e) {
        console.error('获取状态失败:', e);
    }
}

async function loadEvaluations() {
    showLoading('正在加载评价数据...');
    try {
        const resp = await fetch('/api/evaluations');
        const data = await resp.json();
        allEvaluations = data.evaluations || [];
        currentSemester = data.semester;
        document.getElementById('semester-badge').textContent = data.semester;

        if (allEvaluations.length === 0) {
            document.getElementById('eval-empty').style.display = 'flex';
            document.getElementById('eval-list').style.display = 'none';
            document.getElementById('countdown-row').style.display = 'none';
            if (isLoggedIn) {
                document.getElementById('empty-eval-message').textContent =
                    '暂无评价数据，请点击「刷新评价数据」获取最新信息';
            } else {
                document.getElementById('empty-eval-message').textContent =
                    '请先在「设置」页面登录教务系统，然后刷新评价数据';
            }
        } else {
            document.getElementById('eval-empty').style.display = 'none';
            document.getElementById('eval-list').style.display = 'block';
            renderEvaluations(allEvaluations);
            renderCountdown(allEvaluations);
        }
    } catch (e) {
        console.error('加载评价失败:', e);
        document.getElementById('eval-empty').style.display = 'flex';
    } finally {
        hideLoading();
    }
}

function renderCountdown(evals) {
    const row = document.getElementById('countdown-row');
    row.innerHTML = '';

    // 找出未完成且有截止日期的评价，按截止日期排序
    const undone = evals
        .filter(e => !e.is_done && e.end_date)
        .sort((a, b) => (a.end_date || '').localeCompare(b.end_date || ''));

    if (undone.length === 0) {
        // 全部完成，显示一条提示
        row.style.display = 'flex';
        const card = document.createElement('div');
        card.className = 'countdown-card';
        card.innerHTML = `
            <div class="countdown-days" style="font-size:1.5rem;">✅</div>
            <div class="countdown-label">全部已完成</div>
            <div class="countdown-course">本学期评价已全部完成</div>
        `;
        row.appendChild(card);
        return;
    }
    row.style.display = 'flex';

    for (const evalItem of undone.slice(0, 3)) {
        const info = timeUntilDeadline(evalItem.end_date);
        const endDate = parseDate(evalItem.end_date);
        const now = new Date();
        const totalHours = endDate ? (endDate - now) / (1000 * 60 * 60) : 0;

        let cardClass = 'countdown-card';
        if (info.cls === 'urgent') cardClass += ' urgent';
        else if (info.cls === 'warning') cardClass += ' warning';

        let bigNum;
        if (totalHours < 0) bigNum = '!';
        else if (totalHours < 24) bigNum = Math.floor(totalHours) + 'h';
        else bigNum = Math.floor(totalHours / 24);

        const card = document.createElement('div');
        card.className = cardClass;
        card.innerHTML = `
            <div class="countdown-days">${bigNum}</div>
            <div class="countdown-label">${info.text}</div>
            <div class="countdown-course">${evalItem.batch}</div>
            <div class="countdown-date">截止: ${formatDate(evalItem.end_date)}</div>
        `;
        row.appendChild(card);
    }
}

function renderEvaluations(evals) {
    const container = document.getElementById('eval-list');
    container.innerHTML = '';

    // 按截止日期排序（未完成的在前）
    const sorted = [...evals].sort((a, b) => {
        if (a.is_done !== b.is_done) return a.is_done ? 1 : -1;
        return (a.end_date || '').localeCompare(b.end_date || '');
    });

    for (const evalItem of sorted) {
        const info = timeUntilDeadline(evalItem.end_date);
        const card = document.createElement('div');
        card.className = 'exam-card';
        if (evalItem.is_done) card.style.opacity = '0.6';

        // 状态徽章
        let statusBadge = '';
        if (evalItem.is_done) {
            statusBadge = '<span class="badge badge-done">已完成</span>';
        } else if (info.cls === 'urgent') {
            statusBadge = `<span class="badge badge-urgent">${info.text}</span>`;
        } else if (info.cls === 'warning') {
            statusBadge = `<span class="badge badge-warning">${info.text}</span>`;
        } else {
            statusBadge = `<span class="badge">${info.text}</span>`;
        }

        // 评价子项（可点击打开评教页面）
        let itemsHtml = '';
        if (evalItem.items && evalItem.items.length > 0) {
            itemsHtml = '<div class="exam-info-row eval-items-row">';
            for (const item of evalItem.items) {
                const proxyUrl = `/proxy/jw/xspj/${item.url.split('/njlgdx/').pop() || item.url}`;
                itemsHtml += `
                    <span class="eval-item-link" onclick="openEvalModal('${escapeHtml(item.name)}', '${escapeHtml(proxyUrl)}')">
                        📋 ${item.name}
                    </span>`;
            }
            itemsHtml += '</div>';
        }

        card.innerHTML = `
            <div class="exam-course-name">
                ${evalItem.is_done ? '✅ ' : '📝 '}${evalItem.category} — ${evalItem.batch}
                ${statusBadge}
            </div>
            <div class="exam-info-row">
                <span>📅 ${formatDate(evalItem.start_date)} ~ ${formatDate(evalItem.end_date)}</span>
            </div>
            ${itemsHtml}
        `;
        container.appendChild(card);
    }
}

async function refreshEvaluations() {
    showLoading('正在从教务系统获取评价数据...');
    document.getElementById('loading-text').textContent = '正在连接教务系统...';

    try {
        const resp = await fetch('/api/refresh-evaluations', { method: 'POST' });
        const data = await resp.json();
        hideLoading();

        if (data.success) {
            showToast(`✅ ${data.message}`, 'success');
            await loadEvaluations();
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

// ============================================================
// 评教模态窗口
// ============================================================

function escapeHtml(str) {
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function openEvalModal(title, url) {
    document.getElementById('eval-modal-title').textContent = title;
    document.getElementById('eval-iframe').src = url;
    document.getElementById('eval-modal').style.display = 'flex';
    document.body.style.overflow = 'hidden';
}

function closeEvalModal() {
    document.getElementById('eval-modal').style.display = 'none';
    document.getElementById('eval-iframe').src = '';
    document.body.style.overflow = '';
}

// 点击遮罩关闭
document.addEventListener('click', function(e) {
    if (e.target.id === 'eval-modal') closeEvalModal();
});

// ESC 关闭
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeEvalModal();
});
