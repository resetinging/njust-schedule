// 登录模式: 教务改版后只保留智慧理工 SSO（教务直连已下线）
let currentLoginMode = 'webvpn';
// 当前验证码会话 ID（获取验证码时由后端签发，登录时回传；多用户下验证码与登录绑定）
let captchaId = '';

document.addEventListener('DOMContentLoaded', async () => {
    switchLoginMode('webvpn');           // 只保留智慧理工: 初始化表单为 SSO 布局
    await loadStatus();                  // main.js 共享版本
    await loadSettingsAndLoginInfo();    // 补充登录信息面板
    loadSemesters();
    checkNetworkStatus();                // 网络连通性检测
});

// ============================================================
// 登录模式切换
// ============================================================
function switchLoginMode(mode) {
    // 教务改版后只保留智慧理工一步登录; 旧页面若仍传 direct 也强制落到 webvpn
    currentLoginMode = 'webvpn';
    document.querySelectorAll('.login-mode-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.mode === 'webvpn');
    });
    const label = document.getElementById('password-label');
    if (label) {
        label.innerHTML = '智慧理工密码 <span style="color:#1976d2;font-size:12px;">（统一身份认证）</span>';
    }
    const pwd = document.getElementById('password');
    if (pwd) pwd.placeholder = '请输入智慧理工密码';
}

// ============================================================
// 网络状态检测
// ============================================================
async function checkNetworkStatus() {
    const dot = document.getElementById('network-dot');
    const label = document.getElementById('network-label');
    const latency = document.getElementById('network-latency');
    try {
        const resp = await apiFetch('/api/status');
        const data = await resp.json();
        const net = data.network || {};
        if (net.reachable) {
            dot.className = 'network-dot online';
            label.textContent = net.label || '教务在线';
            if (net.latency_ms) {
                latency.textContent = Math.round(net.latency_ms) + 'ms';
            }
        } else {
            dot.className = 'network-dot offline';
            label.textContent = '离线（校外）';
            latency.textContent = '';
        }
        if (net.hint) {
            label.title = net.hint;
        }
    } catch (e) {
        dot.className = 'network-dot';
        label.textContent = '检测失败';
        latency.textContent = '';
    }
}

// 加载设置 + 更新登录状态面板（settings 页面特有）
async function loadSettingsAndLoginInfo() {
    try {
        const resp = await apiFetch('/api/status');
        const data = await resp.json();
        updateLoginInfo(data);
        await loadSettings();
    } catch (e) {
        console.error('获取状态失败:', e);
    }
}

async function loadSettings() {
    try {
        const resp = await apiFetch('/api/settings');
        const data = await resp.json();
        document.getElementById('student-id').value = data.student_id || '';
        document.getElementById('semester-select').value = data.semester || data.current_semester || '';
        document.getElementById('first-week-date').value = data.first_week_date || '';
        // 显示密码保存状态
        const badge = document.getElementById('password-saved-badge');
        if (badge) {
            badge.style.display = data.has_password ? 'inline' : 'none';
        }
        // 标记密码是否已保存（登录时空密码也能提交）
        window._hasSavedPassword = data.has_password;
        updateDataStats(data);
    } catch (e) {
        console.error('加载设置失败:', e);
    }
}

async function loadSemesters() {
    try {
        const resp = await apiFetch('/api/settings');
        const data = await resp.json();
        const select = document.getElementById('semester-select');
        const list = data.semester_list || [];
        const currentSem = data.semester || data.current_semester || '';

        select.innerHTML = list.map(s =>
            `<option value="${s}" ${s === currentSem ? 'selected' : ''}>${s} 学年</option>`
        ).join('');
    } catch (e) {
        console.error('加载学期列表失败:', e);
    }
}

