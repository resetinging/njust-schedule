package httpapi

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"database/sql"
	"encoding/base64"
	"errors"
	"fmt"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/naughtygopher/webgo/v7"
	"github.com/resetinging/njust-schedule/internal/store"
)

const adminTokenTTL = 12 * time.Hour

type auditSyncState struct {
	Running    bool   `json:"running"`
	Semester   string `json:"running_semester"`
	StartedAt  int64  `json:"last_started_at"`
	FinishedAt int64  `json:"last_finished_at"`
	Success    *bool  `json:"last_success"`
	Count      int    `json:"last_count"`
	Error      string `json:"last_error"`
}

func (s *Server) adminSignerKey() []byte {
	raw := base64.StdEncoding.EncodeToString(s.cfg.SessionKey)
	sum := sha256.Sum256([]byte("v1|" + raw + "|" + s.cfg.AdminPassword))
	return sum[:]
}

func (s *Server) issueAdminToken() string {
	exp := time.Now().Add(adminTokenTTL).Unix()
	nonce := randomToken(18)
	body := "v2|" + strconv.FormatInt(exp, 10) + "|" + nonce
	mac := hmac.New(sha256.New, s.adminSignerKey())
	_, _ = mac.Write([]byte(body))
	return "v2." + strconv.FormatInt(exp, 10) + "." + nonce + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}

func (s *Server) adminTokenExpiry(token string) (int64, bool) {
	parts := strings.Split(strings.TrimSpace(token), ".")
	if len(parts) != 3 && len(parts) != 4 || parts[0] != "v1" && parts[0] != "v2" {
		return 0, false
	}
	if parts[0] == "v1" && len(parts) != 3 || parts[0] == "v2" && len(parts) != 4 {
		return 0, false
	}
	exp, err := strconv.ParseInt(parts[1], 10, 64)
	if err != nil || exp <= time.Now().Unix() {
		return 0, false
	}
	provided, err := base64.RawURLEncoding.DecodeString(parts[len(parts)-1])
	if err != nil {
		return 0, false
	}
	body := parts[0] + "|" + parts[1]
	if parts[0] == "v2" {
		if len(parts[2]) < 16 || len(parts[2]) > 64 {
			return 0, false
		}
		body += "|" + parts[2]
	}
	mac := hmac.New(sha256.New, s.adminSignerKey())
	_, _ = mac.Write([]byte(body))
	if !hmac.Equal(provided, mac.Sum(nil)) {
		return 0, false
	}
	return exp, true

}

func (s *Server) validAdminToken(token string) bool {
	exp, ok := s.adminTokenExpiry(token)
	if !ok {
		return false
	}
	digest := sha256.Sum256([]byte(strings.TrimSpace(token)))
	now := time.Now().Unix()
	s.adminAuthMu.Lock()
	defer s.adminAuthMu.Unlock()
	for key, expiresAt := range s.adminRevoked {
		if expiresAt <= now {
			delete(s.adminRevoked, key)
		}
	}
	return s.adminRevoked[digest] != exp
}

func (s *Server) revokeAdminToken(token string) {
	exp, ok := s.adminTokenExpiry(token)
	if !ok {
		return
	}
	digest := sha256.Sum256([]byte(strings.TrimSpace(token)))
	s.adminAuthMu.Lock()
	if s.adminRevoked == nil {
		s.adminRevoked = map[[32]byte]int64{}
	}
	s.adminRevoked[digest] = exp
	s.adminAuthMu.Unlock()
}

func (s *Server) requireAdmin(w http.ResponseWriter, r *http.Request) bool {
	if s.validAdminToken(r.Header.Get("X-Admin-Token")) {
		return true
	}
	writeError(w, http.StatusUnauthorized, "未授权，请重新登录")
	return false
}

func (s *Server) adminPage(w http.ResponseWriter, r *http.Request) {
	file := filepath.Join(filepath.Dir(s.cfg.StaticDir), "templates", "admin.html")
	if _, err := os.Stat(file); err != nil {
		http.Error(w, "管理页面不存在", http.StatusNotFound)
		return
	}
	http.ServeFile(w, r, file)
}

