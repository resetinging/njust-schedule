document.addEventListener('DOMContentLoaded', async () => {
    await loadStatus();                  // main.js 共享版本
    await loadSettingsAndLoginInfo();    // 补充登录信息面板
    loadSemesters();
});

// 加载设置 + 更新登录状态面板（settings 页面特有）
async function loadSettingsAndLoginInfo() {
    try {
        const resp = await fetch('/api/status');
        const data = await resp.json();
        updateLoginInfo(data);
        await loadSettings();
    } catch (e) {
        console.error('获取状态失败:', e);
    }
}

async function loadSettings() {
    try {
        const resp = await fetch('/api/settings');
        const data = await resp.json();
        document.getElementById('student-id').value = data.student_id || '';
        document.getElementById('semester-select').value = data.semester || data.current_semester || '';
        // 显示密码保存状态
        const badge = document.getElementById('password-saved-badge');
        if (badge) {
            badge.style.display = data.has_password ? 'inline' : 'none';
        }
        updateDataStats(data);
    } catch (e) {
        console.error('加载设置失败:', e);
    }
}

async function loadSemesters() {
    try {
        const resp = await fetch('/api/settings');
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
    if (data.logged_in) {
        infoDiv.style.display = 'block';
        document.getElementById('info-status').innerHTML =
            '<span style="color:#27ae60;">● 已登录</span>';
        document.getElementById('info-student-id').textContent = data.student_id;
        document.getElementById('info-student-name').textContent =
            data.student_name || '-';
        document.getElementById('info-login-method').textContent =
            data.login_method || '未知';
        document.getElementById('btn-login').textContent = '🔄 重新登录';
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
    // 异步加载实际数量
    fetch('/api/courses').then(r => r.json()).then(d => {
        document.getElementById('stats-courses').textContent = d.count;
    });
    fetch('/api/exams').then(r => r.json()).then(d => {
        document.getElementById('stats-exams').textContent = d.count;
    });
}

// 测试连接
async function testConnection() {
    showToast('正在测试连接...', 'info');
    try {
        const resp = await fetch('/api/connect-test');
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

    if (!studentId || !password) {
        showToast('❌ 请输入学号和密码', 'error');
        return;
    }

    showLoading('正在登录教务系统...');

    // 判断用哪种登录方式
    const useCaptcha = document.getElementById('captcha-area').style.display !== 'none'
                       && captchaInput.length > 0;
    const url = useCaptcha ? '/api/login-manual' : '/api/login';
    const body = useCaptcha
        ? JSON.stringify({ student_id: studentId, password, captcha: captchaInput })
        : JSON.stringify({ student_id: studentId, password });

    document.getElementById('loading-text').textContent = useCaptcha
        ? '正在使用手动验证码登录...'
        : '正在自动识别验证码并登录，请稍候...';

    try {
        const resp = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body,
        });
        const data = await resp.json();
        hideLoading();

        if (data.success) {
            showToast('✅ ' + data.message, 'success');
            document.getElementById('password').value = '';
            document.getElementById('captcha-input').value = '';
            document.getElementById('captcha-area').style.display = 'none';
            loadStatus();
            loadSettings();
        } else {
            showToast('❌ ' + data.message, 'error');
            // 如果提示验证码相关，自动展开手动验证码区域
            if (data.need_captcha || data.message.includes('验证码')) {
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

    try {
        const resp = await fetch('/api/semester', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ semester }),
        });
        const data = await resp.json();
        showToast(data.success ? '✅ ' + data.message : '❌ ' + data.message,
                  data.success ? 'success' : 'error');
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
        const resp = await fetch('/api/refresh-all', { method: 'POST' });
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
        const resp = await fetch('/api/clear-data', { method: 'POST' });
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

    img.style.display = 'none';
    if (loadBtn) loadBtn.style.display = 'none';

    try {
        const resp = await fetch('/api/get-captcha');
        const data = await resp.json();

        if (data.success && data.captcha_b64) {
            img.src = 'data:image/png;base64,' + data.captcha_b64;
            img.style.display = 'block';
            input.value = '';
            input.focus();
            document.getElementById('captcha-input-group').style.display = 'block';
            showToast('✅ ' + data.message, 'info');
        } else {
            showToast('❌ ' + (data.message || '获取验证码失败'), 'error');
            if (loadBtn) loadBtn.style.display = 'inline-block';
        }
    } catch (e) {
        showToast('❌ 获取验证码失败: ' + e.message, 'error');
        if (loadBtn) loadBtn.style.display = 'inline-block';
    }
}
