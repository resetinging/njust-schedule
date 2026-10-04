# -*- coding: utf-8 -*-
"""小程序使用统计写入服务。

统计只保存行为上下文和广告槽位库存，不保存 token、Cookie、密码、
成绩、课程或教师原文。
"""
import hashlib
import hmac
import json
import re
import threading
from datetime import datetime, timedelta, timezone

import config
from wxcloudrun import db
from wxcloudrun.core.sessions import TOKEN_HEADER, _get_session_client
from wxcloudrun.core.timeutil import _beijing_date, _beijing_datetime
from wxcloudrun.model import UsageEvent, UsageSlotUserDaily, UsageUserDaily


MAX_BATCH_EVENTS = 20
MAX_STRING_LEN = 80
BEIJING_TZ = timezone(timedelta(hours=8))

EVENT_NAMES = {
    'app_open', 'app_background', 'session_start', 'session_end',
    'page_view', 'page_leave', 'feature_open', 'feature_action',
    'refresh_success', 'refresh_fail', 'login_success',
    'reminder_grant', 'audit_favorite', 'feedback_submit',
    'slot_view', 'slot_visible', 'slot_leave',
    'ad_request', 'ad_loaded', 'ad_failed', 'ad_impression',
    'ad_click', 'ad_close', 'ad_reward_complete',
}

PAGE_NAMES = {
    '', 'main', 'schedule', 'feature', 'exams', 'eval', 'grades',
    'credit', 'freeclass', 'gallery', 'audit', 'profile', 'login',
}

FEATURE_NAMES = {
    '', 'schedule', 'exams', 'eval', 'grades', 'credit',
    'freeclass', 'gallery', 'audit', 'subscription', 'feedback',
    'settings', 'profile', 'login',
}

AD_TYPES = {'', 'native', 'banner', 'interstitial', 'rewarded'}
PLATFORM_NAMES = {'', 'ios', 'android', 'devtools', 'other'}
PROPERTY_KEYS = {
    'duration_s', 'visible_ms', 'result', 'kind', 'has_data',
    'items', 'tab', 'source',
}
SAFE_ID_RE = re.compile(r'^[A-Za-z0-9_.:-]{1,64}$')
_last_purge_day = None
_purge_lock = threading.Lock()


class UsageValidationError(ValueError):
    pass


def _safe_string(value, max_len=MAX_STRING_LEN):
    return str(value or '').strip()[:max_len]


def _safe_enum(value, allowed, field):
    text = _safe_string(value, 64)
    if text not in allowed:
        raise UsageValidationError(f'invalid {field}')
    return text


def _safe_id(value, field, required=False):
    text = _safe_string(value, 64)
    if not text:
        if required:
            raise UsageValidationError(f'missing {field}')
        return ''
    if not SAFE_ID_RE.fullmatch(text):
        raise UsageValidationError(f'invalid {field}')
    return text


def _secret_bytes():
    raw = str(getattr(config, 'SESSION_KEY', '') or '')
    return hashlib.sha256(raw.encode('utf-8')).digest()


def analytics_id_for_sid(student_id: str) -> str:
    sid = _safe_string(student_id, 50)
    if not sid:
        return ''
    return hmac.new(_secret_bytes(), ('sid|' + sid).encode('utf-8'),
                    hashlib.sha256).hexdigest()


def _visitor_hash(visitor_id: str) -> str:
    visitor = _safe_id(visitor_id, 'visitor_id')
    if not visitor:
        return ''
    return hmac.new(_secret_bytes(), ('visitor|' + visitor).encode('utf-8'),
                    hashlib.sha256).hexdigest()


def _parse_client_ts(value):
    if value in (None, ''):
        return None
    try:
        if isinstance(value, str) and value.endswith('Z'):
            value = value[:-1] + '+00:00'
        if isinstance(value, (int, float)):
            number = float(value)
            if number > 100000000000:
                number = number / 1000.0
            dt = datetime.fromtimestamp(number, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is not None:
            dt = dt.astimezone(BEIJING_TZ)
        return dt.replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError):
        return None


def _normalize_properties(raw):
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key in PROPERTY_KEYS:
        if key not in raw:
            continue
        value = raw.get(key)
        if isinstance(value, bool):
            out[key] = value
        elif isinstance(value, (int, float)):
            out[key] = max(-86400, min(86400, value))
        elif value is not None:
            out[key] = _safe_string(value, 120)
    return out