func (s *Server) adminLogin(w http.ResponseWriter, r *http.Request) {
	key := "adminfail:" + s.clientIP(r)
	if s.failureCount(key, time.Minute) >= 5 {
		writeError(w, http.StatusTooManyRequests, "尝试次数过多，请稍后再试")
		return
	}
	var body struct {
		Password string `json:"password"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if !hmac.Equal([]byte(body.Password), []byte(s.cfg.AdminPassword)) {
		s.recordFailure(key)
		writeError(w, http.StatusUnauthorized, "密码错误")
		return
	}
	s.clearFailures(key)
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "token": s.issueAdminToken(), "expires_in": int(adminTokenTTL.Seconds())})
}

func (s *Server) failureCount(key string, window time.Duration) int {
	now := time.Now()
	s.rateMu.Lock()
	defer s.rateMu.Unlock()
	values := s.rates[key]
	kept := values[:0]
	for _, value := range values {
		if now.Sub(value) <= window {
			kept = append(kept, value)
		}
	}
	s.rates[key] = kept
	return len(kept)
}

func (s *Server) recordFailure(key string) {
	s.rateMu.Lock()
	s.rates[key] = append(s.rates[key], time.Now())
	s.rateMu.Unlock()
}

func (s *Server) clearFailures(key string) {
	s.rateMu.Lock()
	delete(s.rates, key)
	s.rateMu.Unlock()
}

func (s *Server) adminLogout(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	s.revokeAdminToken(r.Header.Get("X-Admin-Token"))
	writeJSON(w, http.StatusOK, map[string]any{"success": true})
}

func (s *Server) adminCheck(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "logged_in": s.validAdminToken(r.Header.Get("X-Admin-Token"))})
}

func (s *Server) adminSummary(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	counts, err := s.store.AdminCounts(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "统计读取失败")
		return
	}
	users, err := s.store.AdminUsers(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "用户统计读取失败")
		return
	}
	s.adminMu.Lock()
	total := s.adminTotal
	s.adminMu.Unlock()
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "online_sessions": s.sessions.Count(), "total_users": len(users), "requests_total": total, "uptime_sec": int(time.Since(s.adminStarted).Seconds()), "counts": counts})
}

func (s *Server) adminUsers(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	users, err := s.store.AdminUsers(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "用户列表读取失败")
		return
	}
	online := map[string]map[string]any{}
	for _, item := range s.sessions.List() {
		online[fmt.Sprint(item["student_id"])] = item
	}
	hashes := map[string]string{}
	for _, item := range users {
		hashes[s.analyticsHash("sid", item.StudentID)] = item.StudentID
	}
	usage, err := s.store.UsageSummaries(r.Context(), hashes, 30)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "用户活跃统计读取失败")
		return
	}
	result := make([]map[string]any, 0, len(users))
	for _, item := range users {
		current := online[item.StudentID]
		name := item.Name
		if current != nil && strings.TrimSpace(fmt.Sprint(current["student_name"])) != "" {
			name = fmt.Sprint(current["student_name"])
		}
		entry := map[string]any{"student_id": item.StudentID, "name": name, "semester": item.Semester, "courses": item.Courses, "exams": item.Exams, "grades": item.Grades, "best_gpa": item.BestGPA, "online": current != nil, "active_days_30": usage[item.StudentID].ActiveDays, "last_active": usage[item.StudentID].LastActive}
		result = append(result, entry)
	}
	sort.SliceStable(result, func(i, j int) bool {
		if result[i]["online"].(bool) != result[j]["online"].(bool) {
			return result[i]["online"].(bool)
		}
		return result[i]["student_id"].(string) < result[j]["student_id"].(string)
	})
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "users": result})
}

func (s *Server) adminUser(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	sid := strings.TrimSpace(webgo.Context(r).Params()["sid"])
	if !validStudentID(sid) {
		writeError(w, http.StatusBadRequest, "学号无效")
		return
	}
	courses, coursesErr := s.store.AdminCourses(r.Context(), sid)
	exams, examsErr := s.store.AdminExams(r.Context(), sid)
	grades, gradesErr := s.store.Grades(r.Context(), sid, "", "")
	evaluations, evalErr := s.store.Evaluations(r.Context(), sid)
	if errors.Join(coursesErr, examsErr, gradesErr, evalErr) != nil {
		writeError(w, http.StatusInternalServerError, "用户详情读取失败")
		return
	}
	meta, err := s.store.UserSettings(r.Context(), sid, "name", "semester")
	if err != nil {
		writeError(w, http.StatusInternalServerError, "用户信息读取失败")
		return
	}
	name := meta["name"]
	semester := meta["semester"]
	online, loginMethod, accountType := false, "", ""
	for _, item := range s.sessions.List() {
		if fmt.Sprint(item["student_id"]) == sid {
			online, name = true, fmt.Sprint(item["student_name"])
			loginMethod, accountType = fmt.Sprint(item["login_method"]), fmt.Sprint(item["account_type"])
			break
		}
	}
	if name == "" {
		name = sid
	}
	if courses == nil {
		courses = []store.AdminCourse{}
	}
	if exams == nil {
		exams = []store.AdminExam{}
	}
	if grades == nil {
		grades = []store.Grade{}
	}
	if evaluations == nil {
		evaluations = []store.Evaluation{}
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "student_id": sid, "name": name, "semester": semester, "online": online, "login_method": loginMethod, "account_type": accountType, "courses": courses, "exams": exams, "grades": grades, "evaluations": evaluations})
}

func scoreGP(raw string) float64 {
	value := strings.TrimSpace(raw)
	levels := map[string]float64{"优": 4, "优秀": 4, "优+": 4, "优秀+": 4, "优-": 3.7, "优秀-": 3.7, "良+": 3.3, "良好+": 3.3, "良": 3, "良好": 3, "良-": 2.7, "良好-": 2.7, "中+": 2.3, "中等+": 2.3, "中": 2, "中等": 2, "中-": 1.5, "中等-": 1.5, "及格": 1, "通过": 1, "不及格": 0, "不通过": 0}
	if result, ok := levels[value]; ok {
		return result
	}
	for _, marker := range []string{"缓考", "缺考", "免修", "作弊", "违纪", "取消", "旷考", "休学"} {
		if strings.Contains(value, marker) {
			return -1
		}
	}
	number, err := strconv.ParseFloat(value, 64)
	if err != nil {
		return -1
	}
	for _, item := range []struct{ min, gp float64 }{{90, 4}, {85, 3.7}, {82, 3.3}, {78, 3}, {75, 2.7}, {72, 2.3}, {68, 2}, {64, 1.5}, {60, 1}} {
		if number >= item.min {
			return item.gp
		}
	}
	return 0
}

func (s *Server) adminGradeStats(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	rows, err := s.store.AllGradeStats(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "成绩统计失败")
		return
	}
	levels := map[string]int{"优秀": 0, "良好": 0, "中等": 0, "及格": 0, "不及格": 0, "其他": 0}
	best := map[string]float64{}
	type weighted struct{ Sum, Credits float64 }
	semesters := map[string]weighted{}
	for _, row := range rows {
		gp := row.GradePoint
		if gp == 0 {
			gp = scoreGP(row.Score)
		}
		num, numericErr := strconv.ParseFloat(strings.TrimSpace(row.Score), 64)
		switch {
		case numericErr == nil && num >= 90, strings.Contains(row.Score, "优"):
			levels["优秀"]++
		case numericErr == nil && num >= 80, strings.Contains(row.Score, "良"):
			levels["良好"]++
		case numericErr == nil && num >= 70, strings.Contains(row.Score, "中"):
			levels["中等"]++
		case strings.Contains(row.Score, "不及格") || strings.Contains(row.Score, "不通过") || numericErr == nil && num < 60:
			levels["不及格"]++
		case numericErr == nil && num >= 60 || strings.Contains(row.Score, "及格") || strings.Contains(row.Score, "通过"):
			levels["及格"]++
		default:
			levels["其他"]++
		}
		if gp > best[row.StudentID] {
			best[row.StudentID] = gp
		}
		if gp >= 0 && row.Credit > 0 {
			key := row.AcademicYear + "-" + row.Semester
			value := semesters[key]
			value.Sum += row.Credit * gp
			value.Credits += row.Credit
			semesters[key] = value
		}
	}
	hist := map[string]int{"<2.0": 0, "2.0-2.5": 0, "2.5-3.0": 0, "3.0-3.5": 0, "3.5-4.0": 0}
	for _, gp := range best {
		switch {
		case gp < 2:
			hist["<2.0"]++
		case gp < 2.5:
			hist["2.0-2.5"]++
		case gp < 3:
			hist["2.5-3.0"]++
		case gp < 3.5:
			hist["3.0-3.5"]++
		default:
			hist["3.5-4.0"]++
		}
	}
	semGPA := make([]map[string]any, 0, len(semesters))
	for key, value := range semesters {
		if value.Credits > 0 {
			semGPA = append(semGPA, map[string]any{"sem": key, "gpa": math.Round(value.Sum/value.Credits*100) / 100, "credits": math.Round(value.Credits*10) / 10})
		}
	}
	sort.Slice(semGPA, func(i, j int) bool { return semGPA[i]["sem"].(string) > semGPA[j]["sem"].(string) })
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "level_dist": levels, "gpa_hist": hist, "sem_gpa": semGPA})
}

func maskAdminSID(value string) string {
	value = strings.TrimSpace(value)
	if len(value) < 7 {
		return value
	}
	return value[:3] + "****" + value[len(value)-3:]
}

func (s *Server) adminRequests(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	since, _ := strconv.ParseInt(r.URL.Query().Get("since"), 10, 64)
	cutoff := time.Now().Add(-15 * time.Minute).Unix()
	s.adminMu.Lock()
	items := make([]requestRecord, 0, len(s.adminRecent))
	for _, item := range s.adminRecent {
		if item.ID > since && int64(item.Epoch) >= cutoff {
			item.SID = maskAdminSID(item.SID)
			items = append(items, item)
		}
	}
	s.adminMu.Unlock()
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "requests": items})
}

func (s *Server) adminSessions(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	items := s.sessions.List()
	sort.Slice(items, func(i, j int) bool { return number(items[i]["active_sec"]) < number(items[j]["active_sec"]) })
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "sessions": items})
}

func (s *Server) adminDeleteSession(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	sid := strings.TrimSpace(webgo.Context(r).Params()["sid"])
	if !validStudentID(sid) {
		writeError(w, http.StatusBadRequest, "学号无效")
		return
	}
	removed, err := s.sessions.DeleteStudent(r.Context(), sid)
	if err != nil {
		s.logger.Error("管理员删除会话失败", "sid_prefix", maskedSID(sid), "error", err)
		writeError(w, http.StatusServiceUnavailable, "删除会话失败，请稍后重试")
		return
	}
	count := 0
	if removed {
		count = 1
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "student_id": sid, "removed": count, "message": "会话已删除，Cookie 已保留"})
}

func (s *Server) auditStatus(ctx context.Context, semester string) map[string]any {
	count, countErr := s.store.AuditCount(ctx, semester)
	raw, settingErr := s.store.Setting(ctx, "audit_catalog_at:"+semester)
	err := errors.Join(countErr, settingErr)
	updated, _ := strconv.ParseInt(raw, 10, 64)
	s.auditMu.Lock()
	state := s.auditSync
	s.auditMu.Unlock()
	return map[string]any{"semester": semester, "course_count": count, "updated_at": updated, "empty": count <= 0, "needs_refresh": err != nil || count <= 0 || time.Since(time.Unix(updated, 0)) >= 24*time.Hour, "db_error": errorText(err), "running": state.Running, "running_semester": state.Semester, "last_started_at": state.StartedAt, "last_finished_at": state.FinishedAt, "last_success": state.Success, "last_count": state.Count, "last_error": state.Error}
}

func errorText(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}

func (s *Server) adminAuditStatus(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	payload := s.auditStatus(r.Context(), currentSemester())
	payload["success"] = true
	writeJSON(w, http.StatusOK, payload)
}

func (s *Server) adminAuditSync(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	semester := currentSemester()
	started := s.startAuditSync(semester)
	status := s.auditStatus(r.Context(), semester)
	message := "已有同步任务正在运行"
	code := http.StatusOK
	if started {
		message, code = "已开始后台刷新，完成后课程目录会自动更新", http.StatusAccepted
	}
	writeJSON(w, code, map[string]any{"success": true, "started": started, "message": message, "status": status})
}

func (s *Server) startAuditSync(semester string) bool {
	s.auditMu.Lock()
	if s.auditSync.Running {
		s.auditMu.Unlock()
		return false
	}
	s.auditSync = auditSyncState{Running: true, Semester: semester, StartedAt: time.Now().Unix()}
	s.auditMu.Unlock()
	s.wg.Add(1)
	go func() {
		defer s.wg.Done()
		ctx, cancel := context.WithTimeout(s.ctx, time.Hour)
		defer cancel()
		count, err := s.syncAuditCatalog(ctx, semester)
		success := err == nil
		if err != nil {
			s.logger.Warn("蹭课目录同步失败", "semester", semester, "error", err)
		} else {
			s.logger.Info("蹭课目录同步完成", "semester", semester, "count", count)
		}
		s.auditMu.Lock()
		s.auditSync.Running = false
		s.auditSync.FinishedAt = time.Now().Unix()
		s.auditSync.Success = &success
		s.auditSync.Count = count
		s.auditSync.Error = errorText(err)
		s.auditMu.Unlock()
	}()
	return true
}

func (s *Server) syncAuditCatalog(ctx context.Context, semester string) (int, error) {
	var lastErr error
	candidates := s.randomPersistentClients(ctx)
	defer closeSharedJWCCandidates(candidates)
	for _, candidate := range candidates {
		var courses []store.AuditCourse
		candidateCtx, cancel := contextWithSession(ctx, candidate.sess)
		unlock := func() {}
		if candidate.sess != nil {
			unlock = candidate.sess.Lock()
		}
		err := s.withJWC(candidateCtx, func() error {
			if err := candidate.client.Resume(candidateCtx, candidate.sid); err != nil {
				return err
			}
			var fetchErr error
			courses, fetchErr = candidate.client.AuditCatalog(candidateCtx, semester)
			return fetchErr
		})
		unlock()
		cancel()
		if err == nil && len(courses) > 0 {
			if err = s.store.ReplaceAuditCourses(ctx, semester, courses); err == nil {
				if err = s.store.SetSetting(ctx, "audit_catalog_at:"+semester, strconv.FormatInt(time.Now().Unix(), 10)); err != nil {
					return 0, fmt.Errorf("保存蹭课目录版本: %w", err)
				}
				return len(courses), nil
			}
		}
		lastErr = err
	}
	_, client, err := s.serviceAccountClient(ctx)
	if err == nil {
		defer client.CloseIdleConnections()
		var courses []store.AuditCourse
		err = s.withJWC(ctx, func() error {
			var fetchErr error
			courses, fetchErr = client.AuditCatalog(ctx, semester)
			return fetchErr
		})
		if err == nil && len(courses) > 0 {
			if err = s.store.ReplaceAuditCourses(ctx, semester, courses); err == nil {
				if err = s.store.SetSetting(ctx, "audit_catalog_at:"+semester, strconv.FormatInt(time.Now().Unix(), 10)); err != nil {
					return 0, fmt.Errorf("保存蹭课目录版本: %w", err)
				}
				return len(courses), nil
			}
		}
	}
	if err != nil {
		lastErr = err
	}
	if lastErr == nil {
		lastErr = errors.New("没有可用的本科教务 Cookie")
	}
	return 0, lastErr
}

func (s *Server) adminRequestStats(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	minutes, statuses, paths := map[string]int{}, map[string]int{}, map[string]int{}
	s.adminMu.Lock()
	for _, item := range s.adminRecent {
		minutes[item.TS[:5]]++
		statuses[strconv.Itoa(item.Status)]++
		paths[strings.Split(item.Path, "?")[0]]++
	}
	s.adminMu.Unlock()
	type pathCount struct {
		Path  string
		Count int
	}
	ordered := make([]pathCount, 0, len(paths))
	for key, count := range paths {
		ordered = append(ordered, pathCount{key, count})
	}
	sort.Slice(ordered, func(i, j int) bool { return ordered[i].Count > ordered[j].Count })
	top := map[string]int{}
	for _, item := range ordered[:min(10, len(ordered))] {
		top[item.Path] = item.Count
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "minutes": minutes, "statuses": statuses, "top_paths": top})
}

func (s *Server) adminAnnouncement(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	settings, err := s.store.Settings(r.Context(), "announcement_text", "announcement_enabled", "announcement_updated")
	if err != nil {
		writeError(w, http.StatusInternalServerError, "公告读取失败")
		return
	}
	text, enabled, updated := settings["announcement_text"], settings["announcement_enabled"], settings["announcement_updated"]
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "text": text, "enabled": enabled != "0", "updated": updated})
}

func (s *Server) adminSaveAnnouncement(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	var body struct {
		Text    string `json:"text"`
		Enabled bool   `json:"enabled"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	text := strings.TrimSpace(body.Text)
	if len([]rune(text)) > 500 {
		writeError(w, http.StatusBadRequest, "公告不能超过 500 字")
		return
	}
	enabled := "0"
	if body.Enabled {
		enabled = "1"
	}
	now := time.Now().In(beijing).Format("2006-01-02 15:04:05")
	if err := s.store.SetSettings(r.Context(), map[string]string{"announcement_text": text, "announcement_enabled": enabled, "announcement_updated": now}); err != nil {
		writeError(w, http.StatusInternalServerError, "公告保存失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true})
}

func (s *Server) servicePassword(ctx context.Context) (string, bool, error) {
	raw, err := s.store.Setting(ctx, "free_classroom_pwd")
	if err != nil {
		return "", false, err
	}
	if raw == "" {
		return "", false, nil
	}
	if strings.HasPrefix(raw, "enc:v1:") {
		var value struct {
			Password string `json:"pwd"`
		}
		if err = s.crypto.Decrypt("freeclass-service-account", strings.TrimPrefix(raw, "enc:v1:"), &value); err != nil {
			return "", false, fmt.Errorf("解密服务账号密码: %w", err)
		}
		return value.Password, value.Password != "", nil
	}
	return raw, true, nil
}

func (s *Server) adminFreeclassAccount(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	settings, err := s.store.Settings(r.Context(), "free_classroom_sid", "free_classroom_pwd_updated")
	if err != nil {
		writeError(w, http.StatusInternalServerError, "服务账号配置读取失败")
		return
	}
	sid := settings["free_classroom_sid"]
	if sid == "" {
		sid = s.cfg.FreeClassroomSID
	}
	_, hasPassword, err := s.servicePassword(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "服务账号密码读取失败")
		return
	}
	updated := settings["free_classroom_pwd_updated"]
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "sid": sid, "has_password": hasPassword, "updated": updated})
}

