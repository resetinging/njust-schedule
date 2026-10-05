# -*- coding: utf-8 -*-
"""数据库 repository 层。

旧版调用方仍可从 wxcloudrun.dao 使用兼容门面；新业务代码优先直接依赖
具体 repository，避免把所有表的查询和事务挤在一个文件中。
"""
