package httpapi

import (
	"context"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"
)

func (s *Server) metrics(w http.ResponseWriter, _ *http.Request) {
	s.adminMu.Lock()
	total := s.adminTotal
	s.adminMu.Unlock()
	w.Header().Set("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = fmt.Fprintf(w, "# HELP njust_http_requests_total Total HTTP requests.\n# TYPE njust_http_requests_total counter\nnjust_http_requests_total %d\n", total)
}

func (s *Server) status(w http.ResponseWriter, r *http.Request) {
	sess, loggedIn := s.session(r)
	sid, name, method, accountType := "", "", "", "undergraduate"
	semester := currentSemester()
	hasCourses, hasExams := false, false
	refreshState := map[string]any{"state": "idle", "updated_at": int64(0)}
	if loggedIn {
		sid, name, method, accountType = sess.StudentID, sess.StudentName, sess.LoginMethod, sess.AccountType
		semester = s.semesterFor(r, sess)
		courses, exams, err := s.store.CountUserData(r.Context(), sid, semester)
		if err == nil {
			hasCourses, hasExams = courses > 0, exams > 0
		} else {
			s.logger.Warn("读取用户数据状态失败", "sid_prefix", maskedSID(sid), "semester", semester, "error", err)
		}
		if isGraduate(sess) {
			hasCourses = true
		}
		if state := sess.GetRefreshState(); state != nil {
			refreshState = state
		}
	}
	firstWeek, err := s.store.Setting(r.Context(), "first_week_date")
	if err != nil {
		s.logger.Warn("读取默认教学周次失败", "error", err)
	}
	if loggedIn && semester != "" {
		if value, settingErr := s.store.UserSetting(r.Context(), sid, "first_week_date:"+semester); settingErr != nil {
			s.logger.Warn("读取用户教学周次失败", "sid_prefix", maskedSID(sid), "semester", semester, "error", settingErr)
		} else if value != "" {
			firstWeek = value
		}
	}
	network := s.networkStatus(r.Context(), false)
	writeJSON(w, http.StatusOK, map[string]any{
		"logged_in": loggedIn, "student_id": sid, "student_name": name,
		"semester": semester, "has_courses": hasCourses, "has_exams": hasExams,
		"login_method": method, "account_type": accountType, "auto_login_attempted": false,
		"auto_login_error": "", "server_time": time.Now().In(beijing).Format("2006-01-02 15:04:05"),
		"first_week_date": firstWeek, "network": network, "data_refresh": refreshState,
		"api_version": 5,
		"features":    []string{"yjs", "freeclass", "font_subset", "refresh_dedupe", "credential_relogin", "prefetch_status", "usage_analytics", "audit_courses", "general_education", "qr_login", "webgo"},
	})
}

func (s *Server) prefetchStatus(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	state := sess.GetRefreshState()
	if state == nil {
		state = map[string]any{"state": "idle", "updated_at": int64(0)}
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "data_refresh": state})
}

func (s *Server) networkStatus(ctx context.Context, force bool) map[string]any {
	const key = "network-status"
	if !force {
		if value, ok := s.cacheGet(key); ok {
			return value.(map[string]any)
		}
		return map[string]any{
			"reachable": false, "method": "checking", "latency_ms": 0,
			"label": "检测中", "hint": "正在检测教务系统连接", "message": "正在检测智慧理工连接",
		}
	}
	started := time.Now()
	probeCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(probeCtx, http.MethodGet, "https://ids.njust.edu.cn/authserver/login", nil)
	resp, err := http.DefaultClient.Do(req)
	ok := err == nil
	if resp != nil {
		_ = resp.Body.Close()
		ok = ok && resp.StatusCode < 500
	}
	value := map[string]any{
		"reachable": ok, "method": map[bool]string{true: "direct", false: "offline"}[ok],
		"latency_ms": time.Since(started).Milliseconds(), "label": map[bool]string{true: "教务在线", false: "离线"}[ok],
		"hint": map[bool]string{true: "", false: "请检查教务系统连接"}[ok],
	}
	s.cacheSet(key, value, 5*time.Minute)
	return value
}