func (s *Server) adminSaveFreeclassAccount(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	var body struct {
		SID      string `json:"sid"`
		Password string `json:"password"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	updates := map[string]string{}
	if sid := strings.TrimSpace(body.SID); sid != "" {
		if !validStudentID(sid) {
			writeError(w, http.StatusBadRequest, "学号无效")
			return
		}
		updates["free_classroom_sid"] = sid
	}
	if password := body.Password; password != "" {
		blob, err := s.crypto.Encrypt("freeclass-service-account", map[string]string{"pwd": password})
		if err != nil {
			writeError(w, http.StatusInternalServerError, "服务账号密码加密失败")
			return
		}
		updates["free_classroom_pwd"] = "enc:v1:" + blob
		updates["free_classroom_pwd_updated"] = time.Now().In(beijing).Format("2006-01-02 15:04:05")
	}
	if err := s.store.SetSettings(r.Context(), updates); err != nil {
		writeError(w, http.StatusInternalServerError, "服务账号保存失败")
		return
	}
	s.adminFreeclassAccount(w, r)
}

func (s *Server) adminFetchNames(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	writeJSON(w, http.StatusBadRequest, map[string]any{"success": false, "message": "默认密码补全功能已下线，请让用户通过智慧理工登录"})
}

func (s *Server) adminFeedback(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	status := strings.TrimSpace(r.URL.Query().Get("status"))
	if status != "" && status != "pending" && status != "done" {
		writeError(w, http.StatusBadRequest, "状态无效")
		return
	}
	items, err := s.store.FeedbackList(r.Context(), status, 500)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "反馈读取失败")
		return
	}
	result := make([]map[string]any, 0, len(items))
	for _, item := range items {
		result = append(result, item.JSON())
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "feedback": result})
}

func adminFeedbackID(r *http.Request) (int64, error) {
	return strconv.ParseInt(webgo.Context(r).Params()["fid"], 10, 64)
}

func (s *Server) adminFeedbackStatus(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	id, err := adminFeedbackID(r)
	var body struct {
		Status string `json:"status"`
	}
	if err != nil || decodeJSON(r, &body) != nil || body.Status != "pending" && body.Status != "done" {
		writeError(w, http.StatusBadRequest, "参数无效")
		return
	}
	ok, err := s.store.SetFeedbackStatus(r.Context(), id, body.Status)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "反馈状态更新失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": ok})
}

func (s *Server) adminDeleteFeedback(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	id, err := adminFeedbackID(r)
	if err != nil {
		writeError(w, http.StatusBadRequest, "参数无效")
		return
	}
	ok, err := s.store.DeleteFeedback(r.Context(), id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "反馈删除失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": ok})
}

func (s *Server) adminReplyFeedback(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	id, err := adminFeedbackID(r)
	var body struct {
		Reply string `json:"reply"`
	}
	if err != nil || decodeJSON(r, &body) != nil {
		writeError(w, http.StatusBadRequest, "参数无效")
		return
	}
	item, err := s.store.ReplyFeedback(r.Context(), id, body.Reply)
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			writeError(w, http.StatusNotFound, "反馈不存在")
		} else {
			writeError(w, http.StatusInternalServerError, "回复保存失败")
		}
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "feedback": item.JSON()})
}

// adminAnalytics is kept in this file because it is a read-only report over the
// aggregate tables; no user content or credentials are exposed.
func (s *Server) adminAnalytics(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	days := parseInt(r.URL.Query().Get("days"), 30, 1, 90)
	payload, err := s.analyticsReport(r.Context(), days)
	if err != nil {
		s.logger.Warn("使用统计聚合失败", "error", err)
		writeError(w, http.StatusInternalServerError, "统计聚合失败")
		return
	}
	payload["success"] = true
	writeJSON(w, http.StatusOK, payload)
}

func (s *Server) analyticsReport(ctx context.Context, days int) (map[string]any, error) {
	type overview struct{ DAU, Yesterday, WAU, MAU, NewToday, Total, Opens, Sessions, Seconds, Pages int }
	var o overview
	queries := []struct {
		query string
		dest  []any
	}{
		{`SELECT COUNT(*),COALESCE(SUM(open_count),0),COALESCE(SUM(session_count),0),COALESCE(SUM(active_seconds),0),COALESCE(SUM(page_views),0) FROM usage_user_daily WHERE date=CURDATE()`, []any{&o.DAU, &o.Opens, &o.Sessions, &o.Seconds, &o.Pages}},
		{`SELECT COUNT(*) FROM usage_user_daily WHERE date=DATE_SUB(CURDATE(),INTERVAL 1 DAY)`, []any{&o.Yesterday}},
		{`SELECT COUNT(DISTINCT analytics_id) FROM usage_user_daily WHERE date>=DATE_SUB(CURDATE(),INTERVAL 6 DAY)`, []any{&o.WAU}},
		{`SELECT COUNT(DISTINCT analytics_id) FROM usage_user_daily WHERE date>=DATE_SUB(CURDATE(),INTERVAL 29 DAY)`, []any{&o.MAU}},
		{`SELECT COUNT(*) FROM (SELECT analytics_id,MIN(date) first_date FROM usage_user_daily GROUP BY analytics_id HAVING first_date=CURDATE()) x`, []any{&o.NewToday}},
		{`SELECT COUNT(DISTINCT analytics_id) FROM usage_user_daily`, []any{&o.Total}},
	}
	for _, item := range queries {
		if err := s.db.QueryRowContext(ctx, item.query).Scan(item.dest...); err != nil {
			return nil, err
		}
	}
	trend := make([]map[string]any, 0, days)
	trendMap := map[string]map[string]any{}
	for offset := days - 1; offset >= 0; offset-- {
		day := time.Now().In(beijing).AddDate(0, 0, -offset).Format("2006-01-02")
		item := map[string]any{"date": day[5:], "dau": 0, "new_users": 0, "opens": 0, "sessions": 0, "active_seconds": 0}
		trend, trendMap[day] = append(trend, item), item
	}
	rows, err := s.db.QueryContext(ctx, `SELECT DATE_FORMAT(date,'%Y-%m-%d'),COUNT(*),COALESCE(SUM(open_count),0),COALESCE(SUM(session_count),0),COALESCE(SUM(active_seconds),0) FROM usage_user_daily WHERE date>=DATE_SUB(CURDATE(),INTERVAL ? DAY) GROUP BY date ORDER BY date`, days-1)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var day string
		var dau, opens, sessions, seconds int
		if err = rows.Scan(&day, &dau, &opens, &sessions, &seconds); err != nil {
			_ = rows.Close()
			return nil, err
		}
		if item := trendMap[day]; item != nil {
			item["dau"], item["opens"], item["sessions"], item["active_seconds"] = dau, opens, sessions, seconds
		}
	}
	if err = rows.Err(); err != nil {
		_ = rows.Close()
		return nil, err
	}
	if err = rows.Close(); err != nil {
		return nil, err
	}
	pages, err := s.analyticsRanking(ctx, `SELECT page,COUNT(*),COUNT(DISTINCT analytics_id) FROM usage_events WHERE created_at>=DATE_SUB(CURDATE(),INTERVAL ? DAY) AND event_name='page_view' AND page<>'' GROUP BY page ORDER BY COUNT(*) DESC LIMIT 20`, days-1, "page")
	if err != nil {
		return nil, err
	}
	features, err := s.analyticsRanking(ctx, `SELECT feature,COUNT(*),COUNT(DISTINCT analytics_id) FROM usage_events WHERE created_at>=DATE_SUB(CURDATE(),INTERVAL ? DAY) AND feature<>'' GROUP BY feature ORDER BY COUNT(*) DESC LIMIT 20`, days-1, "feature")
	if err != nil {
		return nil, err
	}
	hourly := map[string]int{}
	for hour := 0; hour < 24; hour++ {
		hourly[strconv.Itoa(hour)] = 0
	}
	rows, err = s.db.QueryContext(ctx, `SELECT HOUR(created_at),COUNT(*) FROM usage_events WHERE created_at IS NOT NULL AND created_at>=DATE_SUB(CURDATE(),INTERVAL 6 DAY) GROUP BY HOUR(created_at)`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var hour, count int
		if err = rows.Scan(&hour, &count); err != nil {
			_ = rows.Close()
			return nil, err
		}
		hourly[strconv.Itoa(hour)] = count
	}
	if err = rows.Err(); err != nil {
		_ = rows.Close()
		return nil, err
	}
	if err = rows.Close(); err != nil {
		return nil, err
	}
	slots := []map[string]any{}
	rows, err = s.db.QueryContext(ctx, `SELECT COALESCE(slot_id,''),COALESCE(ad_type,''),COALESCE(MAX(page),''),
		COALESCE(SUM(views),0),COALESCE(SUM(visible_count),0),COALESCE(SUM(visible_ms),0),
		COALESCE(SUM(requests),0),COALESCE(SUM(impressions),0),COALESCE(SUM(clicks),0),
		COALESCE(SUM(closes),0),COUNT(DISTINCT analytics_id)
		FROM usage_slot_user_daily WHERE date>=DATE_SUB(CURDATE(),INTERVAL ? DAY)
		GROUP BY COALESCE(slot_id,''),COALESCE(ad_type,'') ORDER BY COALESCE(SUM(visible_count),0) DESC LIMIT 50`, days-1)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var slot, adType, page string
		var views, visible, visibleMS, requests, impressions, clicks, closes, users int
		if err = rows.Scan(&slot, &adType, &page, &views, &visible, &visibleMS, &requests, &impressions, &clicks, &closes, &users); err != nil {
			_ = rows.Close()
			return nil, err
		}
		if adType == "" {
			adType = "未指定"
		}
		slots = append(slots, map[string]any{
			"slot_id": slot, "ad_type": adType, "page": page,
			"views": views, "visible_count": visible, "visible_ms": visibleMS,
			"visible_per_user":    analyticsPerUser(visible, users),
			"avg_visible_seconds": analyticsAverageSeconds(visibleMS, visible),
			"requests":            requests, "impressions": impressions,
			"clicks": clicks, "closes": closes, "users": users,
			"fill_rate":  analyticsRate(impressions, requests),
			"ctr":        analyticsRate(clicks, impressions),
			"close_rate": analyticsRate(closes, impressions),
		})
	}
	if err = rows.Err(); err != nil {
		_ = rows.Close()
		return nil, err
	}
	if err = rows.Close(); err != nil {
		return nil, err
	}
	retention := map[string]any{}
	for _, item := range []struct {
		key  string
		days int
	}{{"d1", 1}, {"d7", 7}, {"d30", 30}} {
		var eligible, retained int
		err = s.db.QueryRowContext(ctx, `SELECT COUNT(*),COALESCE(SUM(EXISTS(SELECT 1 FROM usage_user_daily later WHERE later.analytics_id=firsts.analytics_id AND later.date=DATE_ADD(firsts.first_date,INTERVAL ? DAY))),0) FROM (SELECT analytics_id,MIN(date) first_date FROM usage_user_daily GROUP BY analytics_id HAVING first_date<=DATE_SUB(CURDATE(),INTERVAL ? DAY)) firsts`, item.days, item.days).Scan(&eligible, &retained)
		if err != nil {
			return nil, err
		}
		rate := 0.0
		if eligible > 0 {
			rate = math.Round(float64(retained)*1000/float64(eligible)) / 10
		}
		retention[item.key] = map[string]any{"eligible": eligible, "retained": retained, "rate": rate}
	}
	avg := 0
	if o.DAU > 0 {
		avg = o.Seconds / o.DAU
	}
	return map[string]any{"days": days, "overview": map[string]any{"dau": o.DAU, "dau_yesterday": o.Yesterday, "wau": o.WAU, "mau": o.MAU, "new_users_today": o.NewToday, "total_users": o.Total, "opens_today": o.Opens, "sessions_today": o.Sessions, "active_seconds_today": o.Seconds, "avg_seconds_today": avg, "page_views_today": o.Pages}, "trend": trend, "retention": retention, "pages": pages, "features": features, "slots": slots, "hourly": hourly}, nil
}

func analyticsPerUser(value, users int) float64 {
	if users <= 0 {
		return 0
	}
	return math.Round(float64(value)/float64(users)*10) / 10
}

func analyticsAverageSeconds(totalMS, count int) float64 {
	if count <= 0 {
		return 0
	}
	return math.Round(float64(totalMS)/float64(count)/100) / 10
}

func analyticsRate(numerator, denominator int) any {
	if denominator <= 0 {
		return nil
	}
	return math.Round(float64(numerator)*1000/float64(denominator)) / 10
}

func (s *Server) analyticsRanking(ctx context.Context, query string, days int, key string) ([]map[string]any, error) {
	rows, err := s.db.QueryContext(ctx, query, days)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var result []map[string]any
	for rows.Next() {
		var name string
		var events, users int
		if err = rows.Scan(&name, &events, &users); err != nil {
			return nil, err
		}
		result = append(result, map[string]any{key: name, "events": events, "users": users})
	}
	return result, rows.Err()
}
