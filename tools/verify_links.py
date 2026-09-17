# -*- coding: utf-8 -*-
"""常用链接功能接线自检: 校验 JS/WXML/WXSS/app.json 的绑定是否完整。"""
import io
import json
import os
import re
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
REL = 'components/settings-view/index.%s'


def rd(rel):
    with io.open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def main():
    js = rd(REL % 'js')
    wxml = rd(REL % 'wxml')
    wxss = rd(REL % 'wxss')
    app = rd('app.json')
    links = rd('utils/links.js')

    try:
        json.loads(app)
        app_ok = True
    except ValueError as e:
        print('  app.json 解析失败: %s' % e)
        app_ok = False

    checks = [
        ('JS 引入 links 模块', "utils/links" in js),
        ('JS 使用 LINK_GROUPS', 'LINK_GROUPS' in js and 'linksData' in js),
        ('JS data 含弹窗状态', all(k in js for k in ('showLinks', 'linkGroups', 'linkTotal'))),
        ('JS onOpenLinks', 'onOpenLinks()' in js),
        ('JS onLinksClose', 'onLinksClose()' in js),
        ('JS onCopyLink', 'onCopyLink(e)' in js),
        ('JS onShowLink', 'onShowLink(e)' in js),
        ('JS 无搜索方法(已移除)', 'onLinkSearch' not in js and 'onLinkClear' not in js),
        ('JS 无搜索字段(已移除)', 'linkKeyword' not in js and 'linkShown' not in js),
        ('WXML 入口 bindtap', 'onOpenLinks' in wxml),
        ('WXML 弹窗 wx:if', 'showLinks' in wxml),
        ('WXML 复制绑定', 'onCopyLink' in wxml),
        ('WXML 长按绑定', 'onShowLink' in wxml),
        ('WXML 无搜索框(已移除)', 'link-search' not in wxml and 'onLinkSearch' not in wxml),
        ('WXML 分组渲染', 'linkGroups' in wxml),
        ('WXSS 链接样式', '.link-row' in wxss),
        ('WXSS 无空规则 .link-list', '.link-list {' not in wxss),
        ('WXSS 无搜索样式(已移除)', 'link-search' not in wxss),
        ('WXML 无嵌套 scroll-view', 'link-scroll' not in wxml),
        ('app.json 合法', app_ok),
        ('app.json 无 links 页残留', 'pages/links' not in app),
        ('无遗留 onGoLinks 跳转', 'onGoLinks' not in js),
    ]

    width = max(len(c[0]) for c in checks) + 2
    bad = 0
    for name, ok in checks:
        if not ok:
            bad += 1
        print('  %-*s %s' % (width, name, 'OK' if ok else 'FAIL'))

    n = len(re.findall(r"\{\s*name:\s*'", links))
    groups = len(re.findall(r"title:\s*'", links))
    print('')
    print('  链接条目: %d 条 / 分组: %d 组' % (n, groups))
    print('  结果: %s' % ('全部通过 ✓' if bad == 0 else '%d 项失败 ✗' % bad))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
