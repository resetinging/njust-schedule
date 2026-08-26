# 南理工课表管理系统

面向南京理工大学学生的教务一站式 Web 应用:登录强智教务系统,拉取并展示**课表、考试安排、教学评价、成绩绩点、四六级成绩**,支持**批量自动评教**与**保研口径 GPA** 计算。部署于微信云托管(Flask + MySQL),手机端可安装为 PWA。

> 本项目从桌面版迁移而来,基于微信云托管 Flask 模板框架二次开发,原模板的计数器示例代码已不再使用。
>
> 配套微信小程序与本后端的分工、模块划分与接口契约,详见 [docs/architecture.md](docs/architecture.md)。
>
> **架构(方案 A)**:后端收敛为「教务网关 + 认证 + 提交中转」,业务计算(GPA 绩点、评教自动评分、批量评教循环)已移至前端(小程序 `utils/gpa.js`、`eval.js`,Web `evaluations.js`)。

## 功能

- **课表**:周视图 + 手机列表视图,自动计算当前教学周(根据学期第一周周一),高亮今日课程
- **考试**:考试安排列表(时间/考场/座位号)
- **教学评价**:
  - 拉取评价批次与课程列表,解析评价指标表单
  - 按目标分自动填选(默认 95 分,含防同列机制与微调优化)
  - 后台线程批量保存/提交全部课程,进度实时可见
  - 内置教务页面反向代理(`/proxy/jw/*`),可在本应用中直接打开教务评价页
- **成绩与绩点**:
  - 成绩记录按学期存储,计算学期绩点与全部学期加权平均绩点(NJUST 4.0 量表)
  - 排除通识教育选修课、缓考/缺考/免修等非正式成绩
  - 保研模式:四六级成绩按官方公式折算百分制,替换英语模块(8 学分)重算 GPA
- **登录**:双端口重定向链认证,验证码支持 ddddocr 自动识别(5 次重试)与手动输入;**仅支持手动登录**(无账号模式)——后端绝不自动登录,用户在设置页输入学号/密码/验证码登录;密码不落库

## 技术栈

- 后端:Python 3.10 / Flask 2.2 / SQLAlchemy 1.4 / MySQL
- 爬虫:requests + BeautifulSoup(lxml),HTML 解析带多策略降级(API → 查询页表单 → 列表页)
- OCR:ddddocr(验证码自动识别)
- 前端:原生 JS + PWA(Service Worker 离线缓存)
- 部署:微信云托管(Dockerfile + container.config.json)

## 目录结构

```
.
├── config.py                    集中配置(数据库、教务 URL、大节定义、HTTP 头)
├── run.py                       Flask 启动入口
├── requirements.txt             依赖清单
├── Dockerfile                    云托管容器构建
├── container.config.json         云托管服务设置与建表 SQL
├── wxcloudrun/                   app 目录
│   ├── __init__.py               Flask 应用与 SQLAlchemy 初始化
│   ├── views.py                  页面路由 + 全部 /api/* 接口 + 批量评教后台
│   ├── jwc_client.py             教务系统爬虫客户端(登录/课表/考试/成绩/评教/四六级)
│   ├── model.py                  ORM 模型(Course/Exam/Evaluation/Grade/CetScore/Setting)
│   ├── dao.py                    数据访问层
│   ├── templates/                Jinja2 页面模板(课表/考试/成绩/评教/校历/设置)
│   └── static/                   前端资源(JS/CSS/PWA/图标/校历图片)
├── docs/
│   └── architecture.md           小程序前后端职责说明与接口契约
```

## 快速开始

### 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `MYSQL_USERNAME` / `MYSQL_PASSWORD` / `MYSQL_ADDRESS` | 云托管 MySQL 连接信息(云托管自动注入) | `root` / `root` / `127.0.0.1:3306` |
| `DEBUG` | Flask 调试模式(生产环境保持关闭) | `False` |

### 本地运行

```bash
pip install -r requirements.txt
python run.py 127.0.0.1 5000
```

浏览器访问 http://127.0.0.1:5000,在「设置」页登录教务系统后即可刷新数据。
注意:教务系统仅限校园网或 VPN 环境访问。

### 云托管部署

使用微信云托管控制台选择本仓库部署(参考[云托管快速开始](https://developers.weixin.qq.com/miniprogram/dev/wxcloudrun/src/basic/guide.html)),数据表由 `container.config.json` 的建表 SQL 与应用启动时的 `db.create_all()` 双保险创建。

## 主要 API

| 端点 | 说明 |
|---|---|
| `GET /api/status` | 登录状态、学期、数据统计 |
| `POST /api/login` / `POST /api/login-manual` | 自动 OCR / 手动验证码登录 |
| `GET /api/get-captcha` | 获取验证码图片(Base64) |
| `POST /api/refresh-schedule` / `refresh-exams` / `refresh-all` | 从教务刷新课表/考试/全部 |
| `POST /api/refresh-grades` / `refresh-cet` / `refresh-evaluations` | 刷新成绩/四六级/评价列表 |
| `GET /api/courses` / `exams` / `grades` / `cet-scores` / `evaluations` | 查询已存储数据(**原始数据**,GPA/折算等计算在前端完成) |
| `GET /api/eval-courses` / `eval-form` | 解析评教课程列表 / 评价表单 |
| `POST /api/submit-eval` | 单门评教提交中转(批量循环由前端执行) |
| `POST /api/jw-proxy` | 通用教务网关:转发任意 9080 GET/POST 并返回原始内容 |
| `POST /api/get-webvpn-captcha` / `login-webvpn-manual` / `login-webvpn` | 智慧理工 SSO 两步/全自动登录 |
| `GET/POST /api/settings`, `POST /api/semester` | 设置与学期切换 |
| `POST /api/clear-data` | 清除当前学期数据 |
| `GET /api/connect-test` | 教务连通性测试 |
| `GET/POST /proxy/jw/*` | 教务页面反向代理(评教用) |

## 使用注意

- 教务系统需要校园网或 VPN 才能访问;**仅支持手动登录**:Session 过期后需在设置页重新输入学号/密码/验证码登录,后端绝不自动登录、不保存密码。
- 登录后教务会话保存在后端容器内存中(单用户共享):任何访问者在该会话有效期内都能看到已登录的数据;容器重启(重新部署/缩容冷启动)或教务会话过期后自动回到未登录状态。
- 批量评教为自动化辅助工具,请仅用于自己的账号,并自行承担使用责任。

## License

[MIT](./LICENSE)
