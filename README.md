# 课表助手 · 微信小程序

> 状态：现行；最后核对：2026-10-23

南京理工大学课表助手的微信小程序客户端。后端使用 Go/WebGo，部署在微信云托管；小程序默认通过 `wx.cloud.callContainer` 访问服务。

## 项目结构

```text
miniprogram/
├── app.js / app.json / app.wxss
├── pages/main/                  # 单主页面: 功能 / 课表 / 我的
├── pages/freeclass/             # 空教室独立入口
├── pages/ui-preview/            # UI 预览
├── components/
│   ├── ad-slot/                 # 微信原生模板广告封装
│   ├── notice-board-view/       # 信息中心
│   ├── schedule-view/           # 课表
│   ├── grades-view/             # 成绩
│   ├── exams-view/              # 考试
│   ├── freeclass-view/          # 空教室
│   ├── audit-course-view/       # 蹭课查询
│   └── gallery-view/            # 校园图鉴
├── utils/
│   ├── config.js                # 云环境、构建号、本地联调开关
│   ├── api/                     # 分域 API 封装
│   ├── storage.js               # 本地缓存和会话状态
│   ├── analytics.js             # 使用统计与广告槽位
│   └── content-board.js         # 公告、更新日志和 QQ 群
├── docs/privacy-guideline.md
└── tools/                       # Node/Python 回归与门禁脚本
```

## 运行配置

编辑 `utils/config.js`：

- `CLOUD_ENV`：微信云托管环境 ID
- `CLOUD_SERVICE`：云托管服务名
- `USE_LOCAL`：是否直连本机 WebGo
- `LOCAL_BASE`：本地服务地址，默认 `http://127.0.0.1:5000`
- `BUILD`：设置页显示的构建标识
- `DEBUG_TODAY`：发布前必须留空

生产版本必须保持 `USE_LOCAL = false`。

## 开发者工具

1. 使用微信开发者工具导入本目录。
2. 使用项目 `project.config.json` 中的 AppID。
3. 本地直连时勾选“不校验合法域名”。
4. 修改 `.miniapp` 后同步到 `C:\Users\a\Documents\local\miniprogram`，并核对哈希。

## 常用测试

```bash
node tools/test_api_smoke.js
node tools/test_navigation.js
node tools/test_audit.js
node tools/test_freeclass.js
node tools/test_ad_slot.js
node tools/test_analytics_slots.js
PYTHONIOENCODING=utf-8 python tools/verify_miniapp.py .
PYTHONIOENCODING=utf-8 python tools/verify_privacy.py .
```

## 文档

- [用户隐私保护指引](docs/privacy-guideline.md)
- 后端仓库的 `docs/HANDOFF.md`：Agent 交接
- 后端仓库的 `docs/architecture/current.md`：系统架构
- 后端仓库的 `docs/operations/miniprogram-launch.md`：上线流程

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | 微信小程序原生 WXML/WXSS/JS |
| UI | TDesign 小程序组件 + 本地统一设计变量 |
| 后端 | Go/WebGo，微信云托管 |
| 通信 | `wx.cloud.callContainer`，本地联调使用 `wx.request` |
| 存储 | 本地缓存 + 服务端 MySQL |
| 广告 | 微信原生模板广告 `ad-custom` |
