# -*- coding: utf-8 -*-
"""服务层、Repository 和后台任务入口的回归测试。"""
import pytest

import wxcloudrun as app_module
from wxcloudrun import app, dao
from wxcloudrun.jwc_client import JWCClient
from wxcloudrun.jobs import runner
from wxcloudrun.repositories import student_data
from wxcloudrun.services.student_data_service import (
    StudentDataError,
    refresh_schedule,
    refresh_schedule_and_exams,
)


def _client(sid="service-test"):
    client = JWCClient()
    client.student_id = sid
    client.logged_in = True
    client.last_error = ""
    client.is_session_valid = lambda: True
    return client


def test_student_service_persists_schedule_and_exams_together():
    with app.app_context():
        client = _client("service-refresh")
        client.get_schedule = lambda semester: [{
            "name": "服务层课程", "teacher": "教师", "classroom": "A101",
            "day": 1, "start": 1, "end": 2, "weeks": "1-16",
        }]
        client.get_exams = lambda semester: [{
            "course_name": "服务层课程", "date": "2026-12-20",
            "time": "09:00-11:00", "location": "A101",
        }]

        result = refresh_schedule_and_exams(client, "2026-2027-1")

        assert result["schedule"] == {"count": 1, "ok": True}
        assert result["exams"] == {"count": 1, "ok": True}
        assert len(dao.get_courses("2026-2027-1", "service-refresh")) == 1
        assert len(dao.get_exams("2026-2027-1", "service-refresh")) == 1


def test_student_service_maps_session_error_to_401():
    with app.app_context():
        client = _client("service-expired")

        def expired(_semester):
            client.logged_in = False
            client.last_error = "登录状态已失效"
            return []

        client.get_schedule = expired
        with pytest.raises(StudentDataError) as caught:
            refresh_schedule(client, "2026-2027-1")
        assert caught.value.status_code == 401
        assert "会话已过期" in caught.value.message
        assert client.logged_in is False


def test_repository_failure_keeps_previous_schedule(monkeypatch):
    with app.app_context():
        sid = "repository-atomic"
        semester = "2026-2027-1"
        student_data.replace_courses([{
            "name": "旧课程", "day": 1, "start": 1, "end": 2,
        }], semester, sid)

        def fail(*_args, **_kwargs):
            raise RuntimeError("模拟写入失败")

        monkeypatch.setattr(dao.db.session, "bulk_insert_mappings", fail)
        with pytest.raises(RuntimeError):
            student_data.replace_courses([{
                "name": "新课程", "day": 2, "start": 3, "end": 4,
            }], semester, sid)

        assert [row["name"] for row in dao.get_courses(semester, sid)] == ["旧课程"]


def test_repository_failure_keeps_complete_grade_snapshot(monkeypatch):
    with app.app_context():
        sid = "repository-grade-atomic"
        student_data.replace_grades_snapshot([{
            "academic_year": "2025-2026",
            "semester": "1",
            "course_name": "旧成绩",
            "score": "88",
        }], sid)

        def fail(*_args, **_kwargs):
            raise RuntimeError("模拟成绩写入失败")

        monkeypatch.setattr(dao.db.session, "bulk_insert_mappings", fail)
        with pytest.raises(RuntimeError):
            student_data.replace_grades_snapshot([{
                "academic_year": "2026-2027",
                "semester": "1",
                "course_name": "新成绩",
                "score": "99",
            }], sid)

        rows = dao.get_grades(student_id=sid)
        assert [row["course_name"] for row in rows] == ["旧成绩"]


def test_job_runner_registers_each_job_once(monkeypatch):
    runner.reset_for_tests()
    calls = []

    def starter():
        calls.append("started")
        return True

    assert runner._start_once("test-job", starter) is True
    assert runner._start_once("test-job", starter) is False
    assert calls == ["started"]
    runner.reset_for_tests()


def test_disabled_auto_migration_never_calls_create_all(monkeypatch):
    """生产启动路径只读校验，不能因配置关闭而触发 DDL。"""
    monkeypatch.setattr(app_module.config, "MIGRATIONS_AUTO", False)
    monkeypatch.setattr(app_module, "_verify_schema", lambda: None)

    def fail_create_all():
        raise AssertionError("关闭自动迁移时不应调用 db.create_all")

    monkeypatch.setattr(app_module.db, "create_all", fail_create_all)
    assert app_module._run_migrations(force=False) == []


def test_enabled_auto_migration_runs_create_all(monkeypatch):
    """保留本地单实例兼容开关时，开启它必须真正执行迁移入口。"""
    called = []
    monkeypatch.setattr(app_module.config, "MIGRATIONS_AUTO", True)
    monkeypatch.setattr(app_module.db, "create_all", lambda: called.append(True))
    assert app_module._run_migrations(force=False) == []
    assert called == [True]


def test_schema_check_reports_missing_migration_and_columns(monkeypatch):
    """只读启动检查不能只看表存在，还要拦截不完整的存量结构。"""
    class _Inspector:
        def has_table(self, _table):
            return True

        def get_columns(self, table):
            if table == "audit_courses":
                return [{"name": "id"}]
            return [{"name": "student_id"}]

    class _Rows:
        def with_entities(self, *_args, **_kwargs):
            return self

        def all(self):
            return []

    with app.app_context():
        monkeypatch.setattr(app_module.SchemaMigration, "query", _Rows())
        issues = app_module._schema_deficiencies(_Inspector())
    assert any("audit_courses 缺少列 class_info" in item for item in issues)
    assert any("缺少迁移版本" in item for item in issues)
