# -*- coding: utf-8 -*-
"""WXML 结构自检: 标签配对 / 属性引号 / 常见语法问题。"""
import io
import os
import re
import sys

# 自闭合或空元素(无需闭合标签)
VOID = {'image', 'input', 'import', 'include', 'icon', 'progress', 'slider',
        'switch', 'checkbox', 'radio', 'textarea', 'camera', 'live-player',
        'live-pusher', 'open-data', 'web-view', 'canvas', 'audio', 'video',
        'voip-room', 'ad', 'official-account', 'navigator', 'wxs'}


def check(path):
    with io.open(path, encoding='utf-8') as f:
        text = f.read()
    # 去掉注释
    clean = re.sub(r'<!--.*?-->', lambda m: ' ' * len(m.group(0)), text, flags=re.S)
    problems = []
    stack = []
    for m in re.finditer(r'<(/?)([a-zA-Z][\w:-]*)((?:"[^"]*"|\'[^\']*\'|[^>"\'])*?)(/?)>', clean):
        closing, tag, attrs, selfclose = m.group(1), m.group(2), m.group(3), m.group(4)
        line = clean[:m.start()].count('\n') + 1
        if closing:
            if not stack:
                problems.append((line, '多余的闭合标签 </%s>' % tag))
            elif stack[-1][0] != tag:
                problems.append((line, '</%s> 与未闭合的 <%s>(第 %d 行) 不匹配'
                                 % (tag, stack[-1][0], stack[-1][1])))
                stack.pop()
            else:
                stack.pop()
        elif selfclose or tag in VOID:
            continue
        else:
            stack.append((tag, line))
    for tag, line in stack:
        problems.append((line, '<%s> 未闭合' % tag))

    # 属性引号配对(粗检): 行内出现奇数个双引号
    for i, raw in enumerate(text.split('\n'), 1):
        if raw.count('"') % 2 == 1 and '{{' not in raw:
            problems.append((i, '属性引号不成对: %s' % raw.strip()[:70]))
    return problems


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    targets = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ('node_modules', 'miniprogram_npm', '.git')]
        for f in files:
            if f.endswith('.wxml'):
                targets.append(os.path.join(base, f))
    bad = 0
    for p in sorted(targets):
        rel = os.path.relpath(p, root).replace('\\', '/')
        probs = check(p)
        if probs:
            bad += len(probs)
            print('%s' % rel)
            for line, msg in probs:
                print('    第 %d 行: %s' % (line, msg))
    print('')
    if bad == 0:
        print('WXML 结构检查: %d 个文件全部通过 ✓' % len(targets))
    else:
        print('WXML 结构检查: %d 处问题 ✗' % bad)
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
