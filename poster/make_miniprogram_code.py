# -*- coding: utf-8 -*-
"""生成小程序码，直接存到 poster/promo/miniprogram-code.png（图文宣传尾卡用）。

用法（AppSecret 只放环境变量，不要写进代码/提交到仓库）：
    set WX_APPSECRET=你的AppSecret
    .venv\\Scripts\\python.exe poster\\make_miniprogram_code.py

可选参数：
    --page pages/main/main   扫码进入的页面（默认首页）
    --scene a=1              带参场景值，便于统计渠道（默认空）
    --env release            开发版 develop / 体验版 trial / 正式版 release

说明：走 getwxacodeunlimit（小程序码，不限数量）；AppID 自动从
.miniapp/project.config.json 读取。生成的图片微信扫一扫可直接打开小程序。
"""
import argparse
import json
import os
import sys

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "promo", "miniprogram-code.png")


def appid() -> str:
    cfg = os.path.join(ROOT, ".miniapp", "project.config.json")
    with open(cfg, encoding="utf-8") as f:
        return json.load(f).get("appid", "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", default="pages/main/main")
    ap.add_argument("--scene", default="")
    ap.add_argument("--env", default="release",
                    choices=["release", "trial", "develop"])
    args = ap.parse_args()

    secret = os.environ.get("WX_APPSECRET", "").strip()
    aid = appid()
    if not secret:
        print("缺少 AppSecret：请先 set WX_APPSECRET=...（公众平台 → 开发管理 → 开发设置）")
        return 2
    if not aid:
        print("未读到 AppID（.miniapp/project.config.json）")
        return 2

    r = requests.get("https://api.weixin.qq.com/cgi-bin/token",
                     params={"grant_type": "client_credential",
                             "appid": aid, "secret": secret}, timeout=20)
    tok = r.json()
    if "access_token" not in tok:
        print("获取 access_token 失败：", tok)
        return 1

    body = {"page": args.page, "width": 430, "check_path": False,
            "env_version": args.env}
    if args.scene:
        body["scene"] = args.scene
    r2 = requests.post("https://api.weixin.qq.com/wxa/getwxacodeunlimit",
                       params={"access_token": tok["access_token"]},
                       json=body, timeout=30)
    ctype = (r2.headers.get("Content-Type") or "").lower()
    if not ctype.startswith("image/"):
        print("生成失败：", r2.text[:300])
        return 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "wb") as f:
        f.write(r2.content)
    print(f"已生成小程序码：{OUT}（{len(r2.content)} 字节）")
    print("接着重跑 poster\\..\\demo-server\\make_promo.py 即可嵌入尾卡")
    return 0


if __name__ == "__main__":
    sys.exit(main())
