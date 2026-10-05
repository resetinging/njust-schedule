# -*- coding: utf-8 -*-
"""考试/成绩提醒任务适配器。"""


def start() -> bool:
    from wxcloudrun.core.reminder import start_exam_reminder
    return start_exam_reminder()
