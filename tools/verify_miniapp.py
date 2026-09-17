# -*- coding: utf-8 -*-
"""小程序完整性自检: 全部 JS 可解析 / app.json 页面存在 / 无悬空引用。"""
import io
import json
import os
import re
import subprocess
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
SKIP_DIRS = {'node_modules', '.git', 'miniprogram_npm', '.idea'}


def walk(ext):
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(ext):
                yield os.path.join(base, f)


def rel(p):
    return os.path.relpath(p, ROOT).replace('\\', '/')


def main():
    bad = 0

    # 1) 全部 JS 语法
    js_files = sorted(walk('.js'))
    print('1) JS 语法检查 (%d 个文件)' % len(js_files))
    for p in js_files:
        r = subprocess.run(['node', '--check', p], capture_output=True)
        if r.returncode != 0:
            bad += 1
            print('   FAIL %s' % rel(p))
            print('        ' + r.stderr.decode('utf-8', 'replace').strip().splitlines()[0])
    if bad == 0:
        print('   全部通过 ✓')

    # 2) app.json 页面文件存在
    print('2) app.json 页面注册')
    app_path = os.path.join(ROOT, 'app.json')
    with io.open(app_path, encoding='utf-8') as f:
        app = json.load(f)
    missing = 0
    for page in app.get('pages', []):
        ok = all(os.path.exists(os.path.join(ROOT, page + ext)) for ext in ('.js', '.wxml'))
        if not ok:
            missing += 1
            print('   缺失: %s' % page)
    bad += missing
    if missing == 0:
        print('   %d 个页面全部存在 ✓' % len(app.get('pages', [])))
    print('   tabBar: %s' % ('有' if 'tabBar' in app else '无(自定义 custom-tab-bar)'))

    # 3) 悬空引用扫描
    print('3) 悬空引用扫描')
    pattern = re.compile(r'pages/links|onGoLinks')
    hits = 0
    for ext in ('.js', '.wxml', '.wxss', '.json'):
        for p in walk(ext):
            with io.open(p, encoding='utf-8', errors='replace') as f:
                txt = f.read()
            for m in pattern.finditer(txt):
                hits += 1
                line = txt[:m.start()].count('\n') + 1
                print('   %s:%d  %s' % (rel(p), line, txt.splitlines()[line - 1].strip()[:80]))
    bad += hits
    if hits == 0:
        print('   无 pages/links 或 onGoLinks 残留 ✓')

    # 4) 剪贴板只写不读
    # 约束: 本项目不得读取用户剪贴板(getClipboardData 属微信隐私接口, 需要用户授权,
    # 且与功能无关)。常用链接只做"写入"(setClipboardData 复制), 不读回任何内容。
    print('4) 剪贴板只写不读')
    read_api = re.compile(r'getClipboardData|readClipboard|Clipboard\.getData|onClipboard')
    reads = 0
    writes = 0
    for ext in ('.js', '.wxml'):
        for p in walk(ext):
            if os.sep + 'tools' + os.sep in p:
                continue
            with io.open(p, encoding='utf-8', errors='replace') as f:
                txt = f.read()
            for m in read_api.finditer(txt):
                reads += 1
                line = txt[:m.start()].count('\n') + 1
                print('   ✗ 读取剪贴板: %s:%d  %s' % (rel(p), line, txt.splitlines()[line - 1].strip()[:80]))
            writes += txt.count('setClipboardData')
    bad += reads
    if reads == 0:
        print('   无任何剪贴板读取调用 ✓ (写入/复制 %d 处, 属功能所需)' % writes)

    # 5) 资源体积
    print('5) 体积')
    total = 0
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            total += os.path.getsize(os.path.join(base, f))
    print('   %.0f KB / 2048 KB 上限' % (total / 1024.0))

    print('')
    print('结果: %s' % ('全部通过 ✓' if bad == 0 else '%d 处问题 ✗' % bad))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
