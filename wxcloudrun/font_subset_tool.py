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

FONT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         'static', 'fonts', 'pixel.woff2')


def main() -> int:
    if len(sys.argv) < 3:
        print('usage: python -m wxcloudrun.font_subset_tool <chars_file> <out_woff>',
              file=sys.stderr)
        return 2
    chars_file, out_file = sys.argv[1], sys.argv[2]
    with open(chars_file, encoding='utf-8') as f:
        chars = f.read().strip()
    if not chars:
        return 3
    font = TTFont(FONT_FILE)
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
