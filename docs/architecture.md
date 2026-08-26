# 小程序前后端职责说明

> 本文档说明「南理工课表管理系统」中**微信小程序前端**与**云托管 Flask 后端**各自的职责范围、模块划分与协作契约。
>
> - 后端仓库:`njust-schedule`(本仓库,部署于微信云托管)
> - 小程序仓库:`C:\Users\a\Documents\local\miniprogram`(微信开发者工具管理)

## 一、总览

```
┌─────────────────────┐   wx.cloud.callContainer   ┌──────────────────────────┐
│   微信小程序(前端)    │ ─────────────────────────→ │   云托管 Flask 后端       │
│                     │   (云托管内网,免域名白名单)   │                          │
│  pages/ 5个tab+校历页 │ ←───────────────────────── │  views.py 全部 /api/*    │
│  components/ 3个组件  │        JSON 响应           │  jwc_client.py 教务爬虫   │
│  utils/ api/storage  │                            │  dao.py + MySQL          │
└─────────────────────┘                            │  gpa.py 绩点计算          │
                                                    └──────────┬───────────────┘
                                                               │ requests + BeautifulSoup
                                                               ▼
                                                ┌──────────────────────────┐
                                                │ 南理工教务系统(强智)       │
                                                │ 202.119.81.112:9080 /     │
                                                │ 202.119.81.113:8080 /     │
                                                │ ids.njust.edu.cn(SSO)     │
                                                └──────────────────────────┘
```

**核心原则**:小程序只做「展示与交互」,后端做「与教务系统打交道的一切脏活」。
小程序不直连教务系统、不存密码;后端不保存小程序的界面状态。

---

## 二、后端职责(`njust-schedule` 仓库)

### 1. 教务系统对接 — `wxcloudrun/jwc_client.py`

| 职责 | 说明 |
|---|---|
| 会话与 Cookie 管理 | 自定义 `_DedupCookieJar` 解决教务返回重复 `JSESSIONID` 导致的崩溃;按 (domain, path) 去重,保留跨服务器 Cookie |
| 登录(3 种方式) | ① 教务直连自动 OCR(`ddddocr`,5 次重试 + 图片预处理);② 教务直连手动验证码;③ 智慧理工 SSO 两步(直连 SSO 表单 + AES-128-CBC 密码加密 + CAS ticket 尝试 + 8080 标准流程兜底) |
| 会话保活 | **多用户**:每个登录用户持有独立 `JWCClient` 实例(独立教务会话/Cookie),登录签发随机 token,请求经 `X-Auth-Token` 头识别;`is_session_valid()` 轻量探测;仅支持手动登录,会话过期/容器重启后需重新登录 |
| 课表抓取 | API(`app.do?method=getKbcxAzc`)优先,降级 HTML:`#kbtable`(周次/教室/教师,从 `font[title]` 提取)与 `#dataList`(精确小节/学分)双表合并 |
| 考试抓取 | 查询页表单提交 → `#dataList` 解析,含 3 个降级策略(表单 POST / 直接 POST / GET) |
| 评教抓取 | 批次列表(`.Nsb_r_list`)、课程列表(`#dataList` + `openWindow` 链接)、评价表单(`#table1` 指标 + `pj0601fz_*` 分值 + radio 选项) |
| 成绩抓取 | `app.do?method=getCjcx` API 优先,降级 HTML(表头列名映射 + 强智常见布局兜底) |
| 四六级抓取 | `djkscj_list` 页面解析,取 CET4/CET6 各自最高分 |
| 连通性 | `test_connection()` / 登录重定向链诊断日志(`debug_log`,登录失败时随接口返回) |

### 2. HTTP API — `wxcloudrun/views.py`

按功能分组:

| 分组 | 接口 | 说明 |
|---|---|---|
| 状态 | `GET /api/status` | 登录态、学号/姓名、学期、数据统计、第一周日期 |
| 登录 | `POST /api/login` | 教务直连自动 OCR |
| | `POST /api/login-manual` | 教务直连手动验证码 |
| | `GET /api/get-captcha` | 验证码图片(base64 + mime) |
| | `POST /api/get-webvpn-captcha` | 智慧理工 Step 1:SSO 登录 → 教务验证码 |
| | `POST /api/login-webvpn-manual` | 智慧理工 Step 2:验证码完成教务登录 |
| | `POST /api/login-webvpn` | 智慧理工全自动(含教务 OCR) |
| 数据刷新 | `POST /api/refresh-schedule` / `refresh-exams` / `refresh-all` | 从教务拉取课表/考试/全部 |
| | `POST /api/refresh-grades` / `refresh-cet` / `refresh-evaluations` | 拉取成绩/四六级/评教批次 |
| 数据查询 | `GET /api/courses` / `exams` / `grades` / `cet-scores` / `evaluations` | 读 MySQL 缓存的数据;**只返回原始数据,不做业务计算**(GPA/折算由前端算) |
| 评教操作 | `GET /api/eval-courses` / `eval-form` | 解析批次课程列表 / 单课评价表单(解析属网关层,评分由前端算) |
| | `POST /api/submit-eval` | 单门保存/提交中转(参数按浏览器原生顺序重建) |
| 网关 | `POST /api/jw-proxy` | 通用教务网关:用已登录会话转发任意 9080 GET/POST,返回原始内容 |
| 设置 | `GET/POST /api/settings`、`POST /api/semester`、`POST /api/clear-data` | 设置读写、学期切换、清数据 |
| 校历 | `GET /api/gallery-images` / `gallery-image?name=` | 图片文件名列表 / 单张 base64(带路径穿越防护) |
| 其他 | `GET /api/connect-test`、`GET/POST /proxy/jw/*` | 连通测试、教务页面反向代理(评教用) |

### 3. 数据存储 — `wxcloudrun/model.py` + `dao.py`

| 表 | 内容 |
|---|---|
| `courses` / `exams` | 课表、考试(按学期先删后插,**按 student_id 隔离**) |
| `evaluations` | 评教批次(items 存 JSON,**按 student_id 隔离**) |
| `grades` / `cet_scores` | 成绩(按学年学期)、四六级(全量替换,查询时取最高,**按 student_id 隔离**) |
| `settings` | 全局键值(校历日期/自动刷新等);用户级设置以 `{student_id}:{key}` 前缀存储(如学期切换) |

- **密码安全**:登录密码**不落库**——仅用于当次登录流程;无任何自动登录机制,数据库不保存明文/加密密码。历史版本遗留的 `password_enc` / `secret_key` 数据无读取入口,可忽略
- 小程序本地**不保存密码**

### 4. 业务计算(方案 A:全部在前端)

| 模块 | 位置 | 职责 |
|---|---|---|
| GPA/绩点 | 小程序 `utils/gpa.js`、Web 无成绩页 | NJUST 4.0 绩点换算、学期/总加权 GPA、通识选修过滤、非正式成绩排除、CET 折算、保研模式(CET 替换英语模块 8 学分)——从服务端 `gpa.py` 移植 |
| 评教自动评分 | 小程序 `eval.js:_computeAutoFill`、Web `evaluations.js:computeAutoFillSelection` | 贪心分配 + 防"全同列" + 单指标微调,生成 `{seq: value}` |
| 批量评教 | 小程序/Web 前端顺序 async 循环 | 逐门课「取表单 → 前端评分 → 提交」,直接更新进度 UI;后端不再有后台线程 |

### 5. 静态与 Web 服务(附带)

- 校历图片托管(`static/gallery/`)
- 桌面网页版(课表/考试/评教/校历/设置页 + PWA)——小程序之外的另一套前端,与小程序共用同一套 API

---

## 三、小程序前端职责(`miniprogram` 仓库)

### 1. 页面(`pages/`,5 个 tab + 1 个子页面)

| 页面 | 职责 |
|---|---|
| `schedule` 课表 | 周网格(`week-grid` 组件)与列表双视图;周次前后切换;单双周过滤;日期行 + 今日列高亮;按学期第一周周一自动定位当前周;学期切换;下拉刷新;课程详情弹窗 |
| `exams` 考试 | 倒计时卡片(最近 3 场,按紧迫度着色);按日期分组列表;下拉刷新 |
| `eval` 评教 | 批次列表(倒计时/紧迫度);批次 → 课程列表;评价表单(radio 勾选、实时总分、**前端自动评分算法**);保存/提交;**一键批量评教由前端顺序循环执行**(实时更新进度弹窗,非轮询) |
| `grades` 成绩 | GPA 大卡片 + 统计(**全部由前端 `utils/gpa.js` 计算**);各学期绩点列表(点击切换学期);成绩明细;保研模式切换;四六级折叠展示与刷新 |
| `settings` 我的 | 登录(模式切换:教务直连 / 智慧理工两步);第一周周一日期设置;校历入口;一键刷新;清缓存;退出登录 |
| `gallery` 校历 | 校历/地图图片列表(base64 加载),点击全屏预览(`wx.previewImage`) |

### 2. 组件(`components/`)

