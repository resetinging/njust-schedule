package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"time"
)

type SubscriptionItem struct {
	Count     int   `json:"count"`
	UpdatedAt int64 `json:"updated_at,omitempty"`
	UsedAt    int64 `json:"used_at,omitempty"`
}

func decodeSubscriptions(raw string) (map[string]SubscriptionItem, error) {
	value := map[string]SubscriptionItem{}
	if raw == "" {
		return value, nil
	}
	if err := json.Unmarshal([]byte(raw), &value); err != nil {
		return nil, err
	}
	if value == nil {
		value = map[string]SubscriptionItem{}
	}
	return value, nil
}

func (s *Store) SubscriptionStatus(ctx context.Context, sid string) (map[string]SubscriptionItem, error) {
	raw, err := s.UserSetting(ctx, sid, "subscribe")
	if err != nil {
		return nil, err
	}
	return decodeSubscriptions(raw)
}

func (s *Store) GrantSubscription(ctx context.Context, sid, kind, openid string) (int, error) {
	count := 0
	err := s.transaction(ctx, func(tx *sql.Tx) error {
		if _, err := tx.ExecContext(ctx, `INSERT IGNORE INTO user_settings (student_id,k,v,updated_at) VALUES (?,'subscribe','{}',NOW())`, sid); err != nil {
			return err
		}
		var raw sql.NullString
		err := tx.QueryRowContext(ctx, "SELECT v FROM user_settings WHERE student_id=? AND k='subscribe' FOR UPDATE", sid).Scan(&raw)
		if err != nil && !errors.Is(err, sql.ErrNoRows) {
			return err
		}
		values, err := decodeSubscriptions(raw.String)
		if err != nil {
			return err
		}
		item := values[kind]
		item.Count++
		item.UpdatedAt = time.Now().Unix()
		values[kind] = item
		encoded, err := json.Marshal(values)
		if err != nil {
			return err
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO user_settings (student_id,k,v,updated_at) VALUES (?,'subscribe',?,NOW()) ON DUPLICATE KEY UPDATE v=VALUES(v),updated_at=NOW()`, sid, string(encoded)); err != nil {
			return err
		}
		if openid != "" {
			if _, err = tx.ExecContext(ctx, `INSERT INTO user_settings (student_id,k,v,updated_at) VALUES (?,'openid',?,NOW()) ON DUPLICATE KEY UPDATE v=VALUES(v),updated_at=NOW()`, sid, openid); err != nil {
				return err
			}
		}
		count = item.Count
		return nil
	})
	return count, err
}

func (s *Store) ConsumeSubscription(ctx context.Context, sid, kind string) (bool, error) {
	return s.ReserveSubscription(ctx, sid, kind)
}

func (s *Store) ReserveSubscription(ctx context.Context, sid, kind string) (bool, error) {
	consumed := false
	err := s.transaction(ctx, func(tx *sql.Tx) error {
		if _, err := tx.ExecContext(ctx, `INSERT IGNORE INTO user_settings (student_id,k,v,updated_at) VALUES (?,'subscribe','{}',NOW())`, sid); err != nil {
			return err
		}
		var raw sql.NullString
		err := tx.QueryRowContext(ctx, "SELECT v FROM user_settings WHERE student_id=? AND k='subscribe' FOR UPDATE", sid).Scan(&raw)
		if errors.Is(err, sql.ErrNoRows) {
			return nil
		}
		if err != nil {
			return err
		}
		values, err := decodeSubscriptions(raw.String)
		if err != nil {
			return err
		}
		item := values[kind]
		if item.Count <= 0 {
			return nil
		}
		item.Count--
		item.UsedAt = time.Now().Unix()
		values[kind] = item
		encoded, err := json.Marshal(values)
		if err != nil {
			return err
		}
		_, err = tx.ExecContext(ctx, "UPDATE user_settings SET v=?,updated_at=NOW() WHERE student_id=? AND k='subscribe'", string(encoded), sid)
		consumed = err == nil
		return err
	})
	return consumed, err
}

func (s *Store) RefundSubscription(ctx context.Context, sid, kind string) error {
	return s.transaction(ctx, func(tx *sql.Tx) error {
		if _, err := tx.ExecContext(ctx, `INSERT IGNORE INTO user_settings (student_id,k,v,updated_at) VALUES (?,'subscribe','{}',NOW())`, sid); err != nil {
			return err
		}
		var raw sql.NullString
		if err := tx.QueryRowContext(ctx, "SELECT v FROM user_settings WHERE student_id=? AND k='subscribe' FOR UPDATE", sid).Scan(&raw); err != nil {
			return err
		}
		values, err := decodeSubscriptions(raw.String)
		if err != nil {
			return err
		}
		item := values[kind]
		item.Count++
		item.UpdatedAt = time.Now().Unix()
		values[kind] = item
		encoded, err := json.Marshal(values)
		if err != nil {
			return err
		}
		_, err = tx.ExecContext(ctx, "UPDATE user_settings SET v=?,updated_at=NOW() WHERE student_id=? AND k='subscribe'", string(encoded), sid)
		return err
	})
}

type UsageEvent struct {
	EventKey, AnalyticsID, VisitorHash, SessionID string
	Name, Page, Feature, SlotID, AdType           string
	VisibleMS                                     int
	Properties                                    string
	AppVersion, Platform                          string
	ClientTS                                      *time.Time
}

func (s *Store) RecordUsageEvents(ctx context.Context, day string, values []UsageEvent) (accepted, duplicates int, err error) {
	err = s.transaction(ctx, func(tx *sql.Tx) error {
		for _, value := range values {
			result, insertErr := tx.ExecContext(ctx, `INSERT INTO usage_events
				(event_key,analytics_id,visitor_hash,session_id,event_name,page,feature,slot_id,ad_type,visible_ms,properties_json,app_version,platform,client_ts,created_at)
				VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,NOW()) ON DUPLICATE KEY UPDATE event_key=VALUES(event_key)`, value.EventKey, value.AnalyticsID, value.VisitorHash,
				value.SessionID, value.Name, value.Page, value.Feature, value.SlotID, value.AdType, value.VisibleMS,
				value.Properties, value.AppVersion, value.Platform, value.ClientTS)
			if insertErr != nil {
				return insertErr
			}
			rows, rowsErr := result.RowsAffected()
			if rowsErr != nil {
				return rowsErr
			}
			if rows == 0 {
				duplicates++
				continue
			}
			accepted++
			open, sessions, seconds, pages, actions := 0, 0, 0, 0, 0
			switch value.Name {
			case "app_open":
				open = 1
			case "session_start":
				sessions = 1
			case "session_end":
				var props map[string]any
				if err := json.Unmarshal([]byte(value.Properties), &props); err != nil {
					return err
				}
				if duration, ok := props["duration_s"].(float64); ok && duration > 0 {
					seconds = min(86400, int(duration))
				}
			case "page_view":
				pages = 1
			case "feature_action", "refresh_success", "refresh_fail", "reminder_grant", "audit_favorite", "feedback_submit":
				actions = 1
			}
			if _, insertErr = tx.ExecContext(ctx, `INSERT INTO usage_user_daily
				(date,analytics_id,open_count,session_count,active_seconds,page_views,event_count,feature_actions,first_seen_at,last_seen_at,updated_at)
				VALUES (?,?,?,?,?,?,1,?,NOW(),NOW(),NOW()) ON DUPLICATE KEY UPDATE
				open_count=open_count+VALUES(open_count),session_count=session_count+VALUES(session_count),
				active_seconds=active_seconds+VALUES(active_seconds),page_views=page_views+VALUES(page_views),
				event_count=event_count+1,feature_actions=feature_actions+VALUES(feature_actions),last_seen_at=NOW(),updated_at=NOW()`,
				day, value.AnalyticsID, open, sessions, seconds, pages, actions); insertErr != nil {
				return insertErr
			}
			if value.SlotID == "" {
				continue
			}
			views, visible, visibleMS, requests, impressions, clicks, closes := 0, 0, 0, 0, 0, 0, 0
			switch value.Name {
			case "slot_view":
				views = 1
			case "slot_visible":
				visible, visibleMS = 1, value.VisibleMS
			case "slot_leave":
				visibleMS = value.VisibleMS
			case "ad_request":
				requests = 1
			case "ad_impression":
				impressions = 1
			case "ad_click":
				clicks = 1
			case "ad_close":
				closes = 1
			}
			if _, insertErr = tx.ExecContext(ctx, `INSERT INTO usage_slot_user_daily
				(date,analytics_id,slot_id,ad_type,page,views,visible_count,visible_ms,requests,impressions,clicks,closes,first_seen_at,last_seen_at,updated_at)
				VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NOW(),NOW(),NOW()) ON DUPLICATE KEY UPDATE
				page=IF(page='',VALUES(page),page),views=views+VALUES(views),visible_count=visible_count+VALUES(visible_count),
				visible_ms=visible_ms+VALUES(visible_ms),requests=requests+VALUES(requests),impressions=impressions+VALUES(impressions),
				clicks=clicks+VALUES(clicks),closes=closes+VALUES(closes),last_seen_at=NOW(),updated_at=NOW()`,
				day, value.AnalyticsID, value.SlotID, value.AdType, value.Page, views, visible, visibleMS, requests, impressions, clicks, closes); insertErr != nil {
				return insertErr
			}
		}
		return nil
	})
	return
}