func (s *Server) connectTest(w http.ResponseWriter, r *http.Request) {
	if s.rateLimited("connect-test:"+s.clientIP(r), 6, time.Minute) {
		writeError(w, http.StatusTooManyRequests, "测试连接过于频繁，请稍后再试")
		return
	}
	value := s.networkStatus(r.Context(), true)
	message := "无法连接智慧理工"
	if value["reachable"] == true {
		message = "智慧理工连接正常"
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": value["reachable"], "message": message})
}

func (s *Server) getSettings(w http.ResponseWriter, r *http.Request) {
	sess, loggedIn := s.session(r)
	sid, name := "", ""
	semester := currentSemester()
	userSettings := map[string]string{}
	if loggedIn {
		sid, name = sess.StudentID, sess.StudentName
		var err error
		userSettings, err = s.store.UserSettings(r.Context(), sid, "semester", "auto_refresh", "refresh_interval")
		if err != nil {
			writeError(w, http.StatusInternalServerError, "读取用户设置失败")
			return
		}
		if userSettings["semester"] != "" {
			semester = userSettings["semester"]
		}
	}
	firstWeek, err := s.store.Setting(r.Context(), "first_week_date")
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取默认设置失败")
		return
	}
	autoRefresh, refreshInterval := "false", "3600"
	if loggedIn {
		if value, settingErr := s.store.UserSetting(r.Context(), sid, "first_week_date:"+semester); settingErr != nil {
			writeError(w, http.StatusInternalServerError, "读取学期设置失败")
			return
		} else if value != "" {
			firstWeek = value
		}
		if userSettings["auto_refresh"] != "" {
			autoRefresh = userSettings["auto_refresh"]
		}
		if userSettings["refresh_interval"] != "" {
			refreshInterval = userSettings["refresh_interval"]
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"student_id": sid, "student_name": name, "semester": semester,
		"auto_refresh": autoRefresh, "refresh_interval": refreshInterval,
		"first_week_date": firstWeek, "semester_list": semesterList(), "current_semester": currentSemester(),
	})
}

func (s *Server) saveSettings(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	var body map[string]any
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	updates := map[string]string{}
	if raw, exists := body["semester"]; exists {
		semester := strings.TrimSpace(fmt.Sprint(raw))
		if semester != "" && !validSemester(semester, false) {
			writeError(w, http.StatusBadRequest, "学期格式无效")
			return
		}
		if semester != "" {
			updates["semester"] = semester
		}
	}
	if raw, exists := body["auto_refresh"]; exists {
		value, err := strconv.ParseBool(strings.TrimSpace(fmt.Sprint(raw)))
		if err != nil {
			writeError(w, http.StatusBadRequest, "自动刷新设置无效")
			return
		}
		updates["auto_refresh"] = strconv.FormatBool(value)
	}
	if raw, exists := body["refresh_interval"]; exists {
		value, err := strconv.Atoi(strings.TrimSpace(fmt.Sprint(raw)))
		if err != nil || value < 60 || value > 30*24*60*60 {
			writeError(w, http.StatusBadRequest, "刷新间隔无效")
			return
		}
		updates["refresh_interval"] = strconv.Itoa(value)
	}
	if raw, exists := body["first_week_date"]; exists {
		firstWeek := strings.TrimSpace(fmt.Sprint(raw))
		if firstWeek != "" && !validISODate(firstWeek) {
			writeError(w, http.StatusBadRequest, "第一周日期格式无效")
			return
		}
		semester := strings.TrimSpace(updates["semester"])
		if semester == "" {
			var err error
			semester, err = s.store.UserSetting(r.Context(), sess.StudentID, "semester")
			if err != nil {
				writeError(w, http.StatusInternalServerError, "读取当前学期失败")
				return
			}
		}
		if semester != "" {
			updates["first_week_date:"+semester] = firstWeek
		}
	}
	if err := s.store.SetUserSettings(r.Context(), sess.StudentID, updates); err != nil {
		writeError(w, http.StatusInternalServerError, "保存设置失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "message": "设置已保存"})
}

func (s *Server) semesters(w http.ResponseWriter, r *http.Request) {
	if sess, ok := s.session(r); ok && isGraduate(sess) {
		payload, err := s.graduateCourses(r.Context(), sess, false)
		if err != nil {
			mapJWCError(w, err, "获取研究生学期列表失败")
			return
		}
		semesters, _ := payload["semesters"].([]string)
		current := ""
		if len(semesters) > 0 {
			current = semesters[0]
		}
		writeJSON(w, http.StatusOK, map[string]any{"success": true, "semesters": semesters, "current": current})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "semesters": semesterList(), "current": currentSemester()})
}

func (s *Server) setSemester(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	var body struct {
		Semester string `json:"semester"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	body.Semester = strings.TrimSpace(body.Semester)
	if !validSemester(body.Semester, false) {
		writeError(w, http.StatusBadRequest, "学期格式无效")
		return
	}
	if err := s.store.SetUserSetting(r.Context(), sess.StudentID, "semester", body.Semester); err != nil {
		writeError(w, http.StatusInternalServerError, "保存学期失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "message": "已切换到学期: " + body.Semester})
}

func (s *Server) clearData(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	semester := s.semesterFor(r, sess)
	if err := s.store.ClearSemester(r.Context(), sess.StudentID, semester); err != nil {
		writeError(w, http.StatusInternalServerError, "清除数据失败")
		return
	}
	if err := s.store.DeleteUserSetting(r.Context(), sess.StudentID, "data_cache_at"); err != nil {
		s.logger.Warn("清除数据后删除缓存标记失败", "sid_prefix", maskedSID(sess.StudentID), "semester", semester, "error", err)
	}
	s.cacheDeletePrefix(sess.StudentID + ":")
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "message": "数据已清除"})
}

func (s *Server) syncVersions(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	semester := s.semesterFor(r, sess)
	versions, err := s.store.DataVersions(r.Context(), sess.StudentID, semester)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取数据版本失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "semester": semester, "versions": versions})
}

func boolText(value bool) string { return strconv.FormatBool(value) }
