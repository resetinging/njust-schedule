# 南理工课表管理 — APK 打包方案

## 项目现状

| 项目 | 说明 |
|------|------|
| 语言 | Python 3 |
| 框架 | Flask（Web 后端） |
| 前端 | HTML + CSS + 原生 JavaScript |
| 桌面窗口 | pywebview（Windows） |
| 数据库 | SQLite（本地文件） |
| 教务抓取 | requests + BeautifulSoup + ddddocr（OCR） |
| 当前运行方式 | `python main.py` → 桌面窗口 |
| EXE 打包 | PyInstaller → 169MB 单文件 |

## 目标

将应用打包为 **Android APK**，手机独立运行，无需依赖电脑。

## 技术方案

### 推荐方案：Buildozer + WebView

**原理**：
```
┌──────────────────────────────────┐
│           Android APK            │
│  ┌────────────────────────────┐  │
│  │     Java/Kotlin 壳         │  │
│  │  ┌──────────────────────┐  │  │
│  │  │   Android WebView    │  │  │
│  │  │   显示 HTML/CSS/JS   │  │  │
│  │  └──────────┬───────────┘  │  │
│  │             ↓              │  │
│  │  ┌──────────────────────┐  │  │
│  │  │   Python 后端线程    │  │  │
│  │  │   Flask + 爬虫 + DB │  │  │
│  │  └──────────────────────┘  │  │
│  └────────────────────────────┘  │
└──────────────────────────────────┘
```

- Python 后端通过 **Chaquopy** 或 **python-for-android** 嵌入 APK
- Flask 在手机本地运行（127.0.0.1:5000）
- WebView 加载本地 Flask 页面
- 用户体验：打开 APP → 直接看到课表（和桌面版一致）

### 备选方案：云部署 + PWA

- Flask 部署到云服务器
- 手机通过互联网访问
- 缺点：教务系统限校园网，云服务器无法抓取数据
- 解决：手机端直接调用教务 API（需要 CORS 代理或 NJUST VPN）

## 构建环境要求

| 需求 | 说明 |
|------|------|
| 操作系统 | Linux（Ubuntu 20.04+ 推荐）或 WSL2 |
| Android SDK | API 30+ |
| Python | 3.9+ |
| Buildozer | 自动化构建工具 |
| 磁盘空间 | ~10GB（SDK + 依赖） |

## 实现步骤

### 第一步：修改 Python 代码适配 Android

**需要修改的文件**：

1. **移除不可用依赖**
   - `pywebview` → Android 上不需要（WebView 由 Java 壳提供）
   - `ddddocr` → ARM 平台的 ONNX Runtime 兼容性问题，改为仅手动验证码

2. **修改 `jwc_client.py`**
   ```python
   # ddddocr 改为可选导入
   try:
       import ddddocr
       HAS_OCR = True
   except ImportError:
       HAS_OCR = False  # Android 上用手动验证码
   ```

3. **新增 `start_android.py`** — Android 入口
   ```python
   """Android 启动入口 — Flask 本地服务器 + 自动打开浏览器"""
   import threading
   from app import app, init_db
   
   def start():
       init_db()
       t = threading.Thread(target=lambda: app.run(
           host="127.0.0.1", port=5000, debug=False
       ), daemon=True)
       t.start()
       # Android Intent 打开 Chrome
       import android  # Chaquopy API
       android.open_url("http://127.0.0.1:5000")
   
   if __name__ == "__main__":
       start()
   ```

4. **新增 `requirements_android.txt`**
   ```
   Flask==3.1.*
   requests==2.32.*
   beautifulsoup4==4.12.*
   lxml==5.3.*
   Pillow==11.1.*
   # 不使用 ddddocr（ARM 兼容问题）
   # 不使用 pywebview（Android 用原生 WebView）
   ```

### 第二步：创建 Buildozer 配置

**`buildozer.spec`**（关键配置）：
```ini
[app]
title = 南理工课表
package.name = njustschedule
package.domain = njust.app
source.dir = .
source.include_exts = py,png,jpg,html,css,js,json,db
requirements = python3,flask,requests,beautifulsoup4,lxml,pillow,sqlite3
android.permissions = INTERNET
android.api = 31
android.minapi = 26
p4a.branch = develop
```

### 第三步：构建 APK

```bash
# 在 Linux/WSL 中执行
pip install buildozer
buildozer init          # 生成配置文件
buildozer android debug # 构建调试版 APK
buildozer android release  # 构建发布版 APK（需签名）
```

构建时间：首次约 20-30 分钟（下载 SDK + 编译依赖）

### 第四步：生成 PWA 图标

需要以下尺寸的图标（已有 192px 和 512px，需补充）：
- 48×48, 72×72, 96×96, 144×144, 192×192, 512×512

### 第五步：签名发布

```bash
# 生成签名密钥
keytool -genkey -v -keystore njust.keystore -alias njust -keyalg RSA

# 签名 APK
jarsigner -keystore njust.keystore njustschedule.apk njust

# 优化
zipalign -v 4 njustschedule.apk njustschedule-release.apk
```

## 手机使用流程

1. 下载 `南理工课表.apk` 到手机
2. 安装（允许"未知来源"）
3. 打开 APP，自动显示课表页面
4. 在「设置」中登录教务系统（手动输入验证码）
5. 点击刷新课表 / 刷新考试
6. 手机需连接校园网 i-Zijin 或 NJUST VPN

## 已知限制

| 限制 | 原因 | 解决方式 |
|------|------|----------|
| 验证码需手动输入 | OCR 库在 ARM 上不可用 | 设置页面支持手动输入验证码（已实现） |
| 需校园网/VPN | 教务系统仅限校内访问 | 手机连接 i-Zijin WiFi 或 NJUST VPN APP |
| APK 体积较大 | Python 运行时 ~40MB + 依赖 | 首次安装约 80-120MB |
| 无 iOS 支持 | iOS 不允许嵌入 Python 运行时 | 仅支持 Android |

## 构建脚本

项目根目录提供 `build_apk.sh`：
```bash
#!/bin/bash
# 一键构建 APK（需在 Linux/WSL 中运行）
set -e
echo "=== 南理工课表管理 APK 构建 ==="
pip install buildozer cython
buildozer android debug
echo "=== 构建完成 ==="
echo "APK 位置: ./bin/njustschedule-*.apk"
```

## 总结

- 核心改动量：新增 2 个文件（`start_android.py`、`buildozer.spec`），修改 2 个文件（`jwc_client.py` OCR 可选、`requirements_android.txt`）
- HTML/CSS/JS 前端代码**完全不变**
- Python 后端逻辑**基本不变**
- 构建环境：需要 Linux 或 WSL2
- 首次构建时间：约 30 分钟
