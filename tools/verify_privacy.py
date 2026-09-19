# -*- coding: utf-8 -*-
"""隐私合规自检: 代码里出现的每个微信接口都必须被"显式判定", 不允许静默放过。

为什么这样设计
--------------
微信自 2023-10-17 起强制启用隐私校验(基础库 2.32.3+, 与 app.json 是否配置
__usePrivacyCheck__ 无关)。规则是: 代码调用了某个隐私接口, 但《用户隐私保护指引》
未声明对应信息类型 → **该接口在线上会直接失败**, 并且代码审核会被驳回。
例: setClipboardData:fail api scope is not declared in the privacy agreement

所以真正的风险不是"当前代码有没有问题", 而是"下次新增接口时没人记得改指引"。
本脚本把每个 wx.* 调用强制归入三类之一:

  1) 隐私接口      -> 必须出现在指引的 declared-privacy-keys 里
  2) 已判定非隐私  -> 必须在下方的 NON_PRIVACY 白名单里(带理由)
  3) 未判定        -> **失败**, 要求人工确认后归类(若是隐私接口, 同时改指引 + 后台配置)

用法:
    python tools/verify_privacy.py [小程序根目录]
"""
import io
import json
import os
import re
import sys

# ── 信息类型 → 隐私接口(依微信《小程序用户隐私保护指引内容介绍》整理) ──
PRIVACY_APIS = {
    'Clipboard': ['wx.getClipboardData', 'wx.setClipboardData'],
    'Location': ['wx.getLocation', 'wx.chooseLocation', 'wx.choosePoi',
                 'wx.getFuzzyLocation', 'wx.onLocationChange',
                 'wx.startLocationUpdate', 'wx.startLocationUpdateBackground'],
    'Album': ['wx.chooseImage', 'wx.chooseMedia', 'wx.chooseVideo',
              'wx.saveImageToPhotosAlbum', 'wx.saveVideoToPhotosAlbum'],
    'Camera': ['wx.createCameraContext'],
    'Record': ['wx.getRecorderManager', 'wx.startRecord', 'wx.joinVoipChat',
               'wx.createMediaRecorder'],
    'UserInfo': ['wx.getUserProfile', 'wx.getUserInfo'],
    'PhoneNumber': [],
    'Contact': ['wx.chooseContact'],
    'Invoice': ['wx.chooseInvoice', 'wx.chooseInvoiceTitle'],
    'RunData': ['wx.getWeRunData'],
    'Bluetooth': ['wx.openBluetoothAdapter', 'wx.startBluetoothDevicesDiscovery',
                  'wx.getBluetoothDevices', 'wx.getConnectedBluetoothDevices',
                  'wx.createBLEConnection', 'wx.startBeaconDiscovery', 'wx.getBeacons'],
    'Calendar': ['wx.addPhoneCalendar', 'wx.addPhoneRepeatCalendar'],
    'DeviceInfo': ['wx.getSystemInfo', 'wx.getSystemInfoSync', 'wx.getDeviceInfo'],
    'Address': ['wx.chooseAddress'],
    'Sensor': ['wx.startAccelerometer', 'wx.onAccelerometerChange',
               'wx.startGyroscope', 'wx.onGyroscopeChange',
               'wx.startCompass', 'wx.onCompassChange'],
}

# ── 组件级隐私用法(写在 WXML 里, 不走 wx.* 调用) ──
WXML_PRIVACY = [
    (r'open-type\s*=\s*"getPhoneNumber"', 'PhoneNumber'),
    (r'open-type\s*=\s*"getRealtimePhoneNumber"', 'PhoneNumber'),
    (r'open-type\s*=\s*"chooseAvatar"', 'UserInfo'),
    (r'type\s*=\s*"nickname"', 'UserInfo'),
    (r'<camera\b', 'Camera'),
    (r'<live-pusher\b', 'Record'),
    (r'<voip-room\b', 'Camera'),
]

