/* ============================================================
   南理工课表管理系统 - 全局 JavaScript
   ============================================================ */

// --- Toast 消息 ---
function showToast(message, type = 'info') {
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }

    // 限制最多 3 个 toast，超出移除最早的
    const existing = container.querySelectorAll('.toast');
    if (existing.length >= 3) existing[0].remove();

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// --- 加载遮罩 ---
function showLoading(message = '正在加载...') {
    let overlay = document.getElementById('loading-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'loading-overlay';
        overlay.className = 'loading-overlay';
        overlay.innerHTML = '<div class="loading-spinner"></div><p id="loading-text"></p>';
        document.body.appendChild(overlay);
    }
    overlay.style.display = 'flex';
    overlay.offsetHeight; // 强制回流，使过渡生效
    overlay.style.opacity = '1';
    const textEl = document.getElementById('loading-text');
    if (textEl) textEl.textContent = message;
}

function hideLoading() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) {
        overlay.style.opacity = '0';
        setTimeout(() => {
            if (overlay.style.opacity === '0') overlay.style.display = 'none';
        }, 200);
    }
}

// --- 导航状态更新 ---
// 使用 sessionStorage 跨页面记住已弹过 toast，避免每次切页面都弹
const AUTO_LOGIN_TOAST_KEY = '_njust_auto_login_toast_shown';

function updateNavStatus(data) {
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');

    if (data.logged_in) {
        dot.className = 'status-dot online';
        text.textContent = data.student_name || '已登录';
        // 自动登录成功提示（同窗口仅首次）
        if (data.auto_login_attempted && !sessionStorage.getItem(AUTO_LOGIN_TOAST_KEY)) {
            sessionStorage.setItem(AUTO_LOGIN_TOAST_KEY, '1');
            showToast('✅ 已自动登录 — ' + (data.student_name || data.student_id), 'success');
        }
    } else {
        dot.className = 'status-dot offline';
        text.textContent = '未登录';
        // 自动登录失败提示（同窗口仅首次）
        if (data.auto_login_attempted && !sessionStorage.getItem(AUTO_LOGIN_TOAST_KEY)) {
            sessionStorage.setItem(AUTO_LOGIN_TOAST_KEY, '1');
            const reason = data.auto_login_error || '凭证无效或教务系统不可达';
            showToast('⚠️ 自动登录失败: ' + reason + '，请前往设置手动登录', 'warning');
        }
    }
}

// --- 学期信息（各页面共用） ---
function getCurrentSemester() {
    const badge = document.getElementById('semester-badge');
    return badge ? badge.textContent.trim() : '';
}

// --- 共享全局状态（各页面直接引用，不再各自声明） ---
window.currentSemester = '';
window.isLoggedIn = false;

// --- 日期解析（本地时间，兼容多种格式） ---
function parseDate(str) {
    if (!str) return null;
    const cleaned = str.replace(/[年月]/g, '-').replace(/[日号]/g, '').replace(/\//g, '-').trim();
    const m = cleaned.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
    if (m) return new Date(parseInt(m[1]), parseInt(m[2]) - 1, parseInt(m[3]));
    const d = new Date(cleaned);
    if (!isNaN(d.getTime())) return d;
    return null;
}

// --- 日期格式化（统一 YYYY-MM-DD） ---
function formatDate(str) {
    const d = parseDate(str);
    if (!d) return str || '日期待定';
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}

// --- 通用状态加载（各页面共用） ---
async function loadStatus() {
    try {
        const resp = await fetch('/api/status');
        const data = await resp.json();
        window.currentSemester = data.semester || '';
        window.isLoggedIn = data.logged_in || false;
        const badge = document.getElementById('semester-badge');
        if (badge) badge.textContent = data.semester || '';
        updateNavStatus(data);
    } catch (e) {
        console.error('获取状态失败:', e);
    }
}
