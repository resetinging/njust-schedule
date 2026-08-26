/* ============================================================
   南理工课表管理系统 - 全局 JavaScript
   ============================================================ */

// --- HTML 转义（防 XSS） ---
function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// --- 登录 token 管理（多用户：请求携带 X-Auth-Token） ---
const TOKEN_KEY = '_njust_token';
function getToken() { return localStorage.getItem(TOKEN_KEY) || ''; }
function setToken(token) {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
}
function clearToken() { localStorage.removeItem(TOKEN_KEY); }

// 带 token 的 fetch 封装（所有页面统一使用）
async function apiFetch(url, options = {}) {
    const headers = Object.assign({}, options.headers || {});
    const token = getToken();
    if (token) headers['X-Auth-Token'] = token;
    return fetch(url, Object.assign({}, options, { headers }));
}

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
function updateNavStatus(data) {
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');

    // 优先显示登录状态
    if (data.logged_in) {
        dot.className = 'status-dot online';
        text.textContent = data.student_name || '已登录';
        text.title = (data.login_method === 'webvpn')
            ? '🌐 智慧理工登录' : '🏫 教务直连';
    } else {
        // 未登录时显示网络状态
        const net = data.network || {};
        if (net.reachable) {
            dot.className = 'status-dot online';
            text.textContent = net.label || '教务在线';
            text.title = net.latency_ms ? Math.round(net.latency_ms) + 'ms' : '';
        } else {
            dot.className = 'status-dot offline';
            text.textContent = '离线';
            text.title = net.hint || '请检查教务系统连接';
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
        const resp = await apiFetch('/api/status');
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
