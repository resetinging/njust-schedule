# 📅 南理工课表管理系统

自动从南京理工大学教务系统（强智）获取课表、考试、成绩、教学评价，以漂亮网页形式展示。支持桌面客户端和手机同时访问。

## ✨ 功能

### 📅 课表管理
- 🔐 **自动登录教务系统** — 支持验证码自动识别（ddddocr）+ 手动输入
- 📅 **课表自动抓取** — 获取完整课表，含上课时间、地点、教师、周次
- 🎨 **色彩标注** — 不同课程不同颜色，单双周区分
- 📱 **响应式布局** — 大节行高按小节比例自适应

### 📝 考试安排
- 📋 **考试自动同步** — 考试时间、地点、座位号一键获取
- ⏰ **倒计时显示** — 距每场考试的天数和小时数
- 🏫 **考场分布** — 按时间排序，清晰展示考试日程

### 📊 成绩查询
- 📈 **全部学期成绩** — 按学期分组，支持单学期/全部学期切换
- 🎯 **绩点计算（NJUST 4.0）** — 加权平均绩点，含完整五分制映射
  - 百分制→绩点精确换算（90→4.0, 85→3.7, 82→3.3, 78→3.0 ...）
  - 五级制全映射（优/优-/良+/良/良-/中+/中/中-/及格/不及格）
- 🚫 **通识选修课过滤** — 按 NJUST 评奖/保研规则自动排除通识教育选修课
- 🏆 **四六级成绩** — 从教务拉取 CET-4/CET-6 成绩，自动折算百分制
- 🎓 **保研推免 GPA 模式** — 用 CET 折算分替换英语模块（8学分），计算保研口径绩点

### 📝 教学评价
- 📋 **评教列表获取** — 按批次展示未完成/已完成评价
- 🤖 **手动评教辅助** — 解析评价表单，可视化指标选项
- ⚡ **一键评教** — 自动贪心算法填写指标 + 防作弊随机化，支持批量提交
- 📊 **实时进度** — 批量评教时轮询显示进度

### 🔧 系统功能
- 💾 **本地数据库** — SQLite 存储，离线可查历史数据
- 🔄 **一键刷新** — 课表/考试/成绩/评教数据随时从教务更新
- 📱 **多设备访问** — 手机连同一 WiFi 即可查看，支持 PWA
- 🖥️ **桌面客户端** — pywebview 原生窗口，可 PyInstaller 打包为 EXE

## 🚀 快速开始

### 第一步：安装 Python

确保电脑已安装 **Python 3.9 或更高版本**。

- 下载地址：https://www.python.org/downloads/
- ⚠️ 安装时勾选 **"Add Python to PATH"**

验证安装：
```bash
python --version
```

### 第二步：安装依赖

双击运行 `scripts\setup.bat`，自动完成所有依赖安装。

或手动执行：
```bash
pip install -r requirements.txt
```

### 第三步：启动

**方式 1：Web 模式**（推荐日常使用）

双击 `scripts\run.bat`，或执行：
```bash
python app.py
```

浏览器打开 `http://127.0.0.1:5000`。

**方式 2：桌面模式**

```bash
python main.py
```

### 第四步：使用

1. 打开浏览器访问 `http://127.0.0.1:5000`
2. 进入「设置」页面，输入学号和密码登录教务系统
3. 登录成功后，在各页面点击「刷新」按钮获取最新数据

## 📱 手机访问

确保手机和电脑连接 **同一 WiFi**，然后在手机浏览器输入：

```
http://电脑IP:5000
```

电脑 IP 在启动时显示。也可以添加到主屏幕获得 PWA 全屏体验。

## ⚠️ 使用前提

- **必须连接校园网 i-Zijin 或南理工 VPN**
- 教务系统地址（校内）：http://202.119.81.113:8080/
- 如果在校外，请先通过 VPN 连接到校园网

## 📁 项目结构

