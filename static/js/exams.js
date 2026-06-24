let allExams = [];
let currentSemester = '';
let isLoggedIn = false;

document.addEventListener('DOMContentLoaded', () => {
    loadStatus();
    loadExams();
});

// 日期解析：兼容多种格式 "2024-01-15" "2024年01月15日" "2024/01/15"
// 使用本地时间解析，避免 UTC 时区偏移导致天数差一天
function parseDate(str) {
    if (!str) return null;
    const cleaned = str.replace(/[年月]/g, '-').replace(/[日号]/g, '').replace(/\//g, '-').trim();
    const m = cleaned.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
    if (m) {
        return new Date(parseInt(m[1]), parseInt(m[2]) - 1, parseInt(m[3]));
    }
    const d = new Date(cleaned);
    if (!isNaN(d.getTime())) return d;
    return null;
}

// 从考试时间字符串中提取开始时间 "15:50~17:50" → "15:50"
function parseStartTime(timeStr) {
    if (!timeStr) return null;
    const m = timeStr.match(/(\d{1,2}):(\d{2})/);
    if (m) return { hour: parseInt(m[1]), minute: parseInt(m[2]) };
    return null;
}

// 获取考试的精确开始时间（Date 对象）
function getExamDateTime(exam) {
    const d = parseDate(exam.date);
    if (!d) return null;
    const t = parseStartTime(exam.time);
    if (t) {
        d.setHours(t.hour, t.minute, 0, 0);
    }
    return d;
}

// 计算距现在的可读时间差
function timeUntil(targetDate) {
    const now = new Date();
    const diffMs = targetDate - now;
    const totalHours = diffMs / (1000 * 60 * 60);
    const totalDays = Math.floor(totalHours / 24);
    const remainHours = Math.floor(totalHours % 24);

    if (totalHours < 0) {
        // 已结束
        const pastHours = Math.abs(totalHours);
        if (pastHours < 1) return { text: '刚刚结束', cls: 'done' };
        if (pastHours < 24) return { text: `${Math.floor(pastHours)}小时前`, cls: 'done' };
        return { text: `${Math.floor(pastHours / 24)}天前`, cls: 'done' };
    }
    if (totalHours < 1) {
        const mins = Math.floor(totalHours * 60);
        return { text: `还有 ${mins} 分钟`, cls: 'urgent' };
    }
    if (totalHours < 24) {
        return { text: `还有 ${Math.floor(totalHours)} 小时`, cls: 'urgent' };
    }
    if (totalDays <= 3) {
        return { text: `还有 ${totalDays}天${remainHours}小时`, cls: 'urgent' };
    }
    if (totalDays <= 7) {
        return { text: `还有 ${totalDays}天${remainHours}小时`, cls: 'warning' };
    }
    return { text: `还有 ${totalDays} 天`, cls: '' };
}

// 格式化日期为统一显示格式
function formatDate(str) {
    const d = parseDate(str);
    if (!d) return str || '日期待定';
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
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

async function loadExams() {
    showLoading('正在加载考试安排...');
    try {
        const resp = await fetch('/api/exams');
        const data = await resp.json();
        allExams = data.exams || [];
        currentSemester = data.semester;
        document.getElementById('semester-badge').textContent = data.semester;

        if (allExams.length === 0) {
            document.getElementById('exam-empty').style.display = 'flex';
            document.getElementById('exam-list').style.display = 'none';
            document.getElementById('countdown-row').style.display = 'none';
            // 根据登录状态显示不同提示
            if (isLoggedIn) {
                document.getElementById('empty-exam-message').textContent =
                    '本学期暂无考试安排，或请点击「刷新考试安排」从教务系统获取最新数据';
            } else {
                document.getElementById('empty-exam-message').textContent =
                    '请先在「设置」页面登录教务系统，然后刷新考试安排';
                document.getElementById('exam-empty').querySelector('.btn-primary').style.display = 'inline-flex';
            }
        } else {
            document.getElementById('exam-empty').style.display = 'none';
            document.getElementById('exam-list').style.display = 'block';
            document.getElementById('countdown-row').style.display = 'flex';
            renderExams(allExams);
            renderCountdown(allExams);
        }
    } catch (e) {
        console.error('加载考试失败:', e);
        document.getElementById('empty-exam-message').textContent = '加载失败: ' + e.message;
        document.getElementById('exam-empty').style.display = 'flex';
        document.getElementById('exam-list').style.display = 'none';
    } finally {
        hideLoading();
    }
}

function renderExams(exams) {
    const container = document.getElementById('exam-list');
    container.innerHTML = '';

    // 按日期分组
    const grouped = {};
    for (const exam of exams) {
        const date = formatDate(exam.date) || '日期待定';
        if (!grouped[date]) grouped[date] = [];
        grouped[date].push(exam);
    }

    // 同一天内按时间排序
    for (const date of Object.keys(grouped)) {
        grouped[date].sort((a, b) => (a.time || '').localeCompare(b.time || ''));
    }

    // 日期排序
    const sortedDates = Object.keys(grouped).sort((a, b) => {
        if (a === '日期待定') return 1;
        if (b === '日期待定') return -1;
        return a.localeCompare(b);
    });

    for (const date of sortedDates) {
        const group = grouped[date];
        const dayDiv = document.createElement('div');
        dayDiv.className = 'exam-day-group';

        // 计算距考试精确时间
        let daysUntil = '';
        if (date !== '日期待定') {
            // 取当天第一场考试的开始时间
            const firstExam = group[0];
            const examDT = getExamDateTime(firstExam);
            if (examDT) {
                const info = timeUntil(examDT);
                const badgeCls = `badge${info.cls ? ' badge-' + info.cls : ''}`;
                daysUntil = `<span class="${badgeCls}">${info.text}</span>`;
            }
        }

        const weekDay = date !== '日期待定' ? ['日','一','二','三','四','五','六'][parseDate(date)?.getDay()] : '';

        dayDiv.innerHTML = `
            <div class="exam-date-header">
                <h3>📅 ${date} ${weekDay ? '周' + weekDay : ''}</h3>
                ${daysUntil}
            </div>
        `;

        for (const exam of group) {
            const card = document.createElement('div');
            card.className = 'exam-card';
            card.innerHTML = `
                <div class="exam-course-name">📖 ${exam.course_name}</div>
                <div class="exam-info-row">
                    <span>⏰ ${exam.time || '时间待定'}</span>
                    <span>📍 ${exam.location || '地点待定'}</span>
                    <span>💺 ${exam.seat || '座位待定'}</span>
                    <span>📋 ${exam.type || '期末考试'}</span>
                </div>
            `;
            dayDiv.appendChild(card);
        }

        container.appendChild(dayDiv);
    }
}

function renderCountdown(exams) {
    const row = document.getElementById('countdown-row');
    row.innerHTML = '';

    // 按精确考试时间排序，未结束的优先
    const now = new Date();
    const withDT = exams
        .filter(e => e.date && e.date !== '日期待定')
        .map(e => ({ exam: e, dt: getExamDateTime(e) }))
        .filter(x => x.dt);

    const future = withDT.filter(x => x.dt >= now).sort((a, b) => a.dt - b.dt);
    const past = withDT.filter(x => x.dt < now).sort((a, b) => b.dt - a.dt);
    const display = [...future, ...past].slice(0, 3);

    for (const { exam, dt } of display) {
        const info = timeUntil(dt);
        const totalHours = (dt - now) / (1000 * 60 * 60);

        let cardClass = 'countdown-card';
        if (info.cls === 'done') cardClass += ' done';
        else if (totalHours <= 72) cardClass += ' urgent';  // 3天内
        else if (totalHours <= 168) cardClass += ' warning'; // 7天内

        // 倒计时大数字
        let bigNum, bigLabel;
        if (totalHours < 0) {
            bigNum = '✓'; bigLabel = '已结束';
        } else if (totalHours < 24) {
            bigNum = Math.floor(totalHours);
            bigLabel = '小时后';
        } else {
            bigNum = Math.floor(totalHours / 24);
            bigLabel = '天后';
        }

        const card = document.createElement('div');
        card.className = cardClass;
        card.innerHTML = `
            <div class="countdown-days">${bigNum}</div>
            <div class="countdown-label">${bigLabel}</div>
            <div class="countdown-course">${exam.course_name}</div>
            <div class="countdown-date">${formatDate(exam.date)} ${exam.time || ''}</div>
        `;
        row.appendChild(card);
    }

    if (display.length === 0) {
        row.style.display = 'none';
    }
}

async function refreshExams() {
    showLoading('正在从教务系统获取考试安排...');
    document.getElementById('loading-text').textContent =
        '正在连接教务系统，可能需要十几秒钟...';

    try {
        const resp = await fetch('/api/refresh-exams', { method: 'POST' });
        const data = await resp.json();
        hideLoading();

        if (data.success) {
            showToast(`✅ ${data.message}`, 'success');
            await loadExams();
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