# ── 已判定为非隐私的接口(本项目实际用到; 新增接口必须显式加进来并写明理由) ──
NON_PRIVACY = {
    'cloud': '调用开发者自己的后端(微信云托管 callContainer)',
    'request': '调用开发者自己的后端接口',
    'downloadFile': '下载学校公开的校历图片',
    'getFileSystemManager': '读写本机缓存文件(校历图片), 不访问相册',
    'previewImage': '全屏预览已下载的校历图片, 不读取用户相册',
    'env': 'wx.env.USER_DATA_PATH 本机路径常量',
    'getStorageSync': '读取本机缓存',
    'setStorageSync': '写入本机缓存',
    'removeStorageSync': '清除本机缓存',
    'getStorageInfoSync': '查询本机缓存用量',
    'getWindowInfo': '仅取视口尺寸/安全区用于布局, 不含设备标识',
    'showLoading': '界面加载提示',
    'hideLoading': '关闭界面加载提示',
    'showToast': '界面轻提示',
    'showModal': '界面弹窗',
    'navigateTo': '页面跳转',
    'navigateBack': '页面返回',
    'reLaunch': '重启到指定页面',
}

READ_APIS = ['wx.getClipboardData', 'readClipboard', 'Clipboard.getData']

GUIDELINE = os.path.join('docs', 'privacy-guideline.md')
MARKER = re.compile(r'<!--\s*declared-privacy-keys\s*:\s*([^>]*?)\s*-->')
SKIP_DIRS = {'node_modules', 'miniprogram_npm', '.git', 'tools', 'docs'}