```
njust-schedule-desktop/
├── app.py                  # Flask 应用工厂 + 启动入口
├── config.py               # 集中配置（教务URL、端口、大节映射）
├── database.py             # SQLite 数据库管理（建表、迁移、CRUD）
├── gpa.py                  # 绩点计算（NJUST 4.0 量表、CET折算、保研模式）
├── jwc_client.py           # 教务系统爬虫客户端（登录/课表/考试/成绩/CET/评教）
├── eval_helpers.py         # 评教辅助（表单解析、自动评分算法、POST构建）
├── main.py                 # 桌面窗口入口（pywebview）
│
├── routes/                 # Flask 蓝图路由（按功能域拆分）
│   ├── __init__.py         # 共享状态、工具函数（JWC客户端、自动登录）
│   ├── pages.py            # HTML 页面路由 + 教务代理
│   ├── api_auth.py         # 认证 API（登录/验证码/状态）
│   ├── api_data.py         # 数据 API（课表/考试/成绩/CET）
│   ├── api_eval.py         # 评教 API（列表/表单/提交/批量）
│   └── api_settings.py     # 设置 API（学期/配置/清除）
│
├── templates/              # Jinja2 HTML 模板
│   ├── base.html           # 基础布局（导航栏、页脚、Toast/Loading）
│   ├── index.html          # 课表页
│   ├── exams.html          # 考试页
│   ├── grades.html         # 成绩页（含CET栏、GPA模式切换）
│   ├── evaluations.html    # 评教页
│   └── settings.html       # 设置页
│
├── static/                 # 静态资源
│   ├── css/style.css       # 全局样式
│   ├── js/
│   │   ├── main.js         # 公共函数（escapeHtml、Toast、Loading）
│   │   ├── schedule.js     # 课表逻辑（大节渲染、周筛选）
│   │   ├── exams.js        # 考试逻辑（倒计时、时间解析）
│   │   ├── grades.js       # 成绩逻辑（GPA模式切换、CET展示）
│   │   ├── evaluations.js  # 评教逻辑（批量提交、进度轮询）
│   │   └── settings.js     # 设置逻辑（登录、验证码）
│   ├── manifest.json       # PWA 清单
│   ├── sw.js               # Service Worker（离线缓存）
│   └── *.png / *.ico       # 图标
│
├── docs/
│   └── android-build-guide.md  # Android APK 构建指南
│
├── requirements.txt        # Python 依赖
├── scripts/
│   ├── build.bat            # EXE 构建脚本
│   ├── setup.bat            # 一键安装脚本
│   ├── run.bat              # 一键启动脚本
│   └── run.pyw              # 无控制台启动入口
├── njust_schedule.spec     # PyInstaller 打包配置
└── README.md               # 本文件
```

## 📐 绩点计算规则

### NJUST 4.0 量表

| 百分制 | 绩点 | 五级制 |
|--------|------|--------|
| 90-100 | 4.0  | 优     |
| 85-89  | 3.7  | 优-    |
| 82-84  | 3.3  | 良+    |
| 78-81  | 3.0  | 良     |
| 75-77  | 2.7  | 良-    |
| 72-74  | 2.3  | 中+    |
| 68-71  | 2.0  | 中     |
| 64-67  | 1.5  | 中-    |
| 60-63  | 1.0  | 及格   |
| <60    | 0    | 不及格 |

### 绩点计算公式

$$\text{GPA} = \frac{\sum(\text{课程学分} \times \text{课程绩点})}{\sum\text{课程学分}}$$

- 通识教育选修课不计入（按 NJUST 评奖/保研规则）
- 缓考/缺考/免修等非正式成绩不参与计算

### 四六级折算（保研模式）

$$\text{百分制} = \frac{\text{CET分数} - 425}{285} \times 40 + 60$$

- CET6 额外 +5 分（封顶 100）
- < 425 分不可用，回退到校内英语课成绩
- 替换全部英语课（通用英语 + 专用英语-*，共 8 学分）

## 🔧 常见问题

### Q: 无法连接教务系统？

- 确认已连接校园网 i-Zijin
- 或确认 VPN 已连接
- 在设置页点击「测试连接」按钮检查

### Q: 登录失败？

- 检查学号和密码是否正确
- 验证码自动识别有概率失败，系统会自动重试 5 次
- 可点击「显示验证码」手动输入
- 如果多次失败，可能教务系统暂时维护中

### Q: 课表/成绩数据为空？

- 确认已在设置页登录成功
- 确认已选择正确的学期
- 点击「刷新」按钮从教务获取最新数据

### Q: 手机无法访问？

- 确认手机和电脑在同一 WiFi
- 确认防火墙没有阻止 5000 端口
- Windows 防火墙会弹出提示，请选择「允许访问」

### Q: 如何更改端口？

编辑 `config.py` 中的 `PORT = 5000` 改为其他端口。

## 🛠️ 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.9+ | 后端语言 |
| Flask 3.x | Web 框架（蓝图拆分） |
| SQLite | 本地数据存储 |
| requests | HTTP 请求 |
| ddddocr | 验证码 OCR 识别 |
| BeautifulSoup4 + lxml | HTML 解析 |
| pywebview | 桌面窗口 |
| PyInstaller | EXE 打包 |
| HTML/CSS/JS | 原生前端（无框架） |

## 📦 构建桌面应用

```bash
# 安装 PyInstaller
pip install pyinstaller

# 一键构建
scripts\build.bat

# 或手动
pyinstaller njust_schedule.spec --clean --noconfirm
```

输出位置：`dist/南理工课表管理/南理工课表管理.exe`

## 📝 参考项目

- [NJUST-JWC-API](https://github.com/Inetgeek/NJUST-JWC-API) — 南理工教务 API
- [classCrawl](https://github.com/inannan423/classCrawl) — 强智教务课表爬虫
- [南理工教务增强助手](https://greasyfork.org/zh-CN/scripts/541627) — 浏览器增强脚本
