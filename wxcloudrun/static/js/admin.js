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
/** 成绩 → 百分制数值(等级制折算中值, 与后端/小程序一致); 无法识别返回 null */
function scoreNum(s) {
  const t = String(s == null ? '' : s).trim();
  if (!t) return null;
  if (/^-?\d+(\.\d+)?$/.test(t)) return parseFloat(t);
  if (/不及格|不通过|未通过/.test(t)) return 55;
  if (/优/.test(t)) return 95;
  if (/良/.test(t)) return 85;
  if (/中/.test(t)) return 75;
  if (/及格|通过/.test(t)) return 65;
  return null;
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
    if (r.logged_in) { show('main'); startStream(); loadSummary(); loadUsers(); loadSessions(); loadGradeStats(); }
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
function startStream() {
  if (es) es.close();
  const status = $('sseStatus');
  es = new EventSource('/api/admin/stream?token=' + encodeURIComponent(token));
  es.onopen = () => { status.textContent = '● 实时连接中'; status.className = 'sse-status ok'; };
  es.onerror = () => { status.textContent = '● 连接断开，重连中…'; status.className = 'sse-status warn'; };
  es.onmessage = (ev) => {
    try { appendReq(JSON.parse(ev.data)); } catch (e) {}
  };
}

function appendReq(r) {
  const list = $('reqList');
  // 列表上限
  while (list.children.length >= 500) list.removeChild(list.firstChild);
  const row = document.createElement('div');
  row.className = 'req-row';
  const msCls = r.ms >= 2000 ? 'ms-slow' : '';
  row.innerHTML =
    `<span class="req-id">#${r.id}</span>` +
    `<span class="req-time">${esc(fmtTs(r.ts))}</span>` +
    `<span class="req-method">${esc(r.method)}</span>` +
    `<span class="req-path">${esc(r.path)}</span>` +
    `<span class="req-status ${statusClass(r.status)}">${r.status}</span>` +
    `<span class="req-ms ${msCls}">${r.ms}ms</span>` +
    `<span class="req-sid">${esc(r.sid || '-')}</span>` +
    `<span class="req-ip">${esc(r.ip || '-')}</span>`;
  list.appendChild(row);
  reqCount++;
  if ($('autoScroll').checked) list.scrollTop = list.scrollHeight;
}

$('reqClear').addEventListener('click', () => { $('reqList').innerHTML = ''; });

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
async function loadUsers() {
  try {
    const r = await api('/api/admin/users');
    if (!r.success) return;
    const box = $('userList');
    box.innerHTML = '<div class="table-head user-row">' +
      '<span>学号</span><span>姓名</span><span>课表</span><span>考试</span><span>成绩</span><span>最高GPA</span><span>学期</span><span>状态</span></div>';
    r.users.forEach(u => {
      const row = document.createElement('div');
      row.className = 'user-row clickable';
      row.innerHTML =
        `<span class="mono">${esc(u.student_id)}</span>` +
        `<span>${esc(u.name || '-')}</span>` +
        `<span>${u.courses}</span><span>${u.exams}</span><span>${u.grades}</span>` +
        `<span>${u.best_gpa != null ? u.best_gpa : '-'}</span>` +
        `<span>${esc(u.semester || '-')}</span>` +
        `<span class="badge ${u.online ? 'on' : ''}">${u.online ? '在线' : '离线'}</span>`;
      row.addEventListener('click', () => openUser(u.student_id));
      box.appendChild(row);
    });
  } catch (e) {}
}

async function openUser(sid) {
  try {
    const r = await api('/api/admin/users/' + encodeURIComponent(sid));
    if (!r.success) return;
    $('drawerTitle').textContent = '用户 ' + sid;
    const g = r.grades;
    const totalCredit = g.reduce((s, x) => s + (parseFloat(x.credit) || 0), 0);
    let best = null;
    g.forEach(x => { const gp = parseFloat(x.grade_point) || 0; if (gp > 0 && (!best || gp > best)) best = gp; });
    const semMap = {};
    g.forEach(x => { const k = (x.academic_year || '') + '-' + (x.semester || ''); if (!semMap[k]) semMap[k] = []; semMap[k].push(x); });
    const semHtml = Object.keys(semMap).sort().reverse().map(k => {
      const arr = semMap[k];
      const scored = arr.map(x => scoreNum(x.score)).filter(v => v != null);
      const n = scored.length;
      const avg = n ? (scored.reduce((a, b) => a + b, 0) / n).toFixed(1) : '-';
      return `<div class="drawer-sem"><b>${esc(k)}</b> · ${arr.length}门 · 均分 ${avg}</div>`;
    }).join('');
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
    const r = await api('/api/admin/stats/grades');
    if (!r.success) return;
    barChart($('levelChart'), r.level_dist, 'linear-gradient(180deg,#8b7cf7,#6a5ae0)');
    barChart($('gpaChart'), r.gpa_hist, 'linear-gradient(180deg,#5ad0a8,#2fa882)');
    // 各学期均分(横向条形)
    const sem = $('semAvgChart');
    const max = Math.max(1, ...r.sem_avg.map(s => s.avg));
    sem.innerHTML = r.sem_avg.length ? r.sem_avg.slice(0, 12).map(s => `
      <div class="sem-row">
        <span class="sem-lbl">${esc(s.sem)}</span>
        <div class="sem-track"><div class="sem-bar" style="width:${Math.round(s.avg / max * 100)}%"></div></div>
        <span class="sem-val">${s.avg} <i>(${s.count}门)</i></span>
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
// 启动
// ============================================================
checkLogin();
setInterval(() => { loadSummary(); loadSessions(); }, 10000);
