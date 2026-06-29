# 南理工课表 — 微信小程序

基于 [njust-schedule](../njust-schedule/) Flask 后端 API 的微信小程序客户端。

## 项目结构

```
miniprogram/
├── app.js / app.json / app.wxss   # 应用入口 + 全局配置 + 样式
├── project.config.json             # 微信开发者工具配置
├── sitemap.json                    # 站点地图
├── utils/
│   ├── config.js                   # 服务器地址等配置
│   ├── api.js                      # 后端 API 封装
│   ├── storage.js                  # 本地缓存管理
│   └── date.js                     # 日期工具函数
├── pages/
│   ├── schedule/                   # 课表（周视图）
│   ├── exams/                      # 考试安排
│   ├── eval/                       # 教学评价 + 一键评教
│   └── settings/                   # 登录 + 用户设置
└── components/
    ├── week-grid/                  # 课表网格组件
    ├── captcha-input/              # 验证码输入组件
    └── loading-modal/              # 加载/进度弹窗
```

## 前置条件

### 1. 启动 Flask 后端

```bash
cd ../njust-schedule
pip install flask gunicorn requests beautifulsoup4 lxml pytesseract opencv-python-headless numpy
python app.py
# 后端运行在 http://localhost:5000
```

### 2. 配置服务器地址

编辑 `utils/config.js`，修改 `API_BASE` 为服务器实际地址：
- 本地开发：`http://localhost:5000`
- 云部署：`https://your-domain.com`

### 3. 配置小程序 AppID

编辑 `project.config.json`，将 `appid` 改为你的小程序 AppID。

## 开发步骤

1. 下载 [微信开发者工具](https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html)
2. 打开工具 → 导入项目 → 选择 `miniprogram/` 目录
3. 填入 AppID（或选择"测试号"）
4. 开始开发调试

## 发布前检查

- [ ] 后端已部署到 HTTPS 服务器
- [ ] 域名已在微信公众平台 → 服务器域名 → request 合法域名中配置
- [ ] `utils/config.js` 中的 `API_BASE` 指向生产服务器
- [ ] TabBar 图标已替换为实际 PNG（`static/icons/*.png`）
- [ ] 测试登录 → 课表 → 考试 → 评教全流程

## 技术栈

| 层 | 技术 |
|----|------|
| 前端 | 微信小程序原生框架 (WXML + WXSS + JS) |
| 后端 | Python Flask + Gunicorn（复用 njust-schedule） |
| 通信 | wx.request (HTTPS) |
| 存储 | wx.Storage（本地缓存） |
| OCR | 服务端 Tesseract |