function updateLoginInfo(data) {
    const infoDiv = document.getElementById('login-info');
    const methodLabels = {
        'web-auto': '🏫 教务直连（自动）',
        'web-manual': '🏫 教务直连（手动验证码）',
        'webvpn': '🌐 智慧理工',
    };
    if (data.logged_in) {
        infoDiv.style.display = 'block';
        document.getElementById('info-status').innerHTML =
            '<span style="color:#27ae60;">● 已登录</span>';
        document.getElementById('info-student-id').textContent = data.student_id;
        document.getElementById('info-student-name').textContent =
            data.student_name || '-';
        document.getElementById('info-login-method').textContent =
            methodLabels[data.login_method] || data.login_method || '未知';
        document.getElementById('btn-login').textContent = '🔄 重新登录';
        // 根据已登录方式预选 tab
        if (data.login_method === 'webvpn') {
            switchLoginMode('webvpn');
        }
    } else {
        infoDiv.style.display = 'block';
        document.getElementById('info-status').innerHTML =
            '<span style="color:#e74c3c;">● 未登录</span>';
        document.getElementById('info-student-id').textContent =
            data.student_id || '未设置';
        document.getElementById('info-student-name').textContent = '-';
        document.getElementById('info-login-method').textContent = '-';
        document.getElementById('btn-login').textContent = '🔑 登录';
    }
}

function updateDataStats(data) {
    const statsDiv = document.getElementById('data-stats');
    statsDiv.innerHTML = `
        <p>📊 课表数据: <strong id="stats-courses">-</strong> 门课程</p>
        <p>📊 考试数据: <strong id="stats-exams">-</strong> 场考试</p>
    `;
    // 异步加载实际数量（未登录时接口返回 401，显示 '-'）
    apiFetch('/api/courses').then(r => r.json()).then(d => {
        document.getElementById('stats-courses').textContent = (d && d.success) ? d.count : '-';
    });
    apiFetch('/api/exams').then(r => r.json()).then(d => {
        document.getElementById('stats-exams').textContent = (d && d.success) ? d.count : '-';
    });
}

// 测试连接
async function testConnection() {
    showToast('正在测试连接...', 'info');
    try {
        const resp = await apiFetch('/api/connect-test');
        const data = await resp.json();
        if (data.ok) {
            showToast('✅ ' + data.message, 'success');
        } else {
            showToast('❌ ' + data.message, 'error');
        }
    } catch (e) {
        showToast('❌ 连接测试失败: ' + e.message, 'error');
    }
}

// 登录
document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const studentId = document.getElementById('student-id').value.trim();
    const password = document.getElementById('password').value;

    if (!studentId) {
        showToast('❌ 请输入学号', 'error');
        return;
    }
    if (!password) {
        showToast('❌ 请输入密码', 'error');
        return;
    }

    // 智慧理工一步登录: SSO 直连换取教务会话（免教务密码/验证码）
    const isWebVPN = true;
    const url = '/api/login-webvpn';
    const body = JSON.stringify({ student_id: studentId, password });
    showLoading('正在通过智慧理工 SSO 登录...');
    document.getElementById('loading-text').textContent =
        '正在连接智慧理工并登录教务，请稍候...';

    try {
        const resp = await apiFetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body,
        });
        const data = await resp.json();
        hideLoading();

        if (data.success) {
            setToken(data.token || '');   // 保存登录 token（多用户会话标识）
            setSid(data.student_id || ''); // 保存学号（数据缓存按用户隔离）
            captchaId = '';
            showToast('✅ ' + data.message, 'success');
            document.getElementById('password').disabled = false;
            loadStatus();
            loadSettings();
            checkNetworkStatus();
        } else {
            captchaId = '';   // 登录失败，验证码会话作废
            showToast('❌ ' + data.message, 'error');
            // WebVPN 失败时显示调试日志
            if (isWebVPN && data.debug_log && data.debug_log.length > 0) {
                console.log('=== WebVPN 调试日志 ===');
                data.debug_log.forEach(l => console.log(l));
                // 也显示在页面上
                const logText = data.debug_log.slice(-10).join('\n');
                const logContainer = document.getElementById('webvpn-debug-log');
                const logPre = document.getElementById('webvpn-debug-content');
                if (logContainer && logPre) {
                    logPre.textContent = logText;
                    logContainer.style.display = 'block';
                }
            } else {
                const logContainer = document.getElementById('webvpn-debug-log');
                if (logContainer) logContainer.style.display = 'none';
            }
        }
    } catch (e) {
        hideLoading();
        showToast('❌ 请求失败: ' + e.message, 'error');
    }
});

