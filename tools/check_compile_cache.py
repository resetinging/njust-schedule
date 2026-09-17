# -*- coding: utf-8 -*-
"""核查开发者工具当前编译产物是否包含指定源码关键字。

用途: 判断「改了代码但界面没生效」是代码问题还是工具缓存/编译状态问题。
自动发现本机开发者工具的编译缓存目录, 不依赖硬编码路径。

用法:
    python check_compile_cache.py                          # 列出最新编译产物
    python check_compile_cache.py onOpenLinks linkShown    # 在最新产物中查关键字
    python check_compile_cache.py --all showLinks          # 只搜最新产物是默认, --all 搜全部
"""
import glob
import io
import os
import sys
import time

CACHE_GLOB = os.path.join(
    os.environ.get('USERPROFILE', os.path.expanduser('~')),
    'AppData', 'Local', '微信开发者工具', 'User Data', '*',
    'WeappCache', 'WeappCompileCache')

MAX_BYTES = 20 * 1024 * 1024


def find_cache_dirs():
    dirs = [d for d in glob.glob(CACHE_GLOB) if os.path.isdir(d)]
    return dirs


def newest_files(cache_dirs, limit=8):
    files = []
    for d in cache_dirs:
        for p in glob.glob(os.path.join(d, '*', '*')):
            if os.path.isfile(p) and not p.endswith('.json') and os.path.getsize(p) < MAX_BYTES:
                files.append(p)
    files.sort(key=os.path.getmtime, reverse=True)
    return files[:limit]


def main():
    args = [a for a in sys.argv[1:] if a != '--all']
    search_all = '--all' in sys.argv[1:]
    keywords = [a for a in args if not a.startswith('--')]

    dirs = find_cache_dirs()
    if not dirs:
        print('未找到开发者工具编译缓存目录:')
        print('  ' + CACHE_GLOB)
        print('请确认已安装微信开发者工具并至少编译过一次项目。')
        return 1

    print('编译缓存目录(%d 个):' % len(dirs))
    for d in dirs:
        print('  ' + d)

    files = newest_files(dirs, limit=len(dirs) * 40 if search_all else 8)
    if not files:
        print('缓存目录为空(项目可能尚未编译)。')
        return 1

    print('\n最新编译产物:')
    for p in files[:8]:
        ts = time.strftime('%m-%d %H:%M:%S', time.localtime(os.path.getmtime(p)))
        print('  %s  %8.1f KB  %s' % (ts, os.path.getsize(p) / 1024.0, os.path.basename(p)))

    if not keywords:
        print('\n(未指定关键字; 例如: python check_compile_cache.py onOpenLinks)')
        return 0

    print('\n关键字检索:')
    targets = files if search_all else files[:1]
    for kw in keywords:
        hits = []
        for p in targets:
            with io.open(p, encoding='utf-8', errors='replace') as f:
                n = f.read().count(kw)
            if n:
                hits.append('%s×%d' % (os.path.basename(p)[:8], n))
        print('  %-24s %s' % (kw, ', '.join(hits) if hits else '未找到'))

    print('\n提示: 产物时间早于源文件修改时间 → 说明该次改动还没进编译, 需要完整重新编译。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
