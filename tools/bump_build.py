# -*- coding: utf-8 -*-
"""把 utils/config.js 的 BUILD 标识更新为指定短哈希(不改动行尾与 BOM)。

仓库约定: 每次改动小程序代码后, 用一个独立的 chore 提交把 BUILD 更新为
该功能提交的短哈希 —— 设置页显示的 build 标识用于确认线上版本。

用法:
    python tools/bump_build.py <短哈希> [小程序根目录]
"""
import io
import os
import re
import sys


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    new_hash = sys.argv[1].strip()
    if not re.fullmatch(r'[0-9a-f]{7,40}', new_hash):
        print('短哈希格式不合法: %r' % new_hash)
        return 2

    root = os.path.abspath(sys.argv[2] if len(sys.argv) > 2
                           else os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
    path = os.path.join(root, 'utils', 'config.js')
    raw = io.open(path, 'rb').read()
    if raw.startswith(b'\xef\xbb\xbf'):
        print('文件带 UTF-8 BOM, 终止(避免写入意外字符)')
        return 1

    pat = re.compile(rb"const BUILD = '([0-9a-f]{7,40})'")
    found = pat.findall(raw)
    if len(found) != 1:
        print('BUILD 行匹配 %d 次, 终止' % len(found))
        return 1

    old = found[0].decode()
    if old == new_hash:
        print("BUILD 已是 '%s', 无需修改" % new_hash)
        return 0
    io.open(path, 'wb').write(pat.sub(("const BUILD = '%s'" % new_hash).encode(), raw))
    print("BUILD '%s' → '%s'" % (old, new_hash))
    return 0


if __name__ == '__main__':
    sys.exit(main())