// 切换学期
document.getElementById('semester-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const semester = document.getElementById('semester-select').value;
    const firstWeekDate = document.getElementById('first-week-date').value;

    try {
        const resp = await apiFetch('/api/semester', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ semester }),
        });
        const data = await resp.json();
        showToast(data.success ? '✅ ' + data.message : '❌ ' + data.message,
                  data.success ? 'success' : 'error');
        // 同时保存第一周日期
        if (firstWeekDate) {
            await apiFetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ first_week_date: firstWeekDate }),
            });
        }
    } catch (e) {
        showToast('❌ 切换失败: ' + e.message, 'error');
    }
});

// 一键刷新
async function refreshAll() {
    showLoading('正在从教务系统获取全部数据...');
    document.getElementById('loading-text').textContent =
        '正在连接教务系统，可能需要半分钟左右...';

    try {
        const resp = await apiFetch('/api/refresh-all', { method: 'POST' });
        const data = await resp.json();
        hideLoading();
        showToast('✅ ' + data.message, 'success');
        loadSettings();
    } catch (e) {
        hideLoading();
        showToast('❌ 刷新失败: ' + e.message, 'error');
    }
}

// 清除数据
async function clearData() {
    if (!confirm('确定要清除当前学期的课表和考试数据吗？此操作不可恢复。')) {
        return;
    }
    try {
        const resp = await apiFetch('/api/clear-data', { method: 'POST' });
        const data = await resp.json();
        showToast('✅ ' + data.message, 'success');
        loadSettings();
    } catch (e) {
        showToast('❌ 清除失败: ' + e.message, 'error');
    }
}

// 退出登录
async function logout() {
    try {
        document.getElementById('login-info').style.display = 'none';
        document.getElementById('btn-login').textContent = '🔑 登录';
        document.getElementById('info-status').innerHTML =
            '<span style="color:#e74c3c;">● 未登录</span>';
        showToast('已退出登录（会话已清除）', 'info');
    } catch (e) {
        showToast('退出失败: ' + e.message, 'error');
    }
}

// 第一周日期变更时自动保存
document.getElementById('first-week-date').addEventListener('change', async function () {
    const date = this.value;
    try {
        await apiFetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ first_week_date: date }),
        });
        showToast('✅ 第一周日期已保存，回到课表页面将自动跳转', 'success');
    } catch (e) {
        showToast('❌ 保存失败: ' + e.message, 'error');
    }
});

// 注: 第二步「教务密码 + 验证码」流程已随教务直连一起下线, 相关验证码加载函数已移除。

// 退出登录（多用户：销毁后端会话 token + 清除本机缓存）
async function logout() {
    try {
        await apiFetch('/api/logout', { method: 'POST' });
    } catch (e) {
        console.error('退出登录请求失败:', e);
    }
    clearUserCaches();
    clearToken();
    setSid('');
    captchaId = '';
    showToast('✅ 已退出登录', 'success');
    loadStatus();
    loadSettings();
    checkNetworkStatus();
}

// 密码明文切换（👁/🙈）
function togglePwdVisibility(inputId) {
    const input = document.getElementById(inputId);
    if (!input) return;
    const show = (input.type === 'password');
    input.type = show ? 'text' : 'password';
    const btn = input.parentElement.querySelector('.pwd-toggle');
    if (btn) btn.textContent = show ? '🙈' : '👁';
}

// 重置密码标签为智慧理工（统一身份认证）状态
function resetPasswordLabel() {
    document.getElementById('password-label').innerHTML =
        '智慧理工密码 <span id="password-saved-badge" class="badge badge-success" style="display:none;">✅ 已保存</span>';
    document.getElementById('password').placeholder = '请输入智慧理工密码';
}
