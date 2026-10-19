package httpapi

import (
	"context"
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/resetinging/njust-schedule/internal/session"
)

func decodeMap(raw string) map[string]any {
	value := map[string]any{}
	if strings.TrimSpace(raw) == "" || json.Unmarshal([]byte(raw), &value) != nil {
		return map[string]any{}
	}
	return value
}

func mapUnix(value map[string]any, key string) int64 {
	switch raw := value[key].(type) {
	case float64:
		return int64(raw)
	case int64:
		return raw
	case json.Number:
		value, _ := raw.Int64()
		return value
	case string:
		value, _ := strconv.ParseInt(raw, 10, 64)
		return value
	default:
		return 0
	}
}

func (s *Server) saveMap(ctx context.Context, key string, value map[string]any) error {
	raw, err := json.Marshal(value)
	if err != nil {
		return err
	}
	return s.store.SetSetting(ctx, key, string(raw))
}

func (s *Server) saveUserMap(ctx context.Context, sid, key string, value map[string]any) error {
	raw, err := json.Marshal(value)
	if err != nil {
		return err
	}
	return s.store.SetUserSetting(ctx, sid, key, string(raw))
}

func calendarKey(semester string) string {
	if semester == "" {
		return "calendar:current"
	}
	return "calendar:" + semester
}

func (s *Server) syncFirstWeek(ctx context.Context, sid string, value map[string]any) error {
	semester, _ := value["semester"].(string)
	firstMonday, _ := value["first_monday"].(string)
	if sid != "" && semester != "" && firstMonday != "" {
		return s.store.SetUserSetting(ctx, sid, "first_week_date:"+semester, firstMonday)
	}
	return nil
}

func (s *Server) fetchCalendar(ctx context.Context, sess *session.Session, semester string) (map[string]any, error) {
	value, err := sess.JWC.Calendar(ctx, semester)
	if err != nil {
		return nil, err
	}
	value["fetched_at"] = time.Now().Unix()
	actualSemester, _ := value["semester"].(string)
	if actualSemester == "" {
		actualSemester = semester
		value["semester"] = semester
	}
	if err := s.saveMap(ctx, calendarKey(actualSemester), value); err != nil {
		return nil, err
	}
	if err := s.syncFirstWeek(ctx, sess.StudentID, value); err != nil {
		return nil, err
	}
	if err := s.syncUserReminderTasks(ctx, sess.StudentID, actualSemester); err != nil {
		s.logger.Warn("校历刷新后同步提醒任务失败", "sid_prefix", maskedSID(sess.StudentID), "error", err)
	}
	return value, nil
}

func (s *Server) calendar(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	semester := s.semesterFor(r, sess)
	raw, err := s.store.Setting(r.Context(), calendarKey(semester))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取教学周历失败")
		return
	}
	cached := decodeMap(raw)
	if fetchedAt := mapUnix(cached, "fetched_at"); fetchedAt > 0 && time.Since(time.Unix(fetchedAt, 0)) < s.cfg.DataCacheTTL {
		if err := s.syncFirstWeek(r.Context(), sess.StudentID, cached); err != nil {
			writeError(w, http.StatusInternalServerError, "同步学期周次失败")
			return
		}
		cached["success"] = true
		cached["cached"] = true
		writeJSON(w, http.StatusOK, cached)
		return
	}
	unlock := sess.Lock()
	defer unlock()
	var value map[string]any
	err = s.withJWC(r.Context(), func() error {
		var fetchErr error
		value, fetchErr = s.fetchCalendar(r.Context(), sess, semester)
		return fetchErr
	})
	if err != nil {
		if len(cached) > 0 {
			cached["success"] = true
			cached["cached"] = true
			cached["stale"] = true
			writeJSON(w, http.StatusOK, cached)
			return
		}
		mapJWCError(w, err, "教学周历获取失败")
		return
	}
	value["success"] = true
	value["cached"] = false
	writeJSON(w, http.StatusOK, value)
}

func (s *Server) refreshCalendar(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	semester := s.semesterFor(r, sess)
	unlock := sess.Lock()
	defer unlock()
	var value map[string]any
	err := s.withJWC(r.Context(), func() error {
		var fetchErr error
		value, fetchErr = s.fetchCalendar(r.Context(), sess, semester)
		return fetchErr
	})
	if err != nil {
		mapJWCError(w, err, "教学周历获取失败")
		return
	}
	value["success"] = true
	value["cached"] = false
	writeJSON(w, http.StatusOK, value)
}

