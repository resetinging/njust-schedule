# -*- coding: utf-8 -*-
"""独立的字体子集生成工具(命令行)。

为什么要单独起进程: 子集生成是纯 CPU 活(fontTools 解析 woff2 + 裁剪),
放在 Flask 进程里会持有 GIL, 把 /api/status 这类轻接口一起拖慢。
用子进程跑, 主进程只等结果, 互不影响。

用法: python -m wxcloudrun.font_subset_tool <chars_file> <out_woff>
"""
import base64
import os
import sys

from fontTools import subset as ft_subset
from fontTools.ttLib import TTFont

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'fonts')


def font_path(key: str) -> str:
    """字体 key → 源文件(候选 woff2/ttf/otf 各取第一个存在的)"""
    for ext in ('.woff2', '.ttf', '.otf'):
        p = os.path.join(FONT_DIR, f'{key}{ext}')
        if os.path.exists(p):
            return p
    return os.path.join(FONT_DIR, 'pixel.woff2')


def main() -> int:
    if len(sys.argv) < 3:
        print('usage: python font_subset_tool.py <chars_file> <out_woff> [font_key]',
              file=sys.stderr)
        return 2
    chars_file, out_file = sys.argv[1], sys.argv[2]
    key = sys.argv[3] if len(sys.argv) > 3 else 'pixel'
    with open(chars_file, encoding='utf-8') as f:
        chars = f.read().strip()
    if not chars:
        return 3
    src = font_path(key)
    if not os.path.exists(src):
        print(f'font not found: {key}', file=sys.stderr)
        return 4
    font = TTFont(src)
    opts = ft_subset.Options()
    opts.flavor = 'woff'
    opts.layout_features = ['*']
    subsetter = ft_subset.Subsetter(options=opts)
    subsetter.populate(text=chars)
    subsetter.subset(font)
    font.save(out_file)
    with open(out_file, 'rb') as src:
        data = base64.b64encode(src.read()).decode('ascii')
    with open(out_file + '.b64', 'w', encoding='ascii') as f:
        f.write(data)
    return 0


if __name__ == '__main__':
    sys.exit(main())
