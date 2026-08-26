// 当前登录模式: 'direct' | 'webvpn'
let currentLoginMode = 'direct';
// 当前验证码会话 ID（获取验证码时由后端签发，登录时回传；多用户下验证码与登录绑定）
let captchaId = '';

document.addEventListener('DOMContentLoaded', async () => {
    await loadStatus();                  // main.js 共享版本
    await loadSettingsAndLoginInfo();    // 补充登录信息面板
    loadSemesters();
    checkNetworkStatus();                // 网络连通性检测
});

// ============================================================
// 登录模式切换
// ============================================================
function switchLoginMode(mode) {
    currentLoginMode = mode;
    // 更新 tab 样式
    document.querySelectorAll('.login-mode-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.mode === mode);
    });
    // 更新描述文字
    const desc = document.getElementById('login-mode-desc');
    const captchaArea = document.getElementById('captcha-area');
    const btnCaptcha = document.getElementById('btn-load-captcha');
    const btnCaptcha2 = document.getElementById('btn-load-captcha-2');
    if (mode === 'webvpn') {
        desc.innerHTML = '<strong>两步登录：</strong>Step 1 智慧理工 SSO 验证 → Step 2 教务系统登录。<br>点击「获取验证码」完成 Step 1，输入<strong>教务密码+验证码</strong>完成 Step 2。';
        // WebVPN 模式也显示验证码（教务系统的验证码，非 SSO）
        if (btnCaptcha) btnCaptcha.style.display = 'inline-block';
        if (btnCaptcha2) btnCaptcha2.style.display = 'inline-block';
        // 先隐藏验证码区域，点获取后再显示
        document.getElementById('captcha-img').style.display = 'none';
        document.getElementById('captcha-input-group').style.display = 'none';
        // 显示两步提示引导 + 教务密码框
        document.getElementById('password-label').innerHTML =
            '智慧理工密码 <span style="color:#1976d2;font-size:12px;">（Step 1）</span>';
        document.getElementById('password').placeholder = '请输入智慧理工密码';
        document.getElementById('jwc-password-group').style.display = 'block';
        document.getElementById('sso-step-hint').style.display = 'none';
    } else {
        desc.innerHTML = '直接登录教务系统，无需校园网环境。';
        if (btnCaptcha) btnCaptcha.style.display = '';
        if (btnCaptcha2) btnCaptcha2.style.display = '';
        document.getElementById('jwc-password-group').style.display = 'none';
        resetPasswordLabel();
    }
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
        const jwcBadge = document.getElementById('jwc-password-saved-badge');
        if (jwcBadge) {
            jwcBadge.style.display = data.has_jwc_password ? 'inline' : 'none';
        }
        // 标记密码是否已保存（登录时空密码也能提交）
        window._hasSavedPassword = data.has_password;
        window._hasSavedJwcPassword = data.has_jwc_password;
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
    const captchaInput = document.getElementById('captcha-input').value.trim();

    if (!studentId) {
        showToast('❌ 请输入学号', 'error');
        return;
    }
    if (!password) {
        showToast('❌ 请输入密码', 'error');
        return;
    }

    // 根据登录模式选择 API 端点
    const isWebVPN = currentLoginMode === 'webvpn';
    const useCaptcha = (
        document.getElementById('captcha-area').style.display !== 'none'
        && captchaInput.length > 0
    );

    let url, body;
    if (isWebVPN && useCaptcha) {
        // Step 2: 智慧理工 + 手动验证码（用户已输入教务密码+验证码）
        const jwcPwd = document.getElementById('jwc-password').value || password;
        if (!jwcPwd) {
            showToast('❌ 请输入教务密码', 'error');
            return;
        }
        url = '/api/login-webvpn-manual';
        body = JSON.stringify({ student_id: studentId, password, jwc_password: jwcPwd, captcha: captchaInput, captcha_id: captchaId });
        showLoading('Step 2/2: 正在登录教务系统...');
        document.getElementById('loading-text').textContent = '正在提交教务密码和验证码...';
    } else if (isWebVPN) {
        // 自动 OCR 模式（使用智慧理工密码，教务密码可选）
        const jwcPwd = document.getElementById('jwc-password').value;
        url = '/api/login-webvpn';
        body = JSON.stringify({ student_id: studentId, password, jwc_password: jwcPwd || password });
        showLoading('正在通过智慧理工 SSO 登录...');
        document.getElementById('loading-text').textContent =
            '正在连接智慧理工并登录教务，请稍候...';
    } else if (useCaptcha) {
        url = '/api/login-manual';
        body = JSON.stringify({ student_id: studentId, password, captcha: captchaInput, captcha_id: captchaId });
        showLoading('正在登录教务系统...');
        document.getElementById('loading-text').textContent =
            '正在使用手动验证码登录...';
    } else {
        url = '/api/login';
        body = JSON.stringify({ student_id: studentId, password });
        showLoading('正在登录教务系统...');
        document.getElementById('loading-text').textContent =
            '正在自动识别验证码并登录，请稍候...';
    }

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
            document.getElementById('captcha-input').value = '';
            document.getElementById('captcha-area').style.display = 'none';
            resetPasswordLabel();
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
            // 如果提示验证码相关或密码错误（可能是教务密码不同），提示走手动两步流程
            if (data.need_captcha || data.message.includes('验证码')
                || (isWebVPN && data.message.includes('密码错误'))) {
                if (isWebVPN) {
                    showToast('💡 建议点击「显示验证码」进入两步登录：先确认智慧理工密码，再单独输入教务密码', 'info');
                }
                loadCaptchaAndShow();
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

// 加载并显示验证码
async function loadCaptchaAndShow() {
    document.getElementById('captcha-area').style.display = 'block';
    document.getElementById('captcha-input-group').style.display = 'block';
    loadCaptcha();
}

async function loadCaptcha() {
    const img = document.getElementById('captcha-img');
    const input = document.getElementById('captcha-input');
    const loadBtn = document.getElementById('btn-load-captcha');
    const isWebVPN = currentLoginMode === 'webvpn';

    img.style.display = 'none';
    if (loadBtn) loadBtn.style.display = 'none';

    try {
        let resp, data;

        if (isWebVPN) {
            // ========================================================
            // 智慧理工模式：Step 1 — SSO 登录 → 获取教务验证码
            // ========================================================
            const studentId = document.getElementById('student-id').value.trim();
            const password = document.getElementById('password').value;
            if (!studentId || !password) {
                showToast('❌ 请先输入学号和智慧理工密码', 'error');
                if (loadBtn) loadBtn.style.display = 'inline-block';
                return;
            }
            showLoading('Step 1/2: 正在登录智慧理工...');
            resp = await apiFetch('/api/get-webvpn-captcha', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ student_id: studentId, password }),
            });
            data = await resp.json();
            hideLoading();
        } else {
            // 直连模式
            resp = await apiFetch('/api/get-captcha');
            data = await resp.json();
        }

        if (data.success && data.captcha_b64) {
            captchaId = data.captcha_id || '';   // 绑定本次验证码会话
            img.src = 'data:image/png;base64,' + data.captcha_b64;
            img.style.display = 'block';
            input.value = '';
            input.focus();
            document.getElementById('captcha-input-group').style.display = 'block';
            document.getElementById('captcha-area').style.display = 'block';

            if (isWebVPN) {
                // ★ Step 1 完成：智慧理工 SSO 登录成功
                // 提示用户进入 Step 2：输入教务密码 + 验证码
                document.getElementById('sso-step-hint').style.display = 'block';
                document.getElementById('password').disabled = true;  // 锁定 SSO 密码，防止误改
                document.getElementById('jwc-password').focus();
                showToast('✅ 智慧理工登录成功！请输入教务密码和验证码', 'info');
            } else {
                showToast('✅ ' + data.message, 'info');
            }
        } else if (data.already_logged_in) {
            // 已有教务会话，无需验证码（SSO 直接完成登录）
            captchaId = '';
            setToken(data.token || '');   // 直接获得登录 token
            document.getElementById('sso-step-hint').style.display = 'none';
            resetPasswordLabel();
            showToast('✅ ' + data.message, 'success');
            loadStatus();
            loadSettings();
        } else {
            captchaId = '';
            document.getElementById('sso-step-hint').style.display = 'none';
            showToast('❌ ' + (data.message || '获取验证码失败'), 'error');
            if (loadBtn) loadBtn.style.display = 'inline-block';
        }
    } catch (e) {
        hideLoading();
        showToast('❌ 获取验证码失败: ' + e.message, 'error');
        if (loadBtn) loadBtn.style.display = 'inline-block';
    }
}

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

// 重置密码标签为默认状态
function resetPasswordLabel() {
    document.getElementById('password-label').innerHTML =
        '密码 <span id="password-saved-badge" class="badge badge-success" style="display:none;">✅ 已保存</span>';
    document.getElementById('password').placeholder = '请输入密码';
    document.getElementById('sso-step-hint').style.display = 'none';
}
