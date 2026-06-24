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
    const textEl = document.getElementById('loading-text');
    if (textEl) textEl.textContent = message;
}

function hideLoading() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) overlay.style.display = 'none';
}

// --- 导航状态更新 ---
function updateNavStatus(data) {
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');

    if (data.logged_in) {
        dot.className = 'status-dot online';
        text.textContent = data.student_name || '已登录';
    } else {
        dot.className = 'status-dot offline';
        text.textContent = '未登录';
    }
}

// --- 学期信息（各页面共用） ---
function getCurrentSemester() {
    const badge = document.getElementById('semester-badge');
    return badge ? badge.textContent.trim() : '';
}