| 组件 | 职责 |
|---|---|
| `week-grid` | 大节行 × 7 天网格,按重叠小节数计算课程块高度,课程颜色 djb2 hash,单双周角标 |
| `captcha-input` | 验证码图片 + 输入框 + 刷新按钮 |
| `loading-modal` | 加载/进度弹窗(属性:`visible/title/message/showProgress/percent/done`) |

### 3. 工具(`utils/`)

| 模块 | 职责 |
|---|---|
| `api.js` | 全部后端接口的封装,统一走 `wx.cloud.callContainer`(云托管内网);非 200 统一包装为 `{success:false,message}` |
| `storage.js` | 本地缓存:学号/姓名/学期、课程/考试/成绩缓存 + 时间戳 TTL;登录态 = 本地有学号(后端无 token 校验) |
| `date.js` | 教学周计算、`weeks` 字符串范围判断("1-16"/"1-8,10-17"/离散)、倒计时文案 |
| `gpa.js` | **GPA 业务计算**(方案 A 新增):绩点换算、学期/总 GPA、CET 折算、保研模式 —— 服务端 `gpa.py` 的 JS 移植 |
| `config.js` | 云环境 ID/服务名、请求超时(30s) |

### 4. 本地状态管理

- `app.js` globalData:登录态、姓名、学期;启动时从本地缓存恢复(以学号为准)
- 缓存优先:页面先渲染本地缓存,再异步刷新服务端数据
- 登录态变化仅影响本地 UI;真正鉴权由后端会话决定(小程序感知不到,失败时后端返回错误信息)

---

## 四、前后端协作契约

### 请求约定

- 小程序 → 后端:JSON body(POST)/ query 参数(GET),经 `wx.cloud.callContainer` 走云托管内网
- 响应统一:`{"success": bool, "message": str, ...业务字段}`;错误码 400/401/403/404/500
- 小程序侧把非 200 状态包装为 `{success:false, message:"服务器错误 xxx"}`

### 关键字段约定

| 数据 | 字段 |
|---|---|
| 课程 | `name, teacher, classroom, day(1-7), start, end, weeks("1-16"等), week_type(0全/1单/2双), credits, course_type` |
| 考试 | `course_name, date, time, location, seat, type` |
| 评教批次 | `semester, category, batch, start_date, end_date, is_done, items[{name,url}]` |
| 评教课程 | `seq, code, name, teacher, score, evaluated, submitted, eval_url` |
| 评价指标 | `seq, label, options[{name,value,label,score,checked}]` |
| 自动评分 | 纯前端计算:输入 `indicators + target_score`,输出 `{selections:{seq:radio_value}, total}`(小程序 `eval.js` / Web `evaluations.js`) |
| 批量评教 | 前端顺序循环:逐门 `GET /api/eval-form` → 前端评分 → `POST /api/submit-eval`,进度直接渲染在本地 UI |
| 成绩 | 原始数据 `academic_year, semester, course_code, course_name, score, credit, grade_point, course_type, course_nature, exam_type`;**GPA/学期汇总/保研折算由前端 `utils/gpa.js` 计算** |
| 四六级 | 原始数据 `{type:"CET4"/"CET6", score, exam_date}`;折算百分制由前端计算 |
| 登录 | 成功响应 `{success, student_name, semester, login_method}` |
| 图片 | 验证码/校历图:`{..._b64, ..._mime}` → 前端拼 `data:<mime>;base64,<b64>` |
| 网关 | `POST /api/jw-proxy` 请求 `{method, path, query, data}` → 响应 `{status, content_type, text 或 data_b64}` |

### 边界约定(方案 A)

- **小程序/Web 前端做**:业务计算(GPA/绩点、评教自动评分、批量评教循环)、展示与交互、本地缓存、周次/倒计时
- **后端只做**:与教务系统通信(登录/OCR/SSO)、页面抓取与解析(网关层)、评教提交中转、设置与凭据存储
- **小程序不做**:教务爬取(域名白名单限制)、密码存储(凭据只在后端加密保存)、会话管理

---

## 五、部署与更新

| 端 | 方式 | 说明 |
|---|---|---|
| 后端 | 微信云托管控制台「重新构建/部署」(或 Git 关联自动构建) | 构建时 `pip install -r requirements.txt`(含 `pycryptodome`);建议配置 `PASSWORD_SECRET` 环境变量 |
| 小程序 | 微信开发者工具「上传」→ 体验版/正式版 | 后端先上线更稳妥;顺序颠倒也兼容(新接口 404 时自动降级) |

**发布顺序建议**:先部署后端 → 再上传小程序。