func (s *Server) fetchProgramme(ctx context.Context, sess *session.Session) (map[string]any, error) {
	if isGraduate(sess) {
		return map[string]any{
			"supported": false,
			"courses":   []any{},
			"count":     0,
		}, nil
	}
	value, err := sess.JWC.Programme(ctx)
	if err != nil {
		return nil, err
	}
	value["supported"] = true
	value["fetched_at"] = time.Now().Unix()
	if err := s.saveUserMap(ctx, sess.StudentID, "programme", value); err != nil {
		return nil, err
	}
	semester, err := s.store.UserSetting(ctx, sess.StudentID, "semester")
	if err != nil {
		return nil, err
	}
	if err := s.syncUserReminderTasks(ctx, sess.StudentID, semester); err != nil {
		s.logger.Warn("培养方案刷新后同步提醒任务失败", "sid_prefix", maskedSID(sess.StudentID), "error", err)
	}
	return value, nil
}

func (s *Server) programme(w http.ResponseWriter, r *http.Request) {
	if sess, ok := s.session(r); ok && isGraduate(sess) {
		writeJSON(w, http.StatusOK, map[string]any{
			"success": true, "supported": false, "courses": []any{}, "count": 0,
		})
		return
	}
	s.serveUserStudy(w, r, "programme", "培养方案", func(ctx context.Context, sess *session.Session) (map[string]any, error) {
		return s.fetchProgramme(ctx, sess)
	}, false)
}

func (s *Server) refreshProgramme(w http.ResponseWriter, r *http.Request) {
	s.serveUserStudy(w, r, "programme", "培养方案", func(ctx context.Context, sess *session.Session) (map[string]any, error) {
		return s.fetchProgramme(ctx, sess)
	}, true)
}

func (s *Server) fetchProfile(ctx context.Context, sess *session.Session) (map[string]any, error) {
	value, err := sess.JWC.Profile(ctx)
	if err != nil {
		return nil, err
	}
	value["fetched_at"] = time.Now().Unix()
	if err := s.saveUserMap(ctx, sess.StudentID, "profile", value); err != nil {
		return nil, err
	}
	return value, nil
}

func (s *Server) profile(w http.ResponseWriter, r *http.Request) {
	s.serveUserStudy(w, r, "profile", "学籍信息", func(ctx context.Context, sess *session.Session) (map[string]any, error) {
		return s.fetchProfile(ctx, sess)
	}, false)
}

func (s *Server) refreshProfile(w http.ResponseWriter, r *http.Request) {
	s.serveUserStudy(w, r, "profile", "学籍信息", func(ctx context.Context, sess *session.Session) (map[string]any, error) {
		return s.fetchProfile(ctx, sess)
	}, true)
}

func (s *Server) serveUserStudy(w http.ResponseWriter, r *http.Request, key, label string, fetch func(context.Context, *session.Session) (map[string]any, error), force bool) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	raw, err := s.store.UserSetting(r.Context(), sess.StudentID, key)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取"+label+"失败")
		return
	}
	cached := decodeMap(raw)
	if key == "programme" {
		cached["supported"] = true
	}
	if !force {
		if fetchedAt := mapUnix(cached, "fetched_at"); fetchedAt > 0 && time.Since(time.Unix(fetchedAt, 0)) < s.cfg.DataCacheTTL {
			cached["success"] = true
			cached["cached"] = true
			writeJSON(w, http.StatusOK, cached)
			return
		}
	}
	unlock := sess.Lock()
	defer unlock()
	var value map[string]any
	err = s.withJWC(r.Context(), func() error {
		var fetchErr error
		value, fetchErr = fetch(r.Context(), sess)
		return fetchErr
	})
	if err != nil {
		if !force && len(cached) > 0 {
			cached["success"] = true
			cached["cached"] = true
			cached["stale"] = true
			writeJSON(w, http.StatusOK, cached)
			return
		}
		mapJWCError(w, err, label+"获取失败")
		return
	}
	value["success"] = true
	value["cached"] = false
	writeJSON(w, http.StatusOK, value)
}
