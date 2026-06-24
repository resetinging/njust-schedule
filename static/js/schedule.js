/* ============================================================
   南理工课表管理系统 - 课表页面逻辑
   ============================================================ */

// NJUST 大节定义：标签、包含的小节、时间范围
const BIG_PERIODS = [
    { label: '第一大节', periods: [1,2,3], time: '08:00-10:25', cssClass: 'morning' },
    { label: '第二大节', periods: [4,5],   time: '10:40-12:15', cssClass: 'morning' },
    { label: '中午',     periods: [14],    time: '12:30-13:15', cssClass: 'noon' },
    { label: '第三大节', periods: [6,7],   time: '14:00-15:35', cssClass: 'afternoon' },
    { label: '第四大节', periods: [8,9,10],time: '15:50-18:15', cssClass: 'afternoon' },
    { label: '第五大节', periods: [11,12,13],time:'19:00-21:25', cssClass: 'evening' },
];
const DAY_NAMES = ['', '周一', '周二', '周三', '周四', '周五', '周六', '周日'];

let currentWeek = 1; // 默认显示第1周

let allCourses = [];
let currentSemester = '';

// 页面加载
document.addEventListener('DOMContentLoaded', () => {
    loadStatus();
    loadSchedule();
});

async function loadStatus() {
    try {
        const resp = await fetch('/api/status');
        const data = await resp.json();
        currentSemester = data.semester;
        document.getElementById('semester-badge').textContent = data.semester;
        updateNavStatus(data);
    } catch (e) {
        console.error('获取状态失败:', e);
    }
}

async function loadSchedule() {
    showLoading('正在加载课表...');
    try {
        const resp = await fetch('/api/courses');
        const data = await resp.json();
        allCourses = data.courses || [];
        currentSemester = data.semester;
        document.getElementById('semester-badge').textContent = data.semester;

        if (allCourses.length === 0) {
            document.getElementById('schedule-empty').style.display = 'flex';
            document.getElementById('schedule-table-wrapper').style.display = 'none';
            document.getElementById('schedule-list').style.display = 'none';
            document.getElementById('empty-message').textContent =
                '请先在「设置」页面登录教务系统，然后点击「刷新课表」';
        } else {
            document.getElementById('schedule-empty').style.display = 'none';
            document.getElementById('schedule-table-wrapper').style.display = 'block';
            document.getElementById('schedule-list').style.display = 'none';
            renderTable(allCourses);
            renderListView(allCourses);
        }
    } catch (e) {
        console.error('加载课表失败:', e);
        document.getElementById('empty-message').textContent = '加载失败: ' + e.message;
        document.getElementById('schedule-empty').style.display = 'flex';
        document.getElementById('schedule-table-wrapper').style.display = 'none';
    } finally {
        hideLoading();
    }
}

function renderTable(courses) {
    const tbody = document.getElementById('schedule-body');
    tbody.innerHTML = '';

    for (const bp of BIG_PERIODS) {
        const tr = document.createElement('tr');
        tr.className = `big-period-row ${bp.cssClass}`;

        // 节次标签列
        const tdTime = document.createElement('td');
        tdTime.className = 'time-col';
        tdTime.innerHTML = `<div class="period-num">${bp.label}</div><div class="period-time">${bp.time}</div>`;
        tr.appendChild(tdTime);

        // 单元格高度：每小节 72px
        const cellHeight = bp.periods.length * 72;
        const totalPeriods = bp.periods.length;

        // 每天一列
        for (let d = 1; d <= 7; d++) {
            const td = document.createElement('td');
            td.className = 'course-cell';

            // 内部固定高度容器，避免 td 被表格算法撑开
            const inner = document.createElement('div');
            inner.className = 'cell-inner';
            inner.style.height = cellHeight + 'px';

            // 找出属于此大节、此天的课程
            const cellCourses = courses.filter(c => {
                if (c.day !== d) return false;
                return c.start <= bp.periods[totalPeriods-1] && c.end >= bp.periods[0];
            });

            // 过滤当前周不上的课
            const visibleCourses = cellCourses.filter(c => {
                const wi = parseWeeks(c.weeks);
                return isWeekInRange(currentWeek, wi, c.week_type);
            });

            for (const course of visibleCourses) {
                const div = document.createElement('div');
                div.className = `course-block type-${(course.week_type || 0)}`;

                // 按课程占小节数的比例分配高度
                const overlapStart = Math.max(course.start, bp.periods[0]);
                const overlapEnd = Math.min(course.end, bp.periods[totalPeriods-1]);
                const overlapCount = overlapEnd - overlapStart + 1;
                const heightPct = (overlapCount / totalPeriods) * 100;
                div.style.height = heightPct + '%';
                div.style.flexShrink = '0';

                div.innerHTML = `
                    <div class="course-name">${course.name}</div>
                    <div class="course-detail">${course.teacher ? '👨‍🏫 ' + course.teacher : ''}</div>
                    <div class="course-detail">${course.classroom ? '📍 ' + course.classroom : ''}</div>
                    <div class="course-weeks">${course.weeks ? '📅 ' + course.weeks : ''}</div>
                    <div class="course-periods">⏰ ${course.start}-${course.end}节</div>
                `;

                inner.appendChild(div);
            }

            if (visibleCourses.length === 0) {
                inner.innerHTML = '<div class="empty-cell"></div>';
            }
            td.appendChild(inner);
            tr.appendChild(td);
        }
        tbody.appendChild(tr);
    }
}

