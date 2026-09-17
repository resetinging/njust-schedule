# -*- coding: utf-8 -*-
"""隐私合规自检: 比对代码实际调用的隐私接口 与 《用户隐私保护指引》声明的信息类型。

微信自 2023-10-17 起强制启用隐私校验(与 app.json 是否配置 __usePrivacyCheck__ 无关):
代码调用了隐私接口但指引未声明对应信息类型, 该接口在线上会直接失败
(例: setClipboardData:fail api scope is not declared in the privacy agreement)。

本脚本把"改代码要同步改指引"变成会失败的检查:
  1. 扫描 .js/.wxml(先剥离注释, 避免注释里的接口名误报), 识别实际调用的隐私接口
  2. 与 docs/privacy-guideline.md 顶部 <!-- declared-privacy-keys: ... --> 比对
  3. 代码用到但未声明 → 失败; 声明了但代码没用 → 告警(多余声明同样有审核风险)
  4. 额外校验「剪切板只写不读」

用法:
    python tools/verify_privacy.py [小程序根目录]
"""
import io
import os
import re
import sys

# 信息类型 → 隐私接口(按微信「用户信息与使用接口对应关系」整理)
PRIVACY_APIS = {
    'Clipboard': {
        'label': '剪切板',
        'apis': ['wx.getClipboardData', 'wx.setClipboardData'],
    },
    'Location': {
        'label': '位置信息',
        'apis': ['wx.getLocation', 'wx.chooseLocation', 'wx.choosePoi',
                 'wx.onLocationChange', 'wx.startLocationUpdate',
                 'wx.startLocationUpdateBackground'],
    },
    'Album': {
        'label': '相册(图片/视频)',
        'apis': ['wx.chooseImage', 'wx.chooseMedia', 'wx.chooseVideo',
                 'wx.saveImageToPhotosAlbum', 'wx.saveVideoToPhotosAlbum'],
    },
    'Camera': {
        'label': '摄像头',
        'apis': ['wx.createCameraContext', '<camera'],
    },
    'Record': {
        'label': '麦克风',
        'apis': ['wx.getRecorderManager', 'wx.startRecord', 'wx.joinVoipChat'],
    },
    'UserInfo': {
        'label': '微信昵称、头像',
        'apis': ['wx.getUserProfile', 'wx.getUserInfo',
                 'open-type="chooseAvatar"', "open-type='chooseAvatar'",
                 'type="nickname"', "type='nickname'"],
    },
    'PhoneNumber': {
        'label': '手机号',
        'apis': ['open-type="getPhoneNumber"', "open-type='getPhoneNumber'",
                 'open-type="getRealtimePhoneNumber"', "open-type='getRealtimePhoneNumber'"],
    },
    'Contact': {'label': '通讯录', 'apis': ['wx.chooseContact']},
    'Invoice': {'label': '发票', 'apis': ['wx.chooseInvoice', 'wx.chooseInvoiceTitle']},
    'RunData': {'label': '微信运动步数', 'apis': ['wx.getWeRunData']},
    'Bluetooth': {
        'label': '蓝牙',
        'apis': ['wx.openBluetoothAdapter', 'wx.startBluetoothDevicesDiscovery',
                 'wx.getBluetoothDevices', 'wx.createBLEConnection',
                 'wx.startBeaconDiscovery'],
    },
    'Calendar': {
        'label': '日历(仅写入)',
        'apis': ['wx.addPhoneCalendar', 'wx.addPhoneRepeatCalendar'],
    },
    'DeviceInfo': {
        'label': '设备信息',
        'apis': ['wx.getSystemInfo', 'wx.getSystemInfoSync', 'wx.getDeviceInfo'],
    },
    'Address': {'label': '地址', 'apis': ['wx.chooseAddress']},
}

READ_APIS = ['wx.getClipboardData', 'readClipboard', 'Clipboard.getData']

GUIDELINE = os.path.join('docs', 'privacy-guideline.md')
MARKER = re.compile(r'<!--\s*declared-privacy-keys\s*:\s*([^>]*?)\s*-->')
SKIP_DIRS = {'node_modules', 'miniprogram_npm', '.git', 'tools', 'docs'}


def strip_js_comments(src):
    """移除 JS 注释, 保留字符串字面量内容(避免误伤 URL 里的 //)."""
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


def collect_files(root, exts):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(exts):
                yield os.path.join(base, f)


def scan(root):
    """返回 {privacy_key: [(接口, 相对路径, 次数)]}"""
    found = {}
    for p in collect_files(root, ('.js', '.wxml')):
        with io.open(p, encoding='utf-8', errors='replace') as f:
            raw = f.read()
        src = strip_js_comments(raw) if p.endswith('.js') else re.sub(r'<!--.*?-->', '', raw, flags=re.S)
        rel = os.path.relpath(p, root).replace('\\', '/')
        for key, meta in PRIVACY_APIS.items():
            for api in meta['apis']:
                cnt = src.count(api)
                if cnt:
                    found.setdefault(key, []).append((api, rel, cnt))
    return found


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

    found = scan(root)
    print('1) 代码实际调用的隐私接口')
    if not found:
        print('   无(未调用任何隐私接口)')
    for key in sorted(found):
        label = PRIVACY_APIS[key]['label']
        print('   %-12s %s' % (key, label))
        for api, rel, cnt in sorted(found[key]):
            print('        %-26s %s ×%d' % (api, rel, cnt))

    declared = declared_keys(root)
    print('\n2) 与《用户隐私保护指引》比对')
    if declared is None:
        bad += 1
        print('   ✗ 未找到声明标记: %s 中的 <!-- declared-privacy-keys: ... -->' % GUIDELINE)
    else:
        print('   指引声明: %s' % (', '.join(declared) if declared else '(无)'))
        print('   代码调用: %s' % (', '.join(sorted(found)) if found else '(无)'))
        missing = [k for k in found if k not in declared]
        extra = [k for k in declared if k not in found]
        if missing:
            bad += len(missing)
            for k in missing:
                print('   ✗ 代码调用了 %s(%s) 但指引未声明 → 线上该接口会失败, '
                      '且代码审核会被驳回' % (k, PRIVACY_APIS.get(k, {}).get('label', '?')))
        if extra:
            for k in extra:
                print('   ⚠ 指引声明了 %s 但代码未调用 → 多余声明同样有审核风险'
                      % k)
        if not missing and not extra:
            print('   一致 ✓')

    print('\n3) 剪切板只写不读')
    reads = []
    for p in collect_files(root, ('.js', '.wxml')):
        with io.open(p, encoding='utf-8', errors='replace') as f:
            src = strip_js_comments(f.read())
        for api in READ_APIS:
            if api in src:
                reads.append((api, os.path.relpath(p, root).replace('\\', '/')))
    writes = 0
    for api, _rel, cnt in found.get('Clipboard', []):
        if 'setClipboardData' in api:
            writes += cnt
    if reads:
        bad += len(reads)
        for api, rel in reads:
            print('   ✗ 读取剪贴板: %s (%s)' % (api, rel))
    else:
        print('   无读取调用 ✓ (写入 %d 处)' % writes)

    print('\n结果: %s' % ('全部通过 ✓' if bad == 0 else '%d 处问题 ✗' % bad))
    if bad:
        print('提示: 改动隐私相关代码后, 需同步更新 docs/privacy-guideline.md 的信息类型表')
        print('      与 declared-privacy-keys 标记, 并在微信公众平台更新隐私保护指引后重新提审。')
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