def _normalize_event(raw):
    if not isinstance(raw, dict):
        raise UsageValidationError('event must be an object')
    event_id = _safe_id(raw.get('id'), 'event_id', required=True)
    name = _safe_enum(raw.get('name'), EVENT_NAMES, 'event_name')
    page = _safe_enum(raw.get('page') or '', PAGE_NAMES, 'page')
    feature = _safe_enum(raw.get('feature') or '', FEATURE_NAMES, 'feature')
    slot_id = _safe_id(raw.get('slot_id'), 'slot_id')
    ad_type = _safe_enum(raw.get('ad_type') or '', AD_TYPES, 'ad_type')
    platform = _safe_enum(raw.get('platform') or '', PLATFORM_NAMES, 'platform')
    properties = _normalize_properties(raw.get('properties'))
    visible_ms = properties.get('visible_ms', raw.get('visible_ms', 0))
    try:
        visible_ms = max(0, min(3600000, int(visible_ms or 0)))
    except (TypeError, ValueError):
        visible_ms = 0
    client_ts = _parse_client_ts(raw.get('ts'))
    if client_ts is not None:
        now = _beijing_datetime()
        if client_ts > now + timedelta(minutes=10):
            client_ts = None
        elif client_ts < now - timedelta(days=30):
            client_ts = None
    return {
        'id': event_id,
        'name': name,
        'page': page,
        'feature': feature,
        'slot_id': slot_id,
        'ad_type': ad_type,
        'visible_ms': visible_ms,
        'properties': properties,
        'app_version': _safe_string(raw.get('app_version'), 40),
        'platform': platform,
        'client_ts': client_ts,
        'session_id': _safe_id(raw.get('session_id'), 'session_id', required=True),
    }


def _event_key(analytics_id, event, session_id):
    material = '|'.join((
        analytics_id or 'anonymous',
        session_id,
        event['id'],
        event['name'],
    ))
    return hashlib.sha256(material.encode('utf-8')).hexdigest()


def _increment_row(row, event):
    """把一条事件累加到按日汇总行。"""
    if row.open_count is None:
        row.open_count = 0
    if row.session_count is None:
        row.session_count = 0
    if row.active_seconds is None:
        row.active_seconds = 0
    if row.page_views is None:
        row.page_views = 0
    if row.event_count is None:
        row.event_count = 0
    if row.feature_actions is None:
        row.feature_actions = 0

    row.event_count += 1
    if event['name'] == 'app_open':
        row.open_count += 1
    elif event['name'] == 'session_start':
        row.session_count += 1
    elif event['name'] == 'session_end':
        try:
            row.active_seconds += max(0, int(
                event['properties'].get('duration_s') or 0))
        except (TypeError, ValueError):
            pass
    elif event['name'] == 'page_view':
        row.page_views += 1
    elif event['name'] in {
            'feature_action', 'refresh_success', 'refresh_fail',
            'reminder_grant', 'audit_favorite', 'feedback_submit'}:
        row.feature_actions += 1

    now = _beijing_datetime()
    if row.first_seen_at is None:
        row.first_seen_at = event['client_ts'] or now
    row.last_seen_at = event['client_ts'] or now


def _increment_slot(row, event):
    if row.views is None:
        row.views = 0
    if row.visible_count is None:
        row.visible_count = 0
    if row.visible_ms is None:
        row.visible_ms = 0
    if row.requests is None:
        row.requests = 0
    if row.impressions is None:
        row.impressions = 0
    if row.clicks is None:
        row.clicks = 0
    if row.closes is None:
        row.closes = 0

    name = event['name']
    if name == 'slot_view':
        row.views += 1
    elif name == 'slot_visible':
        row.visible_count += 1
        row.visible_ms += int(event.get('visible_ms') or 0)
    elif name == 'slot_leave':
        row.visible_ms += int(event.get('visible_ms') or 0)
    elif name == 'ad_request':
        row.requests += 1
    elif name == 'ad_impression':
        row.impressions += 1
    elif name == 'ad_click':
        row.clicks += 1
    elif name == 'ad_close':
        row.closes += 1

    now = _beijing_datetime()
    if row.first_seen_at is None:
        row.first_seen_at = event['client_ts'] or now
    row.last_seen_at = event['client_ts'] or now


