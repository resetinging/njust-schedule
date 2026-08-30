/**
 * 课表助手 · 管理控制面板
 * 实时请求监控(SSE) + 用户/会话/成绩统计
 */

const $ = (id) => document.getElementById(id);
const TOKEN_KEY = 'admin_token';
let token = localStorage.getItem(TOKEN_KEY) || '';
let es = null;
let reqCount = 0;

// ============================================================
// 通用
// ============================================================
function fmtTs(ts) { return ts; }
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function statusClass(code) {
  if (code < 300) return 's2xx';
  if (code < 400) return 's3xx';
  if (code === 401 || code === 403) return 's401';
  if (code < 500) return 's4xx';
  return 's5xx';
}
/** 成绩 → 绩点（官方 4.0 量表, 与后端/桌面端一致）; 非正式成绩返回 -1 */
const LEVEL_MAP = {
  '优': 4.0, '优秀': 4.0, '优+': 4.0, '优秀+': 4.0,
  '优-': 3.7, '优秀-': 3.7,
  '良+': 3.3, '良好+': 3.3, '良': 3.0, '良好': 3.0, '良-': 2.7, '良好-': 2.7,
  '中+': 2.3, '中等+': 2.3, '中': 2.0, '中等': 2.0, '中-': 1.5, '中等-': 1.5,
  '及格': 1.0, '通过': 1.0, '不及格': 0, '不通过': 0
};
function scoreToGp(score) {
  const s = String(score == null ? '' : score).trim();
  if (s in LEVEL_MAP) return LEVEL_MAP[s];
  if (/缓考|缺考|免修|作弊|违纪|取消|旷考|休学/.test(s)) return -1;
  const v = parseFloat(s);
  if (isNaN(v)) return -1;
  if (v >= 90) return 4.0;
  if (v >= 85) return 3.7;
  if (v >= 82) return 3.3;
  if (v >= 78) return 3.0;
  if (v >= 75) return 2.7;
  if (v >= 72) return 2.3;
  if (v >= 68) return 2.0;
  if (v >= 64) return 1.5;
  if (v >= 60) return 1.0;
  return 0;
}
/** 按学期加权平均绩点 Σ(学分×绩点)/Σ学分 */
function semesterGpa(grades) {
  const groups = {};
  (grades || []).forEach(x => {
    const k = (x.academic_year || '') + '-' + (x.semester || '');
    if (!groups[k]) groups[k] = { w: 0, c: 0 };
    const credit = parseFloat(x.credit) || 0;
    if (credit <= 0) return;
    let gp = parseFloat(x.grade_point) || 0;
    if (gp === 0) gp = scoreToGp(x.score);
    if (gp < 0) return;
    groups[k].w += credit * gp;
    groups[k].c += credit;
  });
  return Object.keys(groups).sort().reverse().map(k => {
    const g = groups[k];
    return { sem: k, gpa: g.c > 0 ? (g.w / g.c).toFixed(2) : '-', credits: g.c.toFixed(1) };
  });
}

async function api(path, opts = {}) {
  const headers = Object.assign({}, opts.headers || {});
  if (token) headers['X-Admin-Token'] = token;
  if (opts.body) headers['Content-Type'] = 'application/json';
  const res = await fetch(path, Object.assign({}, opts, { headers }));
  if (res.status === 401) { logout(); throw new Error('未授权'); }
  return res.json();
}

// ============================================================
// 登录 / 退出
// ============================================================
function show(view) {
  $('loginView').classList.toggle('hidden', view !== 'login');
  $('mainView').classList.toggle('hidden', view !== 'main');
}

async function checkLogin() {
  if (!token) { show('login'); return; }
  try {
    const r = await api('/api/admin/check');
    if (r.logged_in) { show('main'); startStream(); loadSummary(); loadUsers(); loadSessions(); loadGradeStats(); loadAnnouncement(); }
    else { logout(); }
  } catch (e) { logout(); }
}

function logout() {
  token = '';
  localStorage.removeItem(TOKEN_KEY);
  if (es) { es.close(); es = null; }
  show('login');
}

$('loginBtn').addEventListener('click', async () => {
  const pwd = $('adminPwd').value;
  $('loginErr').classList.add('hidden');
  try {
    const r = await fetch('/api/admin/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: pwd })
    }).then(res => res.json());
    if (r.success) {
      token = r.token;
      localStorage.setItem(TOKEN_KEY, token);
      show('main');
      startStream(); loadSummary(); loadUsers(); loadSessions(); loadGradeStats();
    } else {
      $('loginErr').textContent = r.message || '登录失败';
      $('loginErr').classList.remove('hidden');
    }
  } catch (e) {
    $('loginErr').textContent = '网络错误';
    $('loginErr').classList.remove('hidden');
  }
});
$('adminPwd').addEventListener('keydown', e => { if (e.key === 'Enter') $('loginBtn').click(); });
$('logoutBtn').addEventListener('click', () => { api('/api/admin/logout', { method: 'POST' }).catch(() => {}); logout(); });