function renderListView(courses) {
    const listContainer = document.getElementById('schedule-list');
    listContainer.innerHTML = '<h3 class="list-title">📋 课程列表</h3>';

    for (let d = 1; d <= 7; d++) {
        const dayCourses = courses.filter(c => c.day === d);
        if (dayCourses.length === 0) continue;

        const dayGroup = document.createElement('div');
        dayGroup.className = 'day-group';
        dayGroup.innerHTML = `<h4 class="day-title">${DAY_NAMES[d]}</h4>`;

        // 去重（同一课程占据多个节次只显示一次）
        const seen = new Set();
        const unique = [];
        for (const c of dayCourses) {
            const key = `${c.name}-${c.start}-${c.end}`;
            if (!seen.has(key)) {
                seen.add(key);
                unique.push(c);
            }
        }
        unique.sort((a, b) => a.start - b.start);

        for (const course of unique) {
            const wi = parseWeeks(course.weeks);
            if (!isWeekInRange(currentWeek, wi, course.week_type)) continue;

            const card = document.createElement('div');
            card.className = `course-card type-${(course.week_type || 0)}`;
            card.innerHTML = `
                <div class="course-card-header">
                    <span class="course-card-name">${course.name}</span>
                    <span class="course-card-time">${course.start}-${course.end}节</span>
                </div>
                <div class="course-card-body">
                    <span>👨‍🏫 ${course.teacher || '未知'}</span>
                    <span>📍 ${course.classroom || '未知'}</span>
                </div>
                <div class="course-card-footer">
                    <span>📅 ${course.weeks || '待定'}</span>
                    ${course.week_type === 1 ? '<span class="badge">单周</span>' : ''}
                    ${course.week_type === 2 ? '<span class="badge">双周</span>' : ''}
                </div>
            `;
            dayGroup.appendChild(card);
        }
        listContainer.appendChild(dayGroup);
    }
}

function parseWeeks(weeksStr) {
    if (!weeksStr) return [];
    const result = [];
    const parts = weeksStr.split(',');
    for (const part of parts) {
        const range = part.split('-');
        if (range.length === 2) {
            const start = parseInt(range[0]);
            const end = parseInt(range[1]);
            if (!isNaN(start) && !isNaN(end)) {
                for (let i = start; i <= end; i++) result.push(i);
            }
        } else {
            const n = parseInt(part);
            if (!isNaN(n)) result.push(n);
        }
    }
    return result;
}

function isWeekInRange(week, weekList, weekType) {
    if (weekList.length === 0) return true;
    const inList = weekList.includes(week);
    if (weekType === 1) return inList && week % 2 === 1;
    if (weekType === 2) return inList && week % 2 === 0;
    return inList;
}

function prevWeek() {
    if (currentWeek > 1) currentWeek--;
    updateWeekLabel();
    renderTable(allCourses);
}

function nextWeek() {
    if (currentWeek < 20) currentWeek++;
    updateWeekLabel();
    renderTable(allCourses);
}

function updateWeekLabel() {
    document.getElementById('week-label').textContent = `第 ${currentWeek} 周`;
}

async function refreshSchedule() {
    showLoading('正在从教务系统获取课表...');
    document.getElementById('loading-text').textContent =
        '正在连接教务系统，可能需要十几秒钟...';

    try {
        const resp = await fetch('/api/refresh-schedule', { method: 'POST' });
        const data = await resp.json();
        hideLoading();

        if (data.success) {
            showToast(`✅ ${data.message}`, 'success');
            await loadSchedule();
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
