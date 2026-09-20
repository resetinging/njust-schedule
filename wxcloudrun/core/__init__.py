# -*- coding: utf-8 -*-
"""wxcloudrun 基础设施层。

从 views.py 拆出的进程内状态与通用能力:
  - cache:     查询接口进程内 TTL 缓存
  - sessions:  多用户会话池 + 验证码临时会话
  - pool:      教务访问池(实例锁 + 全局并发信号量)
  - web:       请求级日志(rid/慢请求告警)注册

views.py 会显式 re-export 这些符号, 保持 views.<name> 旧引用继续可用。
"""
