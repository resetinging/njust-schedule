/* 南理工课表管理 - 教学评价页面逻辑 */

let allEvaluations = [];

document.addEventListener('DOMContentLoaded', () => {
    loadStatus();
    loadEvaluations();
});

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

async function loadEvaluations() {
    showLoading('正在加载评价数据...');
    try {
        const resp = await fetch('/api/evaluations');
        const data = await resp.json();
        allEvaluations = data.evaluations || [];
        window.currentSemester = data.semester;
        document.getElementById('semester-badge').textContent = data.semester;

        if (allEvaluations.length === 0) {
            document.getElementById('eval-empty').style.display = 'flex';
            document.getElementById('eval-list').style.display = 'none';
            document.getElementById('countdown-row').style.display = 'none';
            if (window.isLoggedIn) {
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
                itemsHtml += `
                    <span class="eval-item-link" onclick="openEvalModal('${escapeHtml(item.name)}', '${escapeHtml(item.url)}')">
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
// 评教模态窗口 — 两级导航：课程列表 → 评价表单
// ============================================================

function escapeHtml(str) {
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

let currentEvalForm = null;   // 当前评价表单数据 (indicators + hidden_fields)
let currentBatchData = null;  // 当前批次课程列表数据 (courses + hidden_fields)
let currentBatchUrl = '';     // 当前批次的教务 URL，用于提交后重新拉取
let currentView = 'courses';  // 'courses' | 'form'
let batchPollTimer = null;   // 批量评教轮询定时器

// 第一步：点击批次 → 加载课程列表
async function openEvalModal(title, itemUrl) {
    const modal = document.getElementById('eval-modal');
    const titleEl = document.getElementById('eval-modal-title');
    const body = document.getElementById('eval-modal-content');

    currentBatchUrl = itemUrl.replace('/proxy/jw/', '/');
    titleEl.textContent = '加载中...';
    body.innerHTML = '<div class="eval-modal-message"><div class="loading-spinner"></div><p>正在加载课程列表...</p></div>';
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
    currentView = 'courses';

    try {
        const resp = await fetch('/api/eval-courses?url=' + encodeURIComponent(currentBatchUrl));
        const data = await resp.json();
        if (!data.success) {
            body.innerHTML = `<div class="eval-modal-message error"><p>❌ ${data.message}</p></div>`;
            return;
        }
        currentBatchData = data;
        titleEl.textContent = '📋 ' + (data.batch_title || title);
        renderCourseList(body, data);
    } catch (e) {
        body.innerHTML = `<div class="eval-modal-message"><p>加载失败: ${e.message}</p></div>`;
    }
}

// 渲染课程列表
function renderCourseList(container, data) {
    const courses = data.courses || [];
    const unsubmittedCount = courses.filter(c => !c.submitted).length;

    let html = '';

    // 返回评价列表按钮
    html += `
        <div class="eval-form-toolbar">
            <button type="button" class="btn btn-secondary btn-sm" onclick="closeEvalModal()">
                ← 返回评价列表
            </button>
            <span class="eval-toolbar-sep">|</span>
            <span class="eval-toolbar-title">📋 ${escapeHtml(data.batch_title || '评教课程')}</span>
        </div>`;

    // 一键评教工具栏（有未评价课程时显示）
    if (unsubmittedCount > 0) {
        html += `
        <div class="batch-eval-toolbar" id="batch-eval-toolbar">
            <span class="batch-eval-info">📋 ${unsubmittedCount} 门待评价</span>
            <div class="batch-eval-buttons">
                <label class="batch-target-label">目标分:</label>
                <input type="number" id="batch-target-score" class="batch-target-input"
                       value="95" min="1" max="100" step="1"
                       onkeydown="if(event.key==='Enter')startBatchEval()">
                <button class="btn btn-success btn-sm" onclick="startBatchEval()">
                    🚀 一键评教
                </button>
            </div>
        </div>`;
    }

    html += '<div class="eval-course-list">';

    for (let i = 0; i < courses.length; i++) {
        const c = courses[i];
        const statusIcon = c.submitted ? '✅' : (c.evaluated ? '💾' : '📝');
        const statusText = c.submitted ? '已提交' : (c.evaluated ? '已保存' : '待评价');
        const btnDisabled = c.submitted ? '' : '';
        const btnOnclick = c.submitted
            ? `viewEvalScores('${escapeHtml(c.eval_url)}', '${escapeHtml(c.name)}', '${escapeHtml(c.teacher)}')`
            : `openEvalForm('${escapeHtml(c.eval_url)}', '${escapeHtml(c.name)}', '${escapeHtml(c.teacher)}')`;
        const btnText = c.submitted ? '📊 查看评分' : (c.evaluated ? '📝 继续评价' : '📝 开始评价');
        const btnClass = c.submitted ? 'btn btn-secondary btn-sm' : 'btn btn-primary btn-sm';
        const btnDisabledAttr = c.submitted ? '' : '';  // 所有按钮均可点击

        html += `
        <div class="eval-course-card" id="eval-course-${i}" data-submitted="${c.submitted ? '1' : '0'}">
            <div class="eval-course-card-header">
                <span class="eval-course-card-name">${statusIcon} ${escapeHtml(c.name)}</span>
                <span class="eval-course-card-status">${statusText}</span>
            </div>
            <div class="eval-course-card-info">
                <span>📖 ${escapeHtml(c.code)}</span>
                <span>👨‍🏫 ${escapeHtml(c.teacher)}</span>
                ${c.score !== '0' ? `<span>⭐ ${escapeHtml(c.score)}分</span>` : ''}
            </div>
            <div class="eval-course-card-action">
                <button class="${btnClass}"
                        onclick="${btnOnclick}"
                        ${btnDisabledAttr}>
                    ${btnText}
                </button>
            </div>
        </div>`;
    }
    html += '</div>';
    container.innerHTML = html;
}

// 第二步：点击课程 → 加载评价表单
async function openEvalForm(evalUrl, courseName, teacherName, readonly = false) {
    if (!evalUrl) {
        showToast('❌ 该课程评价链接无效', 'error');
        return;
    }

    const titleEl = document.getElementById('eval-modal-title');
    const body = document.getElementById('eval-modal-content');

    titleEl.textContent = '加载中...';
    body.innerHTML = '<div class="eval-modal-message"><div class="loading-spinner"></div><p>正在加载评价表单...</p></div>';
    currentView = 'form';

    try {
        const resp = await fetch('/api/eval-form?url=' + encodeURIComponent(evalUrl));
        const data = await resp.json();
        if (!data.success) {
            body.innerHTML = `<div class="eval-modal-message">
                <p>❌ ${data.message}</p>
                <button class="btn btn-secondary" onclick="backToCourseList()" class="mt-16">← 返回课程列表</button>
            </div>`;
            return;
        }
        currentEvalForm = data;
        const prefix = readonly ? '📊' : '📝';
        titleEl.textContent = prefix + ' ' + (data.course_name || courseName);
        if (teacherName) {
            titleEl.textContent += ' — ' + teacherName;
        }
        renderEvalForm(body, data, readonly);
    } catch (e) {
        body.innerHTML = `<div class="eval-modal-message">
            <p>加载失败: ${e.message}</p>
            <button class="btn btn-secondary" onclick="backToCourseList()" class="mt-16">← 返回课程列表</button>
        </div>`;
    }
}

// 查看已提交课程的评分（只读模式）
async function viewEvalScores(evalUrl, courseName, teacherName) {
    await openEvalForm(evalUrl, courseName, teacherName, true);
}

// 返回课程列表（使用已有数据，不重新请求）
function backToCourseList() {
    if (!currentBatchData) {
        closeEvalModal();
        return;
    }
    hideBatchProgress();
    const titleEl = document.getElementById('eval-modal-title');
    const body = document.getElementById('eval-modal-content');
    titleEl.textContent = '📋 ' + (currentBatchData.batch_title || '评教课程');
    renderCourseList(body, currentBatchData);
    currentEvalForm = null;
    currentView = 'courses';
}

// 重新拉取课程列表（提交/保存后刷新状态）
async function refreshCourseList() {
    if (!currentBatchUrl) {
        closeEvalModal();
        return;
    }
    // 从批量评教进度切回课程列表视图
    hideBatchProgress();
    const titleEl = document.getElementById('eval-modal-title');
    const body = document.getElementById('eval-modal-content');
    // 锁定当前高度防止刷新时跳变
    body.style.minHeight = body.scrollHeight + 'px';
    currentEvalForm = null;
    currentView = 'courses';

    try {
        const resp = await fetch('/api/eval-courses?url=' + encodeURIComponent(currentBatchUrl));
        const data = await resp.json();
        if (data.success) {
            currentBatchData = data;
            titleEl.textContent = '📋 ' + (data.batch_title || '评教课程');
            renderCourseList(body, data);
            scrollToNextUnsubmitted(body);
        } else {
            titleEl.textContent = '📋 ' + (currentBatchData ? currentBatchData.batch_title || '评教课程' : '评教课程');
            renderCourseList(body, currentBatchData);
        }
    } catch (e) {
        console.error('刷新课程列表失败:', e);
        if (currentBatchData) {
            renderCourseList(body, currentBatchData);
        }
    }
    body.style.minHeight = '';
}

// 滚动到第一个未提交（待评价）的课程卡片
function scrollToNextUnsubmitted(container) {
    // 等 DOM 渲染完成再滚动
    setTimeout(() => {
        const nextCard = container.querySelector('.eval-course-card[data-submitted="0"]');
        if (nextCard) {
            nextCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }, 100);
}

function renderEvalForm(container, data, readonly = false) {
    const indicators = data.indicators || [];
    const hf = data.hidden_fields || {};

    let html = `<form id="eval-native-form" class="eval-native-form">`;

    // 隐藏字段
    for (const [k, v] of Object.entries(hf)) {
        html += `<input type="hidden" name="${escapeHtml(k)}" value="${escapeHtml(v)}">`;
    }

    // 返回按钮
    html += `<div class="eval-form-toolbar">
        <button type="button" class="btn btn-secondary btn-sm" onclick="backToCourseList()">← 返回课程列表</button>
    </div>`;

    // 计算已选总分（若有默认选中项则提前算出）
    const maxScore = calcMaxScore(indicators);
    const currentScore = calcCurrentScoreStatic(indicators);

    if (readonly) {
        // ★ 只读查看模式：显示评分摘要
        html += `<div class="eval-score-summary">
            <span class="eval-summary-icon">📊</span>
            <span class="eval-summary-text">总分: <strong>${currentScore > 0 ? currentScore : '—'}</strong> / ${maxScore}</span>
            <span class="eval-summary-hint">（已提交，仅查看）</span>
        </div>`;
    } else {
        // 自动填写工具栏
        html += `<div class="eval-autofill-bar">
            <span class="eval-autofill-label">🎯 期望分数:</span>
            <input type="number" id="eval-target-score" class="eval-target-input"
                   min="0" max="100" step="1" placeholder="如 85"
                   onkeydown="if(event.key==='Enter')autoFillEval()">
            <span class="eval-autofill-hint">（满分 ${maxScore}）</span>
            <button type="button" class="btn btn-primary btn-sm" onclick="autoFillEval()">
                ✨ 自动填写
            </button>
            <span class="eval-fill-divider">|</span>
            <span class="eval-live-score">📊 当前总分: <strong id="eval-live-total">—</strong></span>
        </div>`;
    }

    // 课程标题
    if (data.course_name) {
        html += `<div class="eval-course-title">📖 ${escapeHtml(data.course_name)}</div>`;
    }

    // 评价指标
    html += '<div class="eval-indicators">';
    for (const ind of indicators) {
        html += `<div class="eval-indicator-card">
            <div class="eval-indicator-label">${escapeHtml(ind.label)}</div>
            <div class="eval-options">`;
        for (const opt of (ind.options || [])) {
            const scoreBadge = opt.score ? `<span class="eval-score-badge">${escapeHtml(opt.score)}分</span>` : '';
            const checked = opt.checked ? ' checked' : '';
            const disabled = readonly ? ' disabled' : '';
            // 只读模式下已选中项高亮
            const extraClass = (readonly && opt.checked) ? ' eval-option-checked' : '';
            html += `
                <label class="eval-option${extraClass}">
                    <input type="radio" name="${escapeHtml(opt.name)}" value="${escapeHtml(opt.value)}"
                           onchange="updateLiveScore()"${checked}${disabled}>
                    <span class="eval-option-label">${escapeHtml(opt.label)}${scoreBadge}</span>
                </label>`;
        }
        html += '</div></div>';
    }
    html += '</div>';

    // 操作按钮
    if (readonly) {
        html += `
            <div class="eval-form-actions">
                <button type="button" class="btn btn-secondary" onclick="backToCourseList()">
                    ← 返回课程列表
                </button>
            </div>`;
    } else {
        html += `
            <div class="eval-form-actions">
                <button type="button" class="btn btn-secondary" onclick="submitEval('0')">
                    💾 保存
                </button>
                <button type="button" class="btn btn-primary" onclick="submitEval('1')">
                    ✅ 提交（不可修改）
                </button>
            </div>`;
    }
    html += '</form>';
    container.innerHTML = html;

    // 非只读模式才更新实时分数
    if (!readonly) {
        setTimeout(updateLiveScore, 50);
    }
}

// 静态计算当前总分（不依赖 DOM，用于只读模式预计算）
function calcCurrentScoreStatic(indicators) {
    let total = 0;
    for (const ind of indicators) {
        for (const opt of (ind.options || [])) {
            if (opt.checked) {
                total += parseFloat(opt.score) || 0;
                break;
            }
        }
    }
    return Math.round(total * 10) / 10;
}

async function submitEval(submitType) {
    if (submitType === '1') {
        if (!confirm('提交后不能修改，确认提交？')) return;
    }

    // 检查是否所有指标都已选择
    const indicators = currentEvalForm.indicators || [];
    for (const ind of indicators) {
        const opts = ind.options || [];
        if (opts.length > 0) {
            const name = opts[0].name;
            const checked = document.querySelector(`input[name="${name}"]:checked`);
            if (!checked) {
                showToast('❌ 请完成所有评价指标', 'error');
                return;
            }
        }
    }

    // 收集表单数据 — 用 FormData 自然顺序（即 DOM 顺序），
    // 确保 hidden 字段在前、radio 值在后，与浏览器原生提交顺序一致。
    // 旧教务 Java 系统可能对参数顺序敏感。
    const form = document.getElementById('eval-native-form');
    const formData = new FormData(form);
    const payload = {};

    // 第一步：FormData 顺序（hidden 在前，checked radio 在后）作为基础
    for (const [k, v] of formData.entries()) {
        payload[k] = v;
    }

    // 第二步：补上课程列表页的隐藏字段（不在表单内，如 cj0701id）
    if (currentBatchData && currentBatchData.hidden_fields) {
        for (const [k, v] of Object.entries(currentBatchData.hidden_fields)) {
            if (!(k in payload)) {
                payload[k] = v;
            }
        }
    }

    // 第三步：用 DOM 实际 checked 状态覆盖 radio 值（理论上与 FormData 一致，但以防万一）
    for (const ind of currentEvalForm.indicators) {
        const opts = ind.options || [];
        if (opts.length === 0) continue;
        const groupName = opts[0].name;
        const checkedRadio = document.querySelector(`input[name="${groupName}"]:checked`);
        if (checkedRadio) {
            payload[groupName] = checkedRadio.value;  // 覆盖为 DOM 确认值
        }
    }

    // 调试：输出所有 radio 键值对
    const radioKeys = Object.keys(payload).filter(k => k.startsWith('pj0601id_'));
    console.log('提交评教 — radio 组数:', radioKeys.length, radioKeys);
    console.log('提交评教 — 完整 payload 键数:', Object.keys(payload).length);

    showLoading('正在提交评教...');
    try {
        const resp = await fetch('/api/submit-eval', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                form_data: payload,
                submit_type: submitType,
                action: currentEvalForm.action || '/njlgdx/xspj/xspj_save.do',
                _debug_radio_count: radioKeys.length,
            }),
        });
        const data = await resp.json();
        hideLoading();
        if (data.success) {
            showToast('✅ ' + data.message, 'success');
            // 重新拉取课程列表，刷新已提交/已保存状态
            await refreshCourseList();
        } else {
            showToast('❌ ' + data.message, 'error');
        }
    } catch (e) {
        hideLoading();
        showToast('❌ 提交失败: ' + e.message, 'error');
    }
}

// ============================================================
// 自动填写算法：根据期望分数自动选择选项
// ============================================================

// 计算满分
function calcMaxScore(indicators) {
    let total = 0;
    for (const ind of indicators) {
        let max = 0;
        for (const opt of (ind.options || [])) {
            const s = parseFloat(opt.score);
            if (s > max) max = s;
        }
        total += max;
    }
    return Math.round(total);
}

// 计算当前已选总分
function calcCurrentScore(indicators) {
    let total = 0;
    for (const ind of indicators) {
        for (const opt of (ind.options || [])) {
            const radio = document.querySelector(`input[name="${opt.name}"]:checked`);
            if (radio) {
                total += parseFloat(opt.score) || 0;
                break;
            }
        }
    }
    return Math.round(total * 10) / 10;
}

// 自动填写
function autoFillEval() {
    const input = document.getElementById('eval-target-score');
    const targetRaw = input.value.trim();
    if (!targetRaw) {
        showToast('❌ 请输入期望分数', 'error');
        input.focus();
        return;
    }
    const target = parseFloat(targetRaw);
    if (isNaN(target) || target < 0 || target > 100) {
        showToast('❌ 请输入 0~100 的分数', 'error');
        return;
    }

    const indicators = currentEvalForm.indicators || [];
    if (indicators.length === 0) {
        showToast('❌ 无评价指标', 'error');
        return;
    }

    const maxScore = calcMaxScore(indicators);

    // 步骤 1: 每条指标选最接近目标比例的选项
    const selections = [];  // [{ind, colIndex, score}]
    for (const ind of indicators) {
        const opts = ind.options || [];
        if (opts.length === 0) continue;

        // 该指标的满分
        let indMax = 0;
        for (const o of opts) {
            const s = parseFloat(o.score) || 0;
            if (s > indMax) indMax = s;
        }

        // 目标分数按比例分配到该指标
        const indTarget = maxScore > 0 ? (target / maxScore) * indMax : 0;

        // 选最接近的
        let bestIdx = 0;
        let bestDist = Infinity;
        for (let i = 0; i < opts.length; i++) {
            const s = parseFloat(opts[i].score) || 0;
            const dist = Math.abs(s - indTarget);
            if (dist < bestDist) {
                bestDist = dist;
                bestIdx = i;
            }
        }
        selections.push({ ind, colIndex: bestIdx, score: parseFloat(opts[bestIdx].score) || 0 });
    }

    // 步骤 2: 防作弊 — 不能所有指标选同一列
    // 如果触发防作弊，则全面重新计算：从所有列组合中找到最接近目标分的方案
    const allSameColumn = selections.every(s => s.colIndex === selections[0].colIndex);
    if (allSameColumn && selections.length > 1) {
        // 取消步骤 1 的贪心结果，改为全局搜索最佳组合
        // 策略：每列选一个"牺牲者"，让它选次优列 → 找总分最接近目标分的组合
        const currentTotal = selections.reduce((sum, s) => sum + s.score, 0);
        let bestCombo = null;
        let bestPenalty = Math.abs(currentTotal - target); // 基准：不做任何调整的偏离

        for (let sacrificeIdx = 0; sacrificeIdx < selections.length; sacrificeIdx++) {
            const opts = selections[sacrificeIdx].ind.options || [];
            for (let altCol = 0; altCol < opts.length; altCol++) {
                if (altCol === selections[sacrificeIdx].colIndex) continue;
                const altScore = parseFloat(opts[altCol].score) || 0;
                const newTotal = currentTotal - selections[sacrificeIdx].score + altScore;
                const penalty = Math.abs(newTotal - target); // 修正：用目标分做参考
                if (penalty < bestPenalty) {
                    bestPenalty = penalty;
                    bestCombo = { sacrificeIdx, altCol, altScore, newTotal };
                }
            }
        }

        if (bestCombo) {
            selections[bestCombo.sacrificeIdx].colIndex = bestCombo.altCol;
            selections[bestCombo.sacrificeIdx].score = bestCombo.altScore;
        }
    }

    // 步骤 3: 微调 — 在满足防作弊的前提下，继续换指标让总分更接近目标
    for (let round = 0; round < 5; round++) {
        const currentTotal = selections.reduce((sum, s) => sum + s.score, 0);
        const currentPenalty = Math.abs(currentTotal - target);
        if (currentPenalty < 0.5) break; // 足够接近了

        let bestSwap = null;
        let bestPenalty = currentPenalty;

        for (let i = 0; i < selections.length; i++) {
            const opts = selections[i].ind.options || [];
            for (let j = 0; j < opts.length; j++) {
                if (j === selections[i].colIndex) continue;
                const newScore = parseFloat(opts[j].score) || 0;
                const newTotal = currentTotal - selections[i].score + newScore;
                const newPenalty = Math.abs(newTotal - target);

                // 检查是否仍然满足防作弊（不能换完后全员又同列）
                const testSelections = selections.map((s, idx) =>
                    idx === i ? { ...s, colIndex: j } : { ...s }
                );
                const testAllSame = testSelections.every(s => s.colIndex === testSelections[0].colIndex);
                if (testAllSame) continue;

                if (newPenalty < bestPenalty) {
                    bestPenalty = newPenalty;
                    bestSwap = { idx: i, col: j, score: newScore };
                }
            }
        }

        if (bestSwap) {
            selections[bestSwap.idx].colIndex = bestSwap.col;
            selections[bestSwap.idx].score = bestSwap.score;
        } else {
            break; // 无法继续优化
        }
    }

    // 步骤 4: 应用选择
    for (const sel of selections) {
        const opts = sel.ind.options || [];
        if (sel.colIndex < opts.length) {
            const radio = document.querySelector(`input[name="${opts[sel.colIndex].name}"][value="${opts[sel.colIndex].value}"]`);
            if (radio) radio.checked = true;
        }
    }

    // 从 selections 计算实际总分（DOM 的 checked 已同步）
    const actualScore = Math.round(selections.reduce((sum, s) => sum + s.score, 0) * 10) / 10;
    showFillResult(actualScore, target);
}

// 实时更新当前总分显示
function updateLiveScore() {
    const indicators = currentEvalForm ? currentEvalForm.indicators : [];
    const total = calcCurrentScore(indicators);
    const el = document.getElementById('eval-live-total');
    if (el) {
        el.textContent = total > 0 ? total : '—';
        el.style.color = 'var(--primary)';
    }
}

// 显示自动填写结果
function showFillResult(actualScore, target) {
    const el = document.getElementById('eval-live-total');
    if (el) {
        el.textContent = actualScore;
        const diff = Math.abs(actualScore - target);
        const color = diff <= 1 ? 'var(--success)' : (diff <= 3 ? '#e6a817' : 'var(--danger)');
        el.style.color = color;
    }
}

// ============================================================
// 批量评教（一键评教）
// ============================================================

async function startBatchEval() {
    if (!currentBatchData || !currentBatchUrl) {
        showToast('❌ 无批次数据', 'error');
        return;
    }

    const unsubmitted = (currentBatchData.courses || []).filter(c => !c.submitted);
    if (unsubmitted.length === 0) {
        showToast('✅ 所有课程已提交', 'success');
        return;
    }

    const targetInput = document.getElementById('batch-target-score');
    const targetScore = parseInt(targetInput ? targetInput.value : '95') || 95;

    const actionPath = currentEvalForm ? currentEvalForm.action : '/njlgdx/xspj/xspj_save.do';

    if (!confirm(`将自动为 ${unsubmitted.length} 门课程以目标分 ${targetScore} 评分并提交，确认继续？`)) {
        return;
    }

    // 显示进度 UI，隐藏课程列表
    document.getElementById('eval-modal-content').style.display = 'none';
    document.getElementById('batch-progress').style.display = 'block';
    document.getElementById('batch-progress-count').textContent = `0 / ${unsubmitted.length}`;
    document.getElementById('batch-progress-fill').style.width = '0%';
    document.getElementById('batch-progress-status').textContent = '正在启动...';
    document.getElementById('batch-progress-results').innerHTML = '';
    document.getElementById('batch-progress-actions').style.display = 'none';
    document.getElementById('eval-modal-title').textContent = '🚀 一键评教中...';

    try {
        const resp = await fetch('/api/batch-submit-eval', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                batch_url: currentBatchUrl,
                action_path: actionPath,
                hidden_fields: currentBatchData.hidden_fields || {},
                target_score: targetScore,
                submit_type: '1',
            }),
        });
        const data = await resp.json();

        if (!data.success) {
            showToast('❌ ' + data.message, 'error');
            hideBatchProgress();
            return;
        }

        if (data.total === 0) {
            showToast('✅ 所有课程已提交，无需评价', 'success');
            hideBatchProgress();
            await refreshCourseList();
            return;
        }

        // 开始轮询进度
        pollBatchProgress(data.batch_id);
    } catch (e) {
        showToast('❌ 请求失败: ' + e.message, 'error');
        hideBatchProgress();
    }
}

function pollBatchProgress(batchId) {
    if (batchPollTimer) clearInterval(batchPollTimer);

    batchPollTimer = setInterval(async () => {
        try {
            const resp = await fetch('/api/batch-progress/' + batchId);
            const data = await resp.json();
            if (!data.success) {
                clearInterval(batchPollTimer);
                batchPollTimer = null;
                showToast('❌ ' + (data.message || '进度查询失败'), 'error');
                hideBatchProgress();
                return;
            }
            renderBatchProgress(data);
            if (data.done) {
                clearInterval(batchPollTimer);
                batchPollTimer = null;
            }
        } catch (e) {
            console.error('轮询进度失败:', e);
        }
    }, 1500);
}

function renderBatchProgress(progress) {
    const pct = progress.total > 0 ? Math.round((progress.current / progress.total) * 100) : 0;

    document.getElementById('batch-progress-count').textContent =
        `${progress.current} / ${progress.total}`;
    document.getElementById('batch-progress-fill').style.width = pct + '%';
    document.getElementById('batch-progress-status').textContent = progress.message;

    // 渲染各课程结果
    let resultsHtml = '';
    for (const r of (progress.results || [])) {
        const icon = r.status === 'success' ? '✅' : '❌';
        const detail = r.status === 'success'
            ? (r.score ? ` — ${r.score}分` : '')
            : ` — ${escapeHtml(r.error || '未知错误')}`;
        resultsHtml += `
            <div class="batch-progress-item ${r.status}">
                <span>${icon} ${escapeHtml(r.course)}</span>
                <span class="batch-progress-item-detail">${detail}</span>
            </div>`;
    }
    document.getElementById('batch-progress-results').innerHTML = resultsHtml;

    // 完成时显示操作按钮
    if (progress.done) {
        document.getElementById('batch-progress-status').textContent =
            `已完成！成功 ${progress.results.filter(r => r.status === 'success').length} / ${progress.total}`;
        document.getElementById('batch-progress-actions').style.display = 'block';
        document.getElementById('eval-modal-title').textContent = '✅ 批量评教完成';

        // 计算总分促进用户反馈
        const successCount = progress.results.filter(r => r.status === 'success').length;
        const failCount = progress.results.filter(r => r.status === 'failed').length;
        let msg = `✅ 批量评教：${successCount} 成功`;
        if (failCount > 0) msg += `，${failCount} 失败`;
        showToast(msg, failCount > 0 ? 'warning' : 'success');
    }
}

function hideBatchProgress() {
    document.getElementById('batch-progress').style.display = 'none';
    document.getElementById('eval-modal-content').style.display = 'block';
}

function closeEvalModal() {
    // 停止批量评教轮询
    if (batchPollTimer) {
        clearInterval(batchPollTimer);
        batchPollTimer = null;
    }
    document.getElementById('eval-modal').style.display = 'none';
    document.getElementById('eval-modal-content').innerHTML = '';
    document.getElementById('batch-progress').style.display = 'none';
    currentEvalForm = null;
    currentBatchData = null;
    currentView = 'courses';
    document.body.style.overflow = '';
}

document.addEventListener('click', function(e) {
    if (e.target.id === 'eval-modal') {
        if (currentView === 'form' && currentBatchData) {
            if (confirm('关闭将丢失已选择的评分，确定关闭？')) {
                closeEvalModal();
            }
        } else {
            closeEvalModal();
        }
    }
});
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        if (currentView === 'form' && currentBatchData) {
            if (confirm('关闭将丢失已选择的评分，确定关闭？')) {
                closeEvalModal();
            }
        } else {
            closeEvalModal();
        }
    }
});
