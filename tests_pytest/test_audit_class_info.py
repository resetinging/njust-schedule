# -*- coding: utf-8 -*-
import os

os.environ.setdefault(
    "SQLALCHEMY_DATABASE_URI",
    "sqlite:///:memory:",
)

from sqlalchemy import String, Text  # noqa: E402
from sqlalchemy.dialects.mysql import LONGTEXT  # noqa: E402

from wxcloudrun import (  # noqa: E402
    _SCHEMA_MIGRATIONS, _audit_class_info_text_statements,
    app, dao,
)
from wxcloudrun.model import AuditCourse, AuditFavorite  # noqa: E402


def test_audit_class_info_columns_are_text():
    assert isinstance(AuditCourse.__table__.c.class_info.type, Text)
    assert isinstance(AuditFavorite.__table__.c.class_info.type, Text)


def test_audit_class_info_text_migration_is_registered():
    versions = {version for version, _fn in _SCHEMA_MIGRATIONS}
    assert "0007_audit_class_info_text" in versions


class _FakeInspector:
    def __init__(self, types):
        self.types = types

    def has_table(self, table):
        return table in self.types

    def get_columns(self, table):
        return [{"name": "class_info", "type": self.types[table]}]


def test_mysql_migration_expands_both_audit_tables():
    statements = _audit_class_info_text_statements(_FakeInspector({
        "audit_courses": String(500),
        "audit_favorites": String(500),
    }))
    assert statements == [
        "ALTER TABLE `audit_courses` MODIFY COLUMN class_info TEXT NULL",
        "ALTER TABLE `audit_favorites` MODIFY COLUMN class_info TEXT NULL",
    ]


def test_mysql_migration_skips_columns_already_text():
    statements = _audit_class_info_text_statements(_FakeInspector({
        "audit_courses": Text(),
        "audit_favorites": Text(),
    }))
    assert statements == []


def test_mysql_migration_does_not_downgrade_longtext():
    statements = _audit_class_info_text_statements(_FakeInspector({
        "audit_courses": LONGTEXT(),
        "audit_favorites": LONGTEXT(),
    }))
    assert statements == []


def test_long_class_info_favorites_keep_full_value_and_distinct_keys():
    with app.app_context():
        student_id = "audit-class-info-regression"
        semester = "2026-2027-1"
        prefix = "9" * 500
        for suffix in ("1", "2"):
            dao.save_audit_favorite(student_id, semester, {
                "name": "长班级信息课程",
                "class_info": prefix + suffix,
                "teacher": "测试教师",
                "classroom": "Ⅰ-101",
                "schedules": [{
                    "day": 1,
                    "start": 1,
                    "end": 2,
                    "weeks": "1-16",
                    "teacher": "测试教师",
                    "classroom": "Ⅰ-101",
                }],
            })
        rows = dao.list_audit_favorites(student_id, semester)
        assert len(rows) == 2
        assert {row["class_info"] for row in rows} == {
            prefix + "1", prefix + "2",
        }
