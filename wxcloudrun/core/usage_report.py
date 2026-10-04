# -*- coding: utf-8 -*-
"""管理面板使用统计聚合。"""
from collections import defaultdict
from datetime import datetime, time, timedelta

from sqlalchemy import func

from wxcloudrun import db
from wxcloudrun.core.timeutil import _beijing_date
from wxcloudrun.core.usage import analytics_id_for_sid
from wxcloudrun.model import UsageEvent, UsageSlotUserDaily, UsageUserDaily


def _percent(retained, eligible):
    if not eligible:
        return 0.0
    return round(retained * 100.0 / eligible, 1)


def build_report(days=30):
    days = max(1, min(90, int(days or 30)))
    today = _beijing_date()
    start = today - timedelta(days=days - 1)
    lookback_start = min(start, today - timedelta(days=120))
    start_dt = datetime.combine(start, time.min)
    hour_start_dt = datetime.combine(today - timedelta(days=6), time.min)

    daily_rows = (
        UsageUserDaily.query
        .filter(UsageUserDaily.date >= lookback_start,
                UsageUserDaily.date <= today)
        .order_by(UsageUserDaily.date.asc())
        .all()
    )
    first_rows = (
        db.session.query(
            UsageUserDaily.analytics_id,
            func.min(UsageUserDaily.date).label('first_date'))
        .group_by(UsageUserDaily.analytics_id)
        .all()
    )
    first_map = {row.analytics_id: row.first_date for row in first_rows}

    by_day = defaultdict(lambda: {
        'users': set(), 'opens': 0, 'sessions': 0,
        'active_seconds': 0, 'page_views': 0, 'new_users': 0,
    })
    active_dates = defaultdict(set)
    for row in daily_rows:
        item = by_day[row.date]
        item['users'].add(row.analytics_id)
        item['opens'] += int(row.open_count or 0)
        item['sessions'] += int(row.session_count or 0)
        item['active_seconds'] += int(row.active_seconds or 0)
        item['page_views'] += int(row.page_views or 0)
        active_dates[row.analytics_id].add(row.date)
        if first_map.get(row.analytics_id) == row.date:
            item['new_users'] += 1

    today_item = by_day.get(today, {})
    yesterday_item = by_day.get(today - timedelta(days=1), {})
    users_7 = {
        row.analytics_id for row in daily_rows
        if row.date >= today - timedelta(days=6)
    }
    users_30 = {
        row.analytics_id for row in daily_rows
        if row.date >= today - timedelta(days=29)
    }
    dau = len(today_item.get('users') or set())
    avg_seconds = (
        int((today_item.get('active_seconds') or 0) / dau) if dau else 0
    )

    trend = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        item = by_day.get(day, {})
        trend.append({
            'date': day.strftime('%m-%d'),
            'dau': len(item.get('users') or set()),
            'new_users': int(item.get('new_users') or 0),
            'opens': int(item.get('opens') or 0),
            'sessions': int(item.get('sessions') or 0),
            'active_seconds': int(item.get('active_seconds') or 0),
        })

    retention = {}
    for name, offset in (('d1', 1), ('d7', 7), ('d30', 30)):
        eligible = retained = 0
        for analytics_id, first_date in first_map.items():
            if first_date < lookback_start:
                continue
            if first_date + timedelta(days=offset) > today:
                continue
            eligible += 1
            if first_date + timedelta(days=offset) in active_dates.get(analytics_id, set()):
                retained += 1
        retention[name] = {
            'eligible': eligible,
            'retained': retained,
            'rate': _percent(retained, eligible),
        }

    page_rows = (
        db.session.query(
            UsageEvent.page,
            func.count(UsageEvent.id).label('events'),
            func.count(func.distinct(UsageEvent.analytics_id)).label('users'))
        .filter(UsageEvent.created_at >= start_dt,
                UsageEvent.event_name == 'page_view',
                UsageEvent.page != '')
        .group_by(UsageEvent.page)
        .order_by(func.count(UsageEvent.id).desc())
        .limit(20)
        .all()
    )
    feature_rows = (
        db.session.query(
            UsageEvent.feature,
            func.count(UsageEvent.id).label('events'),
            func.count(func.distinct(UsageEvent.analytics_id)).label('users'))
        .filter(UsageEvent.created_at >= start_dt,
                UsageEvent.feature != '')
        .group_by(UsageEvent.feature)
        .order_by(func.count(UsageEvent.id).desc())
        .limit(20)
        .all()
    )
    slot_rows = (
        db.session.query(
            UsageSlotUserDaily.slot_id,
            UsageSlotUserDaily.ad_type,
            func.max(UsageSlotUserDaily.page).label('page'),
            func.sum(UsageSlotUserDaily.views).label('views'),
            func.sum(UsageSlotUserDaily.visible_count).label('visible_count'),
            func.sum(UsageSlotUserDaily.visible_ms).label('visible_ms'),
            func.sum(UsageSlotUserDaily.requests).label('requests'),
            func.sum(UsageSlotUserDaily.impressions).label('impressions'),
            func.sum(UsageSlotUserDaily.clicks).label('clicks'),
            func.sum(UsageSlotUserDaily.closes).label('closes'),
            func.count(func.distinct(UsageSlotUserDaily.analytics_id)).label('users'))
        .filter(UsageSlotUserDaily.date >= start)
        .group_by(UsageSlotUserDaily.slot_id, UsageSlotUserDaily.ad_type)
        .order_by(func.sum(UsageSlotUserDaily.visible_count).desc())
        .limit(50)
        .all()
    )

    hour_expr = func.extract('hour', UsageEvent.created_at)
    hour_rows = (
        db.session.query(
            hour_expr.label('hour'),
            func.count(UsageEvent.id).label('events'))
        .filter(UsageEvent.created_at >= hour_start_dt)
        .group_by(hour_expr)
        .all()
    )
    hourly = {str(hour): 0 for hour in range(24)}
    for row in hour_rows:
        try:
            hourly[str(int(row.hour))] = int(row.events or 0)
        except (TypeError, ValueError):
            continue

    return {
        'success': True,
        'days': days,
        'overview': {
            'dau': dau,
            'dau_yesterday': len(yesterday_item.get('users') or set()),
            'wau': len(users_7),
            'mau': len(users_30),
            'new_users_today': len([
                analytics_id for analytics_id, first_date in first_map.items()
                if first_date == today
            ]),
            'total_users': len(first_map),
            'opens_today': int(today_item.get('opens') or 0),
            'sessions_today': int(today_item.get('sessions') or 0),
            'active_seconds_today': int(today_item.get('active_seconds') or 0),
            'avg_seconds_today': avg_seconds,
            'page_views_today': int(today_item.get('page_views') or 0),
        },
        'trend': trend,
        'retention': retention,
        'pages': [
            {'page': row.page, 'events': int(row.events or 0),
             'users': int(row.users or 0)}
            for row in page_rows
        ],
        'features': [
            {'feature': row.feature, 'events': int(row.events or 0),
             'users': int(row.users or 0)}
            for row in feature_rows
        ],
        'slots': [
            {
                'slot_id': row.slot_id,
                'ad_type': row.ad_type or '未指定',
                'page': row.page or '',
                'views': int(row.views or 0),
                'visible_count': int(row.visible_count or 0),
                'visible_ms': int(row.visible_ms or 0),
                'requests': int(row.requests or 0),
                'impressions': int(row.impressions or 0),
                'clicks': int(row.clicks or 0),
                'closes': int(row.closes or 0),
                'users': int(row.users or 0),
            }
            for row in slot_rows
        ],
        'hourly': hourly,
    }


def user_usage_map(student_ids, days=30):
    """返回 {学号: 最近使用摘要}, 只计算当前控制面板中的用户。"""
    days = max(1, min(90, int(days or 30)))
    today = _beijing_date()
    start = today - timedelta(days=days - 1)
    hash_to_sid = {
        analytics_id_for_sid(sid): sid
        for sid in student_ids if sid
    }
    ids = [key for key in hash_to_sid if key]
    if not ids:
        return {}
    rows = (
        db.session.query(
            UsageUserDaily.analytics_id,
            func.count(UsageUserDaily.date).label('active_days'),
            func.max(UsageUserDaily.last_seen_at).label('last_seen_at'))
        .filter(UsageUserDaily.date >= start,
                UsageUserDaily.analytics_id.in_(ids))
        .group_by(UsageUserDaily.analytics_id)
        .all()
    )
    out = {}
    for row in rows:
        sid = hash_to_sid.get(row.analytics_id)
        if not sid:
            continue
        out[sid] = {
            'active_days_30': int(row.active_days or 0),
            'last_active': (
                row.last_seen_at.strftime('%Y-%m-%d %H:%M')
                if row.last_seen_at else ''
            ),
        }
    return out