def strip_js_comments(src):
    """移除 JS 注释, 保留字符串字面量(避免误伤 URL 里的 //)."""
    out = []
    i, n = 0, len(src)
    quote = None
    while i < n:
        ch = src[i]
        if quote:
            out.append(ch)
            if ch == '\\' and i + 1 < n:
                out.append(src[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ('"', "'", '`'):
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == '/' and i + 1 < n:
            if src[i + 1] == '/':
                while i < n and src[i] != '\n':
                    i += 1
                continue
            if src[i + 1] == '*':
                i += 2
                while i + 1 < n and not (src[i] == '*' and src[i + 1] == '/'):
                    i += 1
                i += 2
                continue
        out.append(ch)
        i += 1
    return ''.join(out)


def collect(root, exts):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(exts):
                yield os.path.join(base, f)


def api_to_type():
    m = {}
    for key, apis in PRIVACY_APIS.items():
        for a in apis:
            m[a] = key
    return m


def scan(root):
    """返回 (隐私命中, 非隐私命中, 未判定命中), 结构 {名称: {相对路径: 次数}}"""
    a2t = api_to_type()
    priv, nonpriv, unknown = {}, {}, {}
    for p in collect(root, ('.js', '.wxml')):
        with io.open(p, encoding='utf-8', errors='replace') as f:
            raw = f.read()
        src = strip_js_comments(raw) if p.endswith('.js') else re.sub(r'<!--.*?-->', '', raw, flags=re.S)
        rel = os.path.relpath(p, root).replace('\\', '/')
        for m in re.finditer(r'\bwx\.([A-Za-z_][A-Za-z0-9_]*)', src):
            name = m.group(1)
            api = 'wx.' + name
            if api in a2t:
                bucket, key = priv, api
            elif name in NON_PRIVACY:
                bucket, key = nonpriv, name
            else:
                bucket, key = unknown, api
            d = bucket.setdefault(key, {})
            d[rel] = d.get(rel, 0) + 1
        if p.endswith('.wxml'):
            for pat, key in WXML_PRIVACY:
                cnt = len(re.findall(pat, src))
                if cnt:
                    # 用裸信息类型作键(与 declared-privacy-keys 同一套词汇),
                    # 否则已声明的组件用法会被同时报成"缺失"和"多余"
                    d = priv.setdefault(key, {})
                    loc = rel + '(组件用法)'
                    d[loc] = d.get(loc, 0) + cnt
    return priv, nonpriv, unknown


def declared_keys(root):
    path = os.path.join(root, GUIDELINE)
    if not os.path.exists(path):
        return None
    with io.open(path, encoding='utf-8', errors='replace') as f:
        m = MARKER.search(f.read())
    if not m:
        return None
    return [k.strip() for k in m.group(1).split(',') if k.strip()]


def main():
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1
                           else os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
    print('小程序根目录: %s\n' % root)
    bad = 0

    priv, nonpriv, unknown = scan(root)
    a2t = api_to_type()

    print('1) 隐私接口(必须已在指引中声明)')
    if not priv:
        print('   无')
    for api in sorted(priv):
        label = a2t.get(api, api)
        locs = ', '.join('%s×%d' % (k, v) for k, v in sorted(priv[api].items()))
        print('   %-24s [%s]  %s' % (api, label, locs))

    print('\n2) 已判定为非隐私(%d 种, 见 NON_PRIVACY 白名单)' % len(nonpriv))
    for name in sorted(nonpriv):
        print('   %-22s %s' % (name, NON_PRIVACY.get(name, '未填理由')))

    print('\n3) 未判定接口(必须人工归类)')
    if unknown:
        bad += len(unknown)
        for name in sorted(unknown):
            locs = ', '.join('%s×%d' % (k, v) for k, v in sorted(unknown[name].items()))
            print('   ✗ %-20s %s' % (name, locs))
        print('   → 若属隐私接口: 加入 PRIVACY_APIS + 指引 declared-privacy-keys + 后台勾选;')
        print('     若确属非隐私: 加入 NON_PRIVACY 并写明理由。')
    else:
        print('   无(所有接口都已显式判定) ✓')

    print('\n4) 与《用户隐私保护指引》比对')
    declared = declared_keys(root)
    if declared is None:
        bad += 1
        print('   ✗ 未找到 %s 或其中的 <!-- declared-privacy-keys: ... --> 标记' % GUIDELINE)
    else:
        code_keys = sorted(set(a2t.get(a, a) for a in priv))
        print('   指引声明: %s' % (', '.join(declared) if declared else '(无)'))
        print('   代码调用: %s' % (', '.join(code_keys) if code_keys else '(无)'))
        missing = [k for k in code_keys if k not in declared]
        extra = [k for k in declared if k not in code_keys]
        for k in missing:
            bad += 1
            print('   ✗ 代码调用了 %s 但指引未声明 → 线上该接口会失败, 且代码审核会被驳回' % k)
        for k in extra:
            print('   ⚠ 指引声明了 %s 但代码未调用 → 多余声明同样有审核风险' % k)
        if not missing and not extra:
            print('   一致 ✓')

    print('\n5) 剪切板只写不读')
    reads = []
    for p in collect(root, ('.js', '.wxml')):
        with io.open(p, encoding='utf-8', errors='replace') as f:
            src = strip_js_comments(f.read())
        for api in READ_APIS:
            if api in src:
                reads.append((api, os.path.relpath(p, root).replace('\\', '/')))
    writes = 0
    for api, locs in priv.items():
        if 'setClipboardData' in api:
            writes += sum(locs.values())
    if reads:
        bad += len(reads)
        for api, rel in reads:
            print('   ✗ 读取剪贴板: %s (%s)' % (api, rel))
    else:
        print('   无读取调用 ✓ (写入 %d 处)' % writes)

    print('\n6) app.json 隐私相关配置')
    app_p = os.path.join(root, 'app.json')
    if os.path.exists(app_p):
        with io.open(app_p, encoding='utf-8', errors='replace') as f:
            app = json.loads(f.read())
        for key in ('requiredPrivateInfos', 'permission', '__usePrivacyCheck__',
                    'requiredBackgroundModes'):
            val = app.get(key)
            print('   %-24s %s' % (key, '未配置' if val is None
                                   else json.dumps(val, ensure_ascii=False)))
        if app.get('requiredPrivateInfos'):
            print('   ⚠ 存在 requiredPrivateInfos → 其中每个接口都需声明对应信息类型')

    print('\n结果: %s' % ('全部通过 ✓' if bad == 0 else '%d 处问题 ✗' % bad))
    if bad:
        print('提示: 发布前必须处理完以上问题, 否则线上调用会直接失败。')
        print('      流程: 改代码 → 改 docs/privacy-guideline.md → 更新公众平台隐私保护指引')
        print('            → 重新提交代码审核 → 发布上线(配置需重新发布才生效)。')
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
