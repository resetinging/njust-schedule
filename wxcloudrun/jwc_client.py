# -*- coding: utf-8 -*-
"""教务客户端门面(Phase 2: 按域拆到 wxcloudrun/jwc/)。

对外接口与旧 jwc_client.py 完全一致: JWCClient/CLASSROOM_SLOTS/
ClassroomBorrowError/URL_* 等符号在 common.py 定义, 在此 re-export。
"""
from wxcloudrun.jwc.common import *  # noqa: F401,F403
from wxcloudrun.jwc.common import (  # noqa: F401
    _DedupCookieJar, _encrypt_sso_password, _dedupe_schedule_courses)
from wxcloudrun.jwc.base import BaseMixin
from wxcloudrun.jwc.login import LoginMixin
from wxcloudrun.jwc.core import CoreMixin
from wxcloudrun.jwc.schedule import ScheduleMixin
from wxcloudrun.jwc.exams import ExamsMixin
from wxcloudrun.jwc.utils import UtilsMixin
from wxcloudrun.jwc.eval import EvalMixin
from wxcloudrun.jwc.grades import GradesMixin
from wxcloudrun.jwc.cet import CetMixin
from wxcloudrun.jwc.freeclass import FreeClassMixin
from wxcloudrun.jwc.qrlogin import QrLoginMixin


class JWCClient(BaseMixin, LoginMixin, CoreMixin, ScheduleMixin, ExamsMixin,
                UtilsMixin, EvalMixin, GradesMixin, CetMixin, FreeClassMixin,
                QrLoginMixin):
    """教务客户端: 各域 mixin 组合(方法实现见 wxcloudrun/jwc/*)。"""
