# -*- coding: utf-8 -*-
"""打印指定元素的祖先链(含 wx:if), 用于排查「弹窗不显示」类问题。"""
import io
import re
import sys

VOID = {'image', 'input', 'import', 'include', 'icon', 'progress', 'slider',
        'switch', 'checkbox', 'radio', 'textarea', 'camera', 'open-data',
        'web-view', 'canvas', 'audio', 'video', 'navigator', 'wxs', 'br'}

path = sys.argv[1]
needle = sys.argv[2] if len(sys.argv) > 2 else 'showLinks'

with io.open(path, encoding='utf-8') as f:
    text = f.read()
clean = re.sub(r'<!--.*?-->', lambda m: ' ' * len(m.group(0)), text, flags=re.S)

stack = []
for m in re.finditer(r'<(/?)([a-zA-Z][\w:-]*)((?:"[^"]*"|\'[^\']*\'|[^>"\'])*?)(/?)>', clean):
    closing, tag, attrs, selfclose = m.group(1), m.group(2), m.group(3), m.group(4)
    line = clean[:m.start()].count('\n') + 1
    if closing:
        while stack and stack[-1][0] != tag:
            stack.pop()
        if stack:
            stack.pop()
        continue
    if needle in attrs:
        print('命中第 %d 行: <%s%s>' % (line, tag, attrs[:70]))
        print('')
        print('祖先链(从外到内):')
        for depth, (t, a, ln) in enumerate(stack):
            cond = ''
            cm = re.search(r'wx:if="([^"]*)"', a)
            if cm:
                cond = '   wx:if=%s' % cm.group(1)
            print('  %s<%s>  (第 %d 行)%s' % ('  ' * depth, t, ln, cond))
        print('  %s<%s>  (第 %d 行)  <-- 目标%s' % ('  ' * len(stack), tag, line,
                                                    '   wx:if=%s' % re.search(r'wx:if="([^"]*)"', attrs).group(1)
                                                    if 'wx:if' in attrs else ''))
        break
    if selfclose or tag in VOID:
        continue
    stack.append((tag, attrs, line))