// ============================================================
// SSE 实时请求流
// ============================================================
let reqBuf = [];        // 请求缓冲(全部)
let reqPaused = false;

function reqFilters() {
  return {
    status: $('fStatus').value,
    sid: $('fSid').value.trim().toLowerCase(),
    path: $('fPath').value.trim().toLowerCase()
  };
}

/** 单条请求是否通过当前筛选 */
function reqMatch(r, f) {
  if (f.status === '401' && r.status !== 401) return false;
  if (f.status === '2' && !(r.status >= 200 && r.status < 300)) return false;
  if (f.status === '4' && !(r.status >= 400 && r.status < 500)) return false;
  if (f.status === '5' && !(r.status >= 500)) return false;
  if (f.sid && !String(r.sid || '').toLowerCase().includes(f.sid)) return false;
  if (f.path && !String(r.path || '').toLowerCase().includes(f.path)) return false;
  return true;
}

/** 重渲染请求列表(按筛选) */
function renderReqs() {
  if (reqPaused) return;
  const f = reqFilters();
  const list = $('reqList');
  const matched = reqBuf.filter(r => reqMatch(r, f));
  // 统计摘要
  const total = matched.length;
  const slow = matched.filter(r => r.ms >= 2000).length;
  const err5 = matched.filter(r => r.status >= 500).length;
  $('reqStats').textContent = `匹配 ${total} 条 · 5xx ${err5} 条 · 慢请求 ${slow} 条`;
  // 渲染(上限 300 行)
  const rows = matched.slice(-300).map(reqRowHtml).join('');
  list.innerHTML = rows;
  if ($('autoScroll').checked) list.scrollTop = list.scrollHeight;
}

function reqRowHtml(r) {
  const msCls = r.ms >= 2000 ? 'ms-slow' : '';
  return `<div class="req-row">` +
    `<span class="req-id">#${r.id}</span>` +
    `<span class="req-time">${esc(fmtTs(r.ts))}</span>` +
    `<span class="req-method">${esc(r.method)}</span>` +
    `<span class="req-path">${esc(r.path)}</span>` +
    `<span class="req-status ${statusClass(r.status)}">${r.status}</span>` +
    `<span class="req-ms ${msCls}">${r.ms}ms</span>` +
    `<span class="req-sid">${esc(r.sid || '-')}</span>` +
    `<span class="req-ip">${esc(r.ip || '-')}</span>` +
    `</div>`;
}

function startStream() {
  if (es) es.close();
  const status = $('sseStatus');
  es = new EventSource('/api/admin/stream?token=' + encodeURIComponent(token));
  es.onopen = () => { status.textContent = '● 实时连接中'; status.className = 'sse-status ok'; };
  es.onerror = () => { status.textContent = '● 连接断开，重连中…'; status.className = 'sse-status warn'; };
  es.onmessage = (ev) => {
    try {
      const r = JSON.parse(ev.data);
      // 缓冲上限
      reqBuf.push(r);
      if (reqBuf.length > 800) reqBuf = reqBuf.slice(-800);
      renderReqs();
    } catch (e) {}
  };
}

$('reqClear').addEventListener('click', () => { reqBuf = []; renderReqs(); });
$('reqPause').addEventListener('click', () => {
  reqPaused = !reqPaused;
  $('reqPause').textContent = reqPaused ? '▶ 继续' : '⏸ 暂停';
  if (!reqPaused) renderReqs();
});
['fStatus', 'fSid', 'fPath'].forEach(id => {
  $(id).addEventListener('input', renderReqs);
  $(id).addEventListener('change', renderReqs);
});

// ============================================================
// 仪表盘统计
// ============================================================
async function loadSummary() {
  try {
    const r = await api('/api/admin/summary');
    if (!r.success) return;
    const up = r.uptime_sec;
    const upTxt = up >= 86400 ? Math.floor(up / 86400) + '天' + Math.floor(up % 86400 / 3600) + '时'
      : up >= 3600 ? Math.floor(up / 3600) + '时' + Math.floor(up % 3600 / 60) + '分' : up + '秒';
    $('statRow').innerHTML = `
      <div class="stat-card"><div class="num">${r.online_sessions}</div><div class="lbl">在线会话</div></div>
      <div class="stat-card"><div class="num">${r.total_users}</div><div class="lbl">累计用户</div></div>
      <div class="stat-card"><div class="num">${r.requests_total}</div><div class="lbl">本次运行请求</div></div>
      <div class="stat-card"><div class="num">${upTxt}</div><div class="lbl">运行时长</div></div>
      <div class="stat-card"><div class="num">${r.counts.courses}</div><div class="lbl">课表记录</div></div>
      <div class="stat-card"><div class="num">${r.counts.exams}</div><div class="lbl">考试记录</div></div>
      <div class="stat-card"><div class="num">${r.counts.grades}</div><div class="lbl">成绩记录</div></div>
      <div class="stat-card"><div class="num">${r.counts.evaluations}</div><div class="lbl">评教记录</div></div>`;
  } catch (e) {}
}

