# 南理工课表管理 — Linux 构建指南

> 从零开始在 Linux 上搭建环境、修改代码、构建 Android APK 的完整流程。

---

## 目录

1. [项目概述](#项目概述)
2. [架构说明](#架构说明)
3. [环境准备（Ubuntu 22.04）](#环境准备)
4. [克隆项目](#克隆项目)
5. [代码修改（适配 Android）](#代码修改)
6. [Buildozer 配置](#buildozer-配置)
7. [构建 APK](#构建-apk)
8. [APK 签名](#apk-签名)
9. [安装测试](#安装测试)
10. [故障排除](#故障排除)
11. [开发模式运行](#开发模式运行)

---

## 项目概述

| 项目 | 说明 |
|------|------|
| 语言 | Python 3.9+ |
| Web 框架 | Flask 3.x |
| 前端 | HTML + CSS + 原生 JavaScript（无框架） |
| 数据库 | SQLite（本地 `schedule.db`） |
| 教务抓取 | requests + BeautifulSoup + lxml |
| OCR | ddddocr（桌面版）/ 手动输入（手机版） |
| 桌面窗口 | pywebview（Windows/macOS/Linux） |
| PWA | manifest.json + Service Worker |
| 依赖管理 | requirements.txt |

### 核心文件

```
njust-schedule/
├── config.py              # 集中配置（教务URL、端口、大节映射）
├── app.py                 # Flask Web 应用（路由 + API + SQLite）
├── jwc_client.py          # 教务系统爬虫（登录 + 课表 + 考试）
├── main.py                # 桌面窗口入口（pywebview）
├── start_android.py       # Android 入口（Flask + WebView）← APK 构建时新增
├── buildozer.spec         # Buildozer 构建配置 ← APK 构建时新增
├── requirements.txt       # 桌面版依赖
├── requirements_android.txt # Android 版依赖 ← APK 构建时新增
├── static/
│   ├── css/style.css      # 全局样式（815 行）
│   ├── js/main.js         # 公共函数（Toast、Loading、导航状态）
│   ├── js/schedule.js     # 课表页面逻辑（大节渲染、周筛选）
│   ├── js/exams.js        # 考试页面逻辑（倒计时、时间解析）
│   ├── js/settings.js     # 设置页面逻辑（登录、验证码）
│   ├── manifest.json      # PWA 清单
│   ├── sw.js              # Service Worker（离线缓存）
│   └── icon-*.png         # PWA 图标（192px + 512px）
└── templates/
    ├── base.html          # 基础布局（导航栏、页脚）
    ├── index.html         # 课表页面
    ├── exams.html         # 考试页面
    └── settings.html      # 设置页面
```

---

## 架构说明

### 桌面版架构（当前）

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  pywebview  │ ──→ │  Flask:5000  │ ──→ │  教务系统    │
│  (桌面窗口)  │ ←── │  (本地服务器)  │ ←── │  (校园网)    │
└─────────────┘     └──────┬───────┘     └─────────────┘
                           │
                    ┌──────┴───────┐
                    │  schedule.db │
                    └──────────────┘
```

### Android 版架构（目标）

```
┌────────────────────────────────────────┐
│              Android APK               │
│                                        │
│  ┌──────────────────────────────────┐  │
│  │         WebView Activity         │  │
│  │     (Android 原生 WebView)       │  │
│  │     加载 http://127.0.0.1:5000   │  │
│  └──────────────┬───────────────────┘  │
│                 │                      │
│  ┌──────────────┴───────────────────┐  │
│  │       Python 运行时 (p4a)        │  │
│  │  ┌────────────────────────────┐  │  │
│  │  │  Flask 后端线程             │  │  │
│  │  │  - app.py (路由 + API)     │  │  │
│  │  │  - jwc_client.py (爬虫)    │  │  │
│  │  │  - SQLite (schedule.db)    │  │  │
│  │  └────────────────────────────┘  │  │
│  └──────────────────────────────────┘  │
└────────────────────────────────────────┘
```

数据流：用户操作 → WebView → Flask API → 教务系统抓取 → SQLite → 返回前端

---

## 环境准备

### 硬件要求

| 项目 | 最低配置 |
|------|----------|
| CPU | 4 核 |
| 内存 | 8 GB |
| 磁盘 | 20 GB 可用空间 |
| 网络 | 可访问 GitHub、PyPI、Google Maven |

### 操作系统

**推荐：Ubuntu 22.04 LTS**（桌面版或 Server 版均可）

```bash
# 查看系统版本
lsb_release -a
# Ubuntu 22.04.4 LTS
```

### 安装系统依赖

```bash
# 更新包索引
sudo apt update && sudo apt upgrade -y

# 基础工具
sudo apt install -y \
    git curl wget unzip tar \
    build-essential autoconf libtool \
    python3 python3-pip python3-venv python3-dev \
    openjdk-17-jdk openjdk-17-jre \
    zlib1g-dev libncurses5-dev libgdbm-dev libnss3-dev \
    libssl-dev libreadline-dev libffi-dev \
    libsqlite3-dev libbz2-dev \
    liblzma-dev libfreetype6-dev \
    cmake pkg-config

# 验证安装
python3 --version   # Python 3.10+
java -version       # OpenJDK 17
git --version       # 2.34+
```

### 安装 Android SDK 命令行工具

```bash
# 创建 SDK 目录
mkdir -p ~/Android/Sdk/cmdline-tools
cd ~/Android/Sdk/cmdline-tools

# 下载命令行工具
wget https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
unzip commandlinetools-linux-11076708_latest.zip
mv cmdline-tools latest

# 设置环境变量（写入 ~/.bashrc）
cat >> ~/.bashrc << 'EOF'
export ANDROID_HOME=$HOME/Android/Sdk
export ANDROID_SDK_ROOT=$HOME/Android/Sdk
export PATH=$PATH:$ANDROID_HOME/cmdline-tools/latest/bin
export PATH=$PATH:$ANDROID_HOME/platform-tools
export PATH=$PATH:$ANDROID_HOME/build-tools/34.0.0
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
EOF

source ~/.bashrc

# 安装 SDK 组件
yes | sdkmanager --licenses
sdkmanager "platform-tools" "platforms;android-34" "build-tools;34.0.0"
```

---

## 克隆项目

```bash
# 克隆仓库
git clone git@github.com:resetinging/njust-schedule.git
cd njust-schedule

# 查看项目结构
ls -la
```

---

## 代码修改（适配 Android）

以下修改需要在 Linux 环境中完成。**核心原则：HTML/CSS/JS 前端代码完全不变，Python 后端逻辑最小化修改。**

### 修改 1：OCR 改为可选导入

**文件：`jwc_client.py`**

找到文件顶部 import 区域，将 ddddocr 改为可选导入：

```python
# 在 "from bs4 import BeautifulSoup" 之后新增：

# OCR 库可选（Android ARM 平台不可用）
try:
    import ddddocr
    HAS_DDDDOCR = True
except ImportError:
    HAS_DDDDOCR = False
    print("[警告] ddddocr 未安装，仅支持手动输入验证码")
```

然后在所有使用 `ddddocr` 的地方加上 `HAS_DDDDOCR` 判断。当前 `jwc_client.py` 中 ddddocr 仅在 `_ocr_with_preprocess()` 方法中使用，该方法由 `_try_auto_login()` 调用，如果 OCR 不可用会自动降级到手动验证码模式。

### 修改 2：创建 Android 入口文件

**文件：`start_android.py`**（新建）

```python
"""
南理工课表管理 — Android 启动入口
=================================
在 Android 设备上启动 Flask 本地服务器 + 自动打开 WebView。
通过 python-for-android 的 android 模块管理生命周期。
"""

import os
import sys
import threading
import time

# 数据库目录（Android 内部存储）
DB_DIR = os.environ.get("ANDROID_ARGUMENT", "/data/data/org.njust.schedule/files")
os.environ["NJUST_DB_DIR"] = DB_DIR

from app import app, init_db


def start_flask():
    """后台线程启动 Flask"""
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)


def main():
    """Android 主入口"""
    # 初始化数据库
    init_db()

    # 启动 Flask 后台线程
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    # 等待 Flask 就绪
    time.sleep(0.5)

    # 通过 Android API 打开 WebView
    try:
        from android.runnable import run_on_ui_thread
        from jnius import autoclass

        @run_on_ui_thread
        def open_webview():
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            intent = Intent(Intent.ACTION_VIEW)
            intent.setData(Uri.parse("http://127.0.0.1:5000"))
            activity.startActivity(intent)

        open_webview()
    except ImportError:
        print("[Android] 非 Kivy 环境，Flask 已启动在 http://127.0.0.1:5000")


if __name__ == "__main__":
    main()
```

### 修改 3：创建 Android 依赖文件

**文件：`requirements_android.txt`**（新建）

```
# Android 版依赖（python-for-android 构建用）
# 注意：p4a 通过 buildozer.spec 中的 requirements 字段管理依赖
# 此文件仅作为参考文档

Flask==3.1.*
requests==2.32.*
beautifulsoup4==4.12.*
lxml==5.3.*
Pillow==11.1.*

# 以下依赖在 Android 上不可用或不使用：
# ddddocr      → ARM ONNX Runtime 兼容性问题，使用手动验证码
# pywebview    → Android 使用原生 WebView
# waitress     → Flask 内置开发服务器即可（单用户本地访问）
```

---

## Buildozer 配置

### 创建 buildozer.spec

在项目根目录执行：

```bash
pip install --user buildozer cython
buildozer init
```

这会生成默认的 `buildozer.spec`。然后修改以下关键字段：

**文件：`buildozer.spec`**

```ini
[app]

# 应用标识
title = 南理工课表
package.name = njustschedule
package.domain = org.njust

# 源代码配置
source.dir = .
source.include_exts = py,png,jpg,jpeg,html,css,js,json,db,ttf,otf

# Python 版本
python.version = 3.10

# ============================================================
# 依赖（python-for-android 自动编译 C 扩展）
# ============================================================
requirements = python3,kivy,flask,requests,beautifulsoup4,lxml,pillow,pyjnius,sqlite3,openssl

# 注意：kivy 是必须的（p4a 用它来管理 Activity 生命周期）
# pyjnius 用于调用 Android Java API

# ============================================================
# Android 权限
# ============================================================
android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE

# ============================================================
# Android API 级别
# ============================================================
android.api = 34
android.minapi = 26
android.ndk = 25b

# ============================================================
# 应用图标和启动画面
# ============================================================
icon.filename = %(source.dir)s/static/icon-512.png
presplash.filename = %(source.dir)s/static/icon-512.png

# ============================================================
# 编译选项
# ============================================================
android.arch = arm64-v8a
# android.arch = arm64-v8a,armeabi-v7a  # 如需兼容 32 位设备

# ============================================================
# 签名配置（发布时填写）
# ============================================================
# android.release.sign = release
# android.release.keyalias = njust
# android.release.keystore = njust.keystore

# ============================================================
# 其他
# ============================================================
android.allow_backup = True
android.presplash_color = #1a5276
orientation = portrait,landscape
fullscreen = 0
log_level = 2
warn_on_root = 1

# Kivy 配置
[buildozer]
log_level = 2
```

### 关键配置说明

| 配置 | 值 | 说明 |
|------|-----|------|
| `requirements` | 含 `kivy` | p4a 用 Kivy 管理 Activity，即使不写 Kivy UI 也需要 |
| `requirements` | 含 `pyjnius` | 调用 Android Java API（如打开 WebView） |
| `requirements` | 含 `openssl` | Flask 的 Werkzeug 需要 SSL 支持 |
| `android.ndk` | `25b` | 与 p4a develop 分支兼容的 NDK 版本 |
| `android.arch` | `arm64-v8a` | 仅 64 位（减少 APK 体积），需兼容 32 位则加 `armeabi-v7a` |

---

## 构建 APK

### 下载 Android SDK（自动）

首次运行 `buildozer` 会自动下载 Android SDK、NDK、python-for-android 及所有依赖。确保网络畅通。

### 调试版构建

```bash
# 清理旧构建（可选）
buildozer android clean

# 构建调试版 APK
buildozer android debug

# 构建时间：
#   首次：30-60 分钟（下载 SDK、编译 Python、编译 C 扩展）
#   后续：5-10 分钟（增量编译）
```

构建成功后，APK 位于：
```
./bin/njustschedule-0.1-debug.apk
```

### 构建过程详解

```
buildozer android debug
  ├── 检查/下载 Android SDK
  ├── 检查/下载 Android NDK (25b)
  ├── 克隆/更新 python-for-android
  ├── 创建 Python 发行版
  │   ├── 交叉编译 Python 解释器（arm64-v8a）
  │   ├── 安装 pip 依赖
  │   └── 编译 C 扩展（lxml、Pillow 等）
  ├── 打包 APK
  │   ├── 创建 Android 项目骨架
  │   ├── 复制源代码 + 静态文件
  │   ├── 编译 Java 代码
  │   ├── 生成 DEX
  │   └── 打包 + 对齐
  └── 输出 APK
```

### 监控构建进度

```bash
# 实时查看日志
buildozer android debug 2>&1 | tee build.log

# 查看详细日志
tail -f .buildozer/android/platform/build-*/dists/njustschedule/build/build.log
```

---

## APK 签名

### 调试版（开发测试用）

调试版 APK 自带调试签名，可直接安装测试，无需额外签名。

```bash
# 安装到连接的设备
buildozer android deploy run

# 或手动安装
adb install ./bin/njustschedule-0.1-debug.apk
```

### 发布版（正式分发用）

需要生成正式签名密钥：

```bash
# 生成密钥库
keytool -genkey -v \
  -keystore njust.keystore \
  -alias njust \
  -keyalg RSA \
  -keysize 2048 \
  -validity 10000 \
  -storepass YOUR_STORE_PASSWORD \
  -keypass YOUR_KEY_PASSWORD \
  -dname "CN=南京理工大学, OU=学生, O=个人, L=南京, ST=江苏, C=CN"

# 在 buildozer.spec 中取消注释：
# android.release.sign = release
# android.release.keyalias = njust
# android.release.keystore = njust.keystore

# 构建发布版（会提示输入密码）
buildozer android release

# APK 位于 ./bin/njustschedule-0.1-release.apk
```

---

## 安装测试

### 通过 USB 安装

```bash
# 手机开启 USB 调试，连接电脑
adb devices                    # 确认设备已连接
adb install ./bin/njustschedule-0.1-debug.apk
```

### 通过 HTTP 传输

```bash
# 用 Python 启一个简单 HTTP 服务器
python3 -m http.server 8000 -d ./bin/

# 手机浏览器访问 http://电脑IP:8000
# 下载 APK → 安装（允许"未知来源"）
```

### 功能测试清单

- [ ] 打开 APP，显示课表页面
- [ ] 导航到考试页面、设置页面
- [ ] 在设置页面输入学号和密码，点击登录
- [ ] 获取验证码并手动输入
- [ ] 登录成功后，点击刷新课表
- [ ] 切换不同周次，确认课程过滤正确
- [ ] 点击刷新考试安排
- [ ] 确认倒计时天数和小时正确
- [ ] 确认大节行高按小节比例显示
- [ ] 手机连校园网 i-Zijin 或 NJUST VPN
- [ ] 关闭 APP 后重新打开，数据仍存在

---

## 故障排除

### 构建失败

| 问题 | 原因 | 解决 |
|------|------|------|
| `C compiler not found` | 缺少编译工具 | `sudo apt install build-essential` |
| `Android SDK not found` | SDK 路径错误 | 检查 `~/.bashrc` 中的 `ANDROID_HOME` |
| `NDK download failed` | 网络问题 | 手动下载 NDK 25b 放到 `~/.buildozer/android/platform/` |
| `pip install failed for lxml` | 缺少 libxml2 | `sudo apt install libxml2-dev libxslt1-dev` |
| `MemoryError` | 内存不足 | 增加 swap：`sudo fallocate -l 4G /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile` |

### 运行时错误

| 问题 | 原因 | 解决 |
|------|------|------|
| 闪退 | Flask 启动失败 | 检查 `logcat`：`adb logcat \| grep python` |
| 页面空白 | WebView 无法连接 localhost | 确认 Flask 线程正常启动 |
| 登录失败 | 教务系统不可达 | 确认手机连了校园网或 VPN |
| 字体乱码 | 缺少中文字体 | p4a 默认支持 UTF-8，检查模板编码 |

### 查看运行时日志

```bash
# 实时查看应用日志
adb logcat -s python:V

# 过滤错误信息
adb logcat | grep -E "python|ERROR|Traceback"

# 清除旧日志
adb logcat -c
```

---

## 开发模式运行

在 Linux 上开发调试时，不需要每次都构建 APK。

### 桌面模式（Linux）

```bash
# 安装依赖
pip install -r requirements.txt

# 直接运行（Flask + pywebview）
python main.py

# 如果 pywebview 不可用，直接运行 Flask
python app.py
# 浏览器打开 http://127.0.0.1:5000
```

### 手机模式（开发调试）

```bash
# 电脑运行 Flask（绑定 0.0.0.0）
python app.py

# 手机连同一 WiFi
# 浏览器打开 http://电脑IP:5000
# 添加到主屏幕 → PWA 全屏体验
```

---

## 文件清单（构建前）

构建 APK 前，确保以下文件就绪：

```
njust-schedule/
├── .gitignore                  ✓ 已有
├── README.md                   ✓ 已有
├── PLAN.md                     ✓ 已有（本文档）
├── config.py                   ✓ 已有
├── app.py                      ✓ 已有
├── jwc_client.py               ✗ 需修改（OCR 可选导入）
├── main.py                     ✓ 已有
├── start_android.py            ✗ 需新建
├── buildozer.spec              ✗ 需新建
├── build_apk.sh                ✗ 需新建
├── requirements.txt            ✓ 已有
├── requirements_android.txt    ✗ 需新建
├── static/                     ✓ 已有（8 个文件）
└── templates/                  ✓ 已有（4 个文件）
```

---

## 一键构建脚本

**文件：`build_apk.sh`**（新建）

```bash
#!/bin/bash
# ============================================================
# 南理工课表管理 — APK 一键构建脚本
# 适用于 Ubuntu 22.04 LTS
# ============================================================
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  南理工课表管理 — APK 构建工具${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# ---- 检查依赖 ----
echo -e "${YELLOW}[1/6] 检查系统依赖...${NC}"
command -v python3 >/dev/null 2>&1 || { echo "请先安装 python3"; exit 1; }
command -v java >/dev/null 2>&1 || { echo "请先安装 OpenJDK 17"; exit 1; }

# ---- 安装 Python 包 ----
echo -e "${YELLOW}[2/6] 安装 Python 依赖...${NC}"
pip install --user --upgrade buildozer cython virtualenv

# ---- 清理旧构建 ----
echo -e "${YELLOW}[3/6] 清理旧构建...${NC}"
buildozer android clean 2>/dev/null || true
rm -rf .buildozer/android/platform/build
rm -rf bin/

# ---- 构建 APK ----
echo -e "${YELLOW}[4/6] 开始构建 APK...${NC}"
echo "这可能需要 30-60 分钟（首次）或 5-10 分钟（增量）"
buildozer android debug 2>&1 | tee build_$(date +%Y%m%d_%H%M%S).log

# ---- 检查结果 ----
echo -e "${YELLOW}[5/6] 检查构建结果...${NC}"
APK=$(find bin -name "*.apk" 2>/dev/null | head -1)
if [ -z "$APK" ]; then
    echo -e "${RED}构建失败！请检查日志。${NC}"
    exit 1
fi
APK_SIZE=$(du -h "$APK" | cut -f1)
echo -e "${GREEN}APK 构建成功！${NC}"
echo "  文件: $APK"
echo "  大小: $APK_SIZE"

# ---- 可选：安装到设备 ----
echo -e "${YELLOW}[6/6] 安装到设备...${NC}"
read -p "是否安装到连接的 Android 设备？(y/n): " INSTALL
if [ "$INSTALL" = "y" ]; then
    adb install -r "$APK"
    echo -e "${GREEN}安装完成！${NC}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  构建完成${NC}"
echo -e "${GREEN}========================================${NC}"
```

使用方法：
```bash
chmod +x build_apk.sh
./build_apk.sh
```

---

## 总结

| 项目 | 数量 |
|------|------|
| 需要新建的文件 | 3 个（`start_android.py`、`buildozer.spec`、`build_apk.sh`） |
| 需要修改的文件 | 1 个（`jwc_client.py`，OCR 可选导入） |
| 新增依赖文件 | 1 个（`requirements_android.txt`，仅作参考） |
| 前端代码改动 | **0 行**（HTML/CSS/JS 完全不变） |
| 后端代码改动 | **~10 行**（OCR try/except + Android 入口） |
| 首次构建时间 | 30-60 分钟 |
| 增量构建时间 | 5-10 分钟 |
| APK 体积 | 80-120 MB |