def record_events(payload, token=''):
    """写入一批事件，返回 (accepted, duplicates, rejected)。"""
    if not isinstance(payload, dict) or payload.get('consent') is not True:
        raise UsageValidationError('consent required')
    events = payload.get('events')
    if not isinstance(events, list):
        raise UsageValidationError('events must be a list')
    if len(events) > MAX_BATCH_EVENTS:
        raise UsageValidationError('too many events')
    if not events:
        return 0, 0, 0

    student_id = ''
    if token:
        try:
            client = _get_session_client()
            if client is not None and getattr(client, 'logged_in', False):
                student_id = getattr(client, 'student_id', '') or ''
        except Exception:  # noqa: BLE001
            student_id = ''

    visitor_hash = _visitor_hash(payload.get('visitor_id'))
    analytics_id = analytics_id_for_sid(student_id) or visitor_hash
    if not analytics_id:
        raise UsageValidationError('missing identity')

    normalized = []
    rejected = 0
    for raw in events:
        try:
            normalized.append(_normalize_event(raw))
        except UsageValidationError:
            rejected += 1

    if not normalized:
        return 0, 0, rejected

    keys = [_event_key(analytics_id, event, event['session_id'])
            for event in normalized]
    existing = {
        row[0] for row in db.session.query(UsageEvent.event_key)
        .filter(UsageEvent.event_key.in_(keys)).all()
    }
    accepted = []
    duplicates = 0
    for key, event in zip(keys, normalized):
        if key in existing:
            duplicates += 1
            continue
        existing.add(key)
        accepted.append((key, event))

    if not accepted:
        return 0, duplicates, rejected

    day = _beijing_date()
    now = _beijing_datetime()
    user_day = db.session.get(UsageUserDaily, (day, analytics_id))
    if user_day is None:
        user_day = UsageUserDaily(
            date=day, analytics_id=analytics_id,
            first_seen_at=now, last_seen_at=now)
        db.session.add(user_day)

    slot_rows = {}
    for key, event in accepted:
        db.session.add(UsageEvent(
            event_key=key,
            analytics_id=analytics_id,
            visitor_hash=visitor_hash,
            session_id=event['session_id'],
            event_name=event['name'],
            page=event['page'],
            feature=event['feature'],
            slot_id=event['slot_id'],
            ad_type=event['ad_type'],
            visible_ms=event['visible_ms'],
            properties_json=json.dumps(
                event['properties'], ensure_ascii=False, separators=(',', ':')),
            app_version=event['app_version'],
            platform=event['platform'],
            client_ts=event['client_ts'],
            created_at=now,
        ))
        _increment_row(user_day, event)
        if event['slot_id']:
            slot_key = (event['slot_id'], event['ad_type'])
            slot_row = slot_rows.get(slot_key)
            if slot_row is None:
                slot_row = db.session.get(
                    UsageSlotUserDaily,
                    (day, analytics_id, event['slot_id'], event['ad_type']))
                if slot_row is None:
                    slot_row = UsageSlotUserDaily(
                        date=day,
                        analytics_id=analytics_id,
                        slot_id=event['slot_id'],
                        ad_type=event['ad_type'],
                        page=event['page'],
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                    db.session.add(slot_row)
                slot_rows[slot_key] = slot_row
            if event['page'] and not slot_row.page:
                slot_row.page = event['page']
            _increment_slot(slot_row, event)

    db.session.commit()
    _maybe_purge()
    return len(accepted), duplicates, rejected


def purge_expired_events(raw_days=90):
    """删除超过保留期的原始事件和匿名日汇总。"""
    now = _beijing_datetime()
    cutoff = now - timedelta(days=max(1, int(raw_days)))
    deleted = (
        UsageEvent.query
        .filter(UsageEvent.created_at < cutoff)
        .delete(synchronize_session=False)
    )
    daily_cutoff = _beijing_date() - timedelta(days=365)
    UsageUserDaily.query.filter(
        UsageUserDaily.date < daily_cutoff
    ).delete(synchronize_session=False)
    UsageSlotUserDaily.query.filter(
        UsageSlotUserDaily.date < daily_cutoff
    ).delete(synchronize_session=False)
    db.session.commit()
    return int(deleted or 0)


def _maybe_purge(raw_days=90):
    """每个进程每天最多清理一次过期原始事件。"""
    global _last_purge_day
    today = _beijing_date()
    if _last_purge_day == today:
        return
    with _purge_lock:
        if _last_purge_day == today:
            return
        try:
            purge_expired_events(raw_days=raw_days)
        except Exception:  # noqa: BLE001 清理失败不能影响上报
            return
        _last_purge_day = today