// ============================================================
// 用户列表
// ============================================================
let allUsersCache = [];

async function loadUsers() {
  try {
    const r = await api('/api/admin/users');
    if (!r.success) return;
    allUsersCache = r.users;
    renderUsers();
  } catch (e) {}
}

function renderUsers() {
  const kw = $('userSearch').value.trim().toLowerCase();
  const users = allUsersCache.filter(u =>
    !kw || String(u.student_id).toLowerCase().includes(kw) ||
    String(u.name || '').toLowerCase().includes(kw));
  const box = $('userList');
  box.innerHTML = '<div class="table-head user-row">' +
    '<span>学号</span><span>姓名</span><span>课表</span><span>考试</span><span>成绩</span><span>最高GPA</span><span>学期</span><span>状态</span></div>';
  users.forEach(u => {
    const row = document.createElement('div');
    row.className = 'user-row clickable';
    row.innerHTML =
      `<span class="mono">${esc(u.student_id)}</span>` +
      `<span>${esc(u.name || u.student_id)}</span>` +
      `<span>${u.courses}</span><span>${u.exams}</span><span>${u.grades}</span>` +
      `<span>${u.best_gpa != null ? u.best_gpa : '-'}</span>` +
      `<span>${esc(u.semester || '-')}</span>` +
      `<span class="badge ${u.online ? 'on' : ''}">${u.online ? '在线' : '离线'}</span>`;
    row.addEventListener('click', () => openUser(u.student_id));
    box.appendChild(row);
  });
  if (!users.length) box.innerHTML += '<p class="dim center">无匹配用户</p>';
}

$('userSearch').addEventListener('input', renderUsers);

async function openUser(sid) {
  try {
    const r = await api('/api/admin/users/' + encodeURIComponent(sid));
    if (!r.success) return;
    $('drawerTitle').textContent = '用户 ' + sid;
    const g = r.grades;
    const totalCredit = g.reduce((s, x) => s + (parseFloat(x.credit) || 0), 0);
    let best = null;
    g.forEach(x => { const gp = parseFloat(x.grade_point) || 0; if (gp > 0 && (!best || gp > best)) best = gp; });
    const semHtml = semesterGpa(g).map(x =>
      `<div class="drawer-sem"><b>${esc(x.sem)}</b> · 绩点 ${x.gpa} · ${x.credits}学分</div>`
    ).join('');
    const courseHtml = r.courses.map(c => `<div class="chip">${esc(c.name)}<i>${esc(c.semester)}</i></div>`).join('');
    $('drawerBody').innerHTML = `
      <div class="drawer-grid">
        <div class="card"><h3>概览</h3>
          <p>成绩 ${g.length} 门 · 总学分 ${totalCredit.toFixed(1)} · 最高绩点 ${best ? best.toFixed(2) : '-'}</p>
          <p>考试 ${r.exams.length} 场 · 评教批次 ${r.evaluations.length} 个</p>
        </div>
        <div class="card"><h3>各学期成绩</h3>${semHtml || '<p class="dim">无成绩</p>'}</div>
      </div>
      <div class="card"><h3>课表(${r.courses.length} 门)</h3>
        <div class="chips">${courseHtml || '<p class="dim">无课表</p>'}</div>
      </div>
      <div class="card"><h3>成绩明细</h3>
        <div class="table-head grade-row"><span>课程</span><span>分数</span><span>绩点</span><span>学分</span><span>学期</span></div>
        ${g.slice(0, 200).map(x => `<div class="grade-row"><span>${esc(x.course_name)}</span><span>${esc(x.score)}</span><span>${x.grade_point || '-'}</span><span>${x.credit || '-'}</span><span>${esc((x.academic_year||'') + '-' + (x.semester||''))}</span></div>`).join('') || '<p class="dim">无成绩</p>'}
      </div>`;
    $('drawer').classList.remove('hidden');
  } catch (e) {}
}
$('drawerClose').addEventListener('click', () => $('drawer').classList.add('hidden'));

