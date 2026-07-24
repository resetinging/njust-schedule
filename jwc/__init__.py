"""
南理工强智教务系统客户端 — jwc 包
=================================
JWCClient = AuthMixin + ParserMixin + BaseClient

用法: from jwc import JWCClient
"""
from jwc._base import BaseClient
from jwc._auth import AuthMixin
from jwc._parsers import ParserMixin


class JWCClient(AuthMixin, ParserMixin, BaseClient):
    """南理工教务系统客户端 — 组合所有 Mixin。"""
    pass
