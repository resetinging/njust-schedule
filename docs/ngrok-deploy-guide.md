# 南理工课表管理 — ngrok 内网穿透部署方案

## 目标

电脑运行 Flask 后端 → ngrok 暴露公网 HTTPS URL → iPhone 通过流量随时随地访问

## 整体架构

```
教务系统 (202.119.81.112)
       ↑
Flask (127.0.0.1:5000)  ←──  ngrok 隧道  ←──  ngrok 公网服务器
       ↑                                              ↓
  你的 Windows 电脑                              https://xxx.ngrok-free.app
                                                       ↓
                                                  iPhone Safari / PWA
```

---

## 第一步：注册 ngrok（一次性操作）

1. 打开 [ngrok.com](https://ngrok.com)，点 "Sign Up"
2. 用 GitHub 或 Google 账号注册（免费）
3. 登录后，左侧菜单 → **Your Authtoken**
4. 复制 token，在终端执行：
   ```bash
   ngrok config add-authtoken <你的authtoken>
   ```

---

## 第二步：领取免费固定域名（一次性操作）

1. ngrok 控制台左侧 → **Cloud Edge** → **Domains**
2. 点 "Create Domain"
3. 会给你一个 `xxx.ngrok-free.app` 的域名（永久不变）
4. 记下这个域名，后面会用

---

## 第三步：启动（每次使用）

开两个终端：

**终端 1 — Flask：**
```bash
cd D:\njust-schedule-fork
python app.py
```

**终端 2 — ngrok：**
```bash
ngrok http --domain=<你的固定域名>.ngrok-free.app 5000
```

搞定。iPhone 打开 `https://<你的域名>.ngrok-free.app` 即可。

---

## 第四步：iPhone 添加到主屏幕（PWA）

1. Safari 打开上面的 URL
2. 底部点 **分享按钮**（↑）
3. 选择 **「添加到主屏幕」**
4. 命名（建议 "南理工课表"），点添加

之后从桌面图标打开就是全屏模式，和原生 App 体验一样。

---

## 一键启动脚本（可选）

嫌每次开两个终端麻烦的话，可以写一个批处理 `scripts/tunnel.bat`：

```batch
@echo off
chcp 65001 >nul
cd /d "%~dp0.."

echo 启动 Flask 后台服务...
start "Flask" py -m flask run --host=0.0.0.0 --port=5000 --no-debug

echo 等待 Flask 就绪...
timeout /t 2 >nul

echo 启动 ngrok 隧道...
ngrok http --domain=YOUR_DOMAIN.ngrok-free.app 5000
```

把 `YOUR_DOMAIN` 替换成你的实际域名，双击就能启动。

---

## 注意事项

| 问题 | 说明 |
|------|------|
| **免费版限制** | 每月 ~1GB 流量，日常查课表够用 |
| **浏览器确认页** | 免费版首次访问会有 ngrok "Visit Site" 确认页，点一下即可；PWA 添加到主屏幕后不会出现 |
| **电脑不能关** | Flask 跑在本机，电脑需要保持开机且不睡眠 |
| **HTTPS** | ngrok 自动提供，Service Worker 可以正常注册 |
| **固定域名** | 免费版只给 1 个固定域名，不要乱创建 |

---

## 如果不想开电脑

这个方案需要电脑始终开机。如果你想要 7×24 在线且不需要开自己电脑，需要切换到**云服务器部署方案**（见 `docs/cloud-deploy-guide.md`，待编写）。