// ============================================================
// 在线会话
// ============================================================
async function loadSessions() {
  try {
    const r = await api('/api/admin/sessions');
    if (!r.success) return;
    const box = $('sessionList');
    box.innerHTML = '<div class="table-head user-row"><span>学号</span><span>姓名</span><span>token</span><span>活跃于</span></div>';
    r.sessions.forEach(s => {
      const row = document.createElement('div');
      row.className = 'user-row';
      const act = s.active_sec < 60 ? '刚刚' : s.active_sec < 3600 ? Math.floor(s.active_sec / 60) + '分钟前' : Math.floor(s.active_sec / 3600) + '小时前';
      row.innerHTML = `<span class="mono">${esc(s.student_id)}</span><span>${esc(s.name || '-')}</span><span class="mono">${esc(s.token)}</span><span>${act}</span>`;
      box.appendChild(row);
    });
    if (!r.sessions.length) box.innerHTML += '<p class="dim center">当前无在线会话</p>';
  } catch (e) {}
}

// ============================================================
// 成绩统计
// ============================================================
function barChart(el, data, color) {
  const entries = Object.entries(data);
  const max = Math.max(1, ...entries.map(([, v]) => v));
  el.innerHTML = entries.map(([k, v]) => `
    <div class="bar-col">
      <div class="bar-val">${v}</div>
      <div class="bar" style="height:${Math.round(v / max * 120)}px;background:${color}"></div>
      <div class="bar-lbl">${esc(k)}</div>
    </div>`).join('');
}

async function loadGradeStats() {
  try {
    const [r, tr] = await Promise.all([
      api('/api/admin/stats/grades'),
      api('/api/admin/stats/requests').catch(() => null)
    ]);
    if (!r.success) return;
    barChart($('levelChart'), r.level_dist, 'linear-gradient(180deg,#8b7cf7,#6a5ae0)');
    barChart($('gpaChart'), r.gpa_hist, 'linear-gradient(180deg,#5ad0a8,#2fa882)');
    // 请求趋势(最近 60 分钟)
    if (tr && tr.success && tr.minutes) {
      const entries = Object.entries(tr.minutes);
      const max = Math.max(1, ...entries.map(([, v]) => v));
      $('reqTrendChart').innerHTML = entries.length
        ? entries.slice(-60).map(([k, v]) => `
          <div class="bar-col">
            <div class="bar-val">${v}</div>
            <div class="bar" style="height:${Math.round(v / max * 110)}px;background:linear-gradient(180deg,#7c6be8,#5ad0a8)"></div>
            <div class="bar-lbl">${esc(k)}</div>
          </div>`).join('')
        : '<p class="dim center">暂无请求数据</p>';
    }
    // 各学期平均绩点(横向条形, 0-4.0)
    const sem = $('semAvgChart');
    sem.innerHTML = r.sem_gpa.length ? r.sem_gpa.slice(0, 12).map(s => `
      <div class="sem-row">
        <span class="sem-lbl">${esc(s.sem)}</span>
        <div class="sem-track"><div class="sem-bar" style="width:${Math.min(100, Math.round(s.gpa / 4 * 100))}%"></div></div>
        <span class="sem-val">${s.gpa} <i>(${s.credits}学分)</i></span>
      </div>`).join('') : '<p class="dim center">暂无成绩数据</p>';
  } catch (e) {}
}

// ============================================================
// Tab 切换
// ============================================================
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    $('panel-' + tab.dataset.tab).classList.add('active');
  });
});

// ============================================================
// 公告管理
// ============================================================
async function loadAnnouncement() {
  try {
    const r = await api('/api/admin/announcement');
    if (!r.success) return;
    $('annText').value = r.text || '';
    $('annEnabled').checked = r.enabled;
    $('annUpdated').textContent = r.updated ? '上次修改: ' + r.updated : '';
    updateAnnCount();
  } catch (e) {}
}
function updateAnnCount() {
  $('annCount').textContent = ($('annText').value.length || 0) + ' / 500';
}
$('annText').addEventListener('input', updateAnnCount);
$('annSave').addEventListener('click', async () => {
  const text = $('annText').value.trim();
  const enabled = $('annEnabled').checked;
  const r = await api('/api/admin/announcement', {
    method: 'POST',
    body: JSON.stringify({ text, enabled })
  });
  if (r.success) {
    loadAnnouncement();
    alert('公告已保存，小程序端即时生效');
  } else {
    alert('保存失败: ' + (r.message || '未知错误'));
  }
});

// ============================================================
// 启动
// ============================================================
checkLogin();
setInterval(() => { loadSummary(); loadSessions(); }, 10000);
setInterval(loadGradeStats, 60000);   // 成绩统计+请求趋势 60s 刷新
