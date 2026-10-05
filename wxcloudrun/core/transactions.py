# -*- coding: utf-8 -*-
"""数据库事务边界。

Repository 负责组成一个完整的数据快照，事务由这里统一提交或回滚。
API 层不应在批量写入过程中自行 commit，避免出现先删后插的半成品状态。
"""
from contextlib import contextmanager

from wxcloudrun import db


@contextmanager
def transaction():
    """提交一个业务事务；任意异常都会回滚当前 SQLAlchemy 会话。"""
    try:
        yield db.session
        db.session.commit()
    except BaseException:
        db.session.rollback()
        raise
