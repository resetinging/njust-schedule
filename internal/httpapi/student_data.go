package httpapi

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/resetinging/njust-schedule/internal/jwc"
	"github.com/resetinging/njust-schedule/internal/session"
	"github.com/resetinging/njust-schedule/internal/store"
)

var errNoCETScores = errors.New("未获取到四六级成绩")

type refreshAllResult struct {
	schedule map[string]any
	exams    map[string]any
}

type prefetchStep struct {
	name string
	fn   func() error
}

func (s *Server) courses(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	if isGraduate(sess) {
		payload, err := s.graduateCourses(r.Context(), sess, false)
		if err != nil {
			mapJWCError(w, err, "获取研究生课表失败")
			return
		}
		writeJSON(w, http.StatusOK, payload)
		return
	}
	semester := s.semesterFor(r, sess)
	values, err := s.store.Courses(r.Context(), sess.StudentID, semester)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取课表失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "semester": semester, "count": len(values), "courses": nonNilCourses(values)})
}

func nonNilCourses(values []store.Course) []store.Course {
	if values == nil {
		return []store.Course{}
	}
	seen := map[string]bool{}
	out := make([]store.Course, 0, len(values))
	for _, value := range values {
		key := fmt.Sprintf("%s|%d|%d|%d|%s|%s|%s", value.Name, value.Day, value.Start, value.End, value.Weeks, value.Teacher, value.Classroom)
		if seen[key] {
			continue
		}
		seen[key] = true
		out = append(out, value)
	}
	return out
}

func (s *Server) exams(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	if isGraduate(sess) {
		payload, err := s.graduateTable(r.Context(), sess, "exams", false)
		if err != nil {
			mapJWCError(w, err, "获取研究生考试失败")
			return
		}
		writeJSON(w, http.StatusOK, payload)
		return
	}
	semester := s.semesterFor(r, sess)
	values, err := s.store.Exams(r.Context(), sess.StudentID, semester)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取考试安排失败")
		return
	}
	if values == nil {
		values = []store.Exam{}
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "semester": semester, "count": len(values), "exams": values})
}

func (s *Server) refreshSchedule(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	if isGraduate(sess) {
		payload, err := s.graduateCourses(r.Context(), sess, true)
		if err != nil {
			mapJWCError(w, err, "获取研究生课表失败")
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"success": true, "count": payload["count"], "semester": payload["semester"]})
		return
	}
	semester := s.semesterFor(r, sess)
	values, err := doOnceValue(r.Context(), s, "schedule:"+sess.StudentID+":"+semester, func(ctx context.Context) ([]store.Course, error) {
		unlock := sess.Lock()
		defer unlock()
		var values []store.Course
		if err := s.withJWC(ctx, func() error {
			var err error
			values, err = sess.JWC.Courses(ctx, semester)
			return err
		}); err != nil {
			return nil, err
		}
		if err := s.store.ReplaceCourses(ctx, sess.StudentID, semester, values); err != nil {
			return nil, err
		}
		return values, s.store.SetUserSetting(ctx, sess.StudentID, "semester", semester)
	})
	if err != nil {
		mapJWCError(w, err, "获取课表失败")
		return
	}
	s.cacheDeletePrefix(sess.StudentID + ":")
	if err := s.syncUserReminderTasks(r.Context(), sess.StudentID, semester); err != nil {
		s.logger.Warn("课表刷新后同步提醒任务失败", "sid_prefix", maskedSID(sess.StudentID), "error", err)
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "message": fmt.Sprintf("成功获取 %d 门课程", len(values)), "count": len(values), "semester": semester})
}

func (s *Server) refreshExams(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	if isGraduate(sess) {
		payload, err := s.graduateTable(r.Context(), sess, "exams", true)
		if err != nil {
			mapJWCError(w, err, "获取研究生考试失败")
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"success": true, "count": payload["count"]})
		return
	}
	semester := s.semesterFor(r, sess)
	values, err := doOnceValue(r.Context(), s, "exams:"+sess.StudentID+":"+semester, func(ctx context.Context) ([]store.Exam, error) {
		unlock := sess.Lock()
		defer unlock()
		var values []store.Exam
		if err := s.withJWC(ctx, func() error {
			var err error
			values, err = sess.JWC.Exams(ctx, semester)
			return err
		}); err != nil {
			return nil, err
		}
		return values, s.store.ReplaceExams(ctx, sess.StudentID, semester, values)
	})
	if err != nil {
		mapJWCError(w, err, "获取考试安排失败")
		return
	}
	if err := s.syncUserReminderTasks(r.Context(), sess.StudentID, semester); err != nil {
		s.logger.Warn("考试刷新后同步提醒任务失败", "sid_prefix", maskedSID(sess.StudentID), "error", err)
	}
	message := fmt.Sprintf("成功获取 %d 场考试", len(values))
	if len(values) == 0 {
		message = "成功获取 0 场考试（本学期暂无考试安排）"
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "message": message, "count": len(values)})
}

func (s *Server) refreshAll(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	if isGraduate(sess) {
		courses, err := s.graduateCourses(r.Context(), sess, true)
		if err != nil {
			mapJWCError(w, err, "获取研究生课表失败")
			return
		}
		exams, err := s.graduateTable(r.Context(), sess, "exams", true)
		if err != nil {
			mapJWCError(w, err, "获取研究生考试失败")
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"success": true, "semester": courses["semester"], "schedule": refreshPart(courses["count"]), "exams": refreshPart(exams["count"])})
		return
	}
	semester := s.semesterFor(r, sess)
	result, err := doOnceValue(r.Context(), s, "all:"+sess.StudentID+":"+semester, func(ctx context.Context) (refreshAllResult, error) {
		unlock := sess.Lock()
		defer unlock()
		var result refreshAllResult
		err := s.withJWC(ctx, func() error {
			result = runRefreshAll(
				func() ([]store.Course, error) { return sess.JWC.Courses(ctx, semester) },
				func(values []store.Course) error {
					return s.store.ReplaceCourses(ctx, sess.StudentID, semester, values)
				},
				func() ([]store.Exam, error) { return sess.JWC.Exams(ctx, semester) },
				func(values []store.Exam) error { return s.store.ReplaceExams(ctx, sess.StudentID, semester, values) },
			)
			return nil
		})
		if err == nil {
			err = s.store.SetUserSetting(ctx, sess.StudentID, "semester", semester)
		}
		return result, err
	})
	if err != nil {
		mapJWCError(w, err, "刷新课表和考试失败")
		return
	}
	s.cacheDeletePrefix(sess.StudentID + ":")
	if result.schedule["ok"] == true {
		if err := s.syncUserReminderTasks(r.Context(), sess.StudentID, semester); err != nil {
			s.logger.Warn("全量刷新后同步提醒任务失败", "sid_prefix", maskedSID(sess.StudentID), "error", err)
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"success": true, "semester": semester,
		"schedule": result.schedule,
		"exams":    result.exams,
		"message":  fmt.Sprintf("课表: %d门, 考试: %d场", refreshCount(result.schedule), refreshCount(result.exams)),
	})
}

func runRefreshAll(
	fetchCourses func() ([]store.Course, error),
	saveCourses func([]store.Course) error,
	fetchExams func() ([]store.Exam, error),
	saveExams func([]store.Exam) error,
) refreshAllResult {
	result := refreshAllResult{}
	courses, err := fetchCourses()
	if err == nil {
		err = saveCourses(courses)
	}
	if err == nil {
		result.schedule = refreshPart(len(courses))
	} else {
		result.schedule = refreshFailedPart(err, "获取课表失败")
		if refreshMustAbort(err) {
			result.exams = refreshFailedPart(jwc.ErrSessionExpired, "获取考试失败")
			return result
		}
	}

	exams, err := fetchExams()
	if err == nil {
		err = saveExams(exams)
	}
	if err == nil {
		result.exams = refreshPart(len(exams))
	} else {
		result.exams = refreshFailedPart(err, "获取考试失败")
	}
	return result
}

func refreshFailedPart(err error, fallback string) map[string]any {
	status, message := http.StatusBadGateway, fallback
	switch {
	case errors.Is(err, jwc.ErrSessionExpired):
		status, message = http.StatusUnauthorized, "会话已过期，请重新登录"
	case errors.Is(err, jwc.ErrCaptchaRequired):
		status, message = http.StatusUnauthorized, "智慧理工要求验证码，请改用二维码登录"
	}
	return map[string]any{"ok": false, "success": false, "count": 0, "error": message, "status_code": status}
}

func refreshMustAbort(err error) bool {
	return errors.Is(err, jwc.ErrSessionExpired) || errors.Is(err, jwc.ErrCaptchaRequired)
}

func refreshCount(part map[string]any) int {
	value, _ := part["count"].(int)
	return value
}

func refreshPart(count any) map[string]any {
	return map[string]any{"ok": true, "success": true, "count": count}
}

func (s *Server) grades(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	if isGraduate(sess) {
		payload, err := s.graduateTable(r.Context(), sess, "grades", false)
		if err != nil {
			mapJWCError(w, err, "获取研究生成绩失败")
			return
		}
		writeJSON(w, http.StatusOK, payload)
		return
	}
	semester := strings.TrimSpace(r.URL.Query().Get("semester"))
	viewAll := semester == "" || semester == "__all__"
	year, term := "", ""
	if !viewAll {
		parts := strings.Split(semester, "-")
		if len(parts) >= 3 {
			year, term = parts[0]+"-"+parts[1], parts[2]
		}
	}
	values, err := s.store.Grades(r.Context(), sess.StudentID, year, term)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取成绩失败")
		return
	}
	available, err := s.store.GradeSemesters(r.Context(), sess.StudentID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取成绩学期失败")
		return
	}
	if values == nil {
		values = []store.Grade{}
	}
	if available == nil {
		available = []string{}
	}
	display := semester
	if viewAll {
		display = "__all__"
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "semester": display, "count": len(values), "grades": values, "available_semesters": available})
}

func (s *Server) refreshGrades(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	if isGraduate(sess) {
		payload, err := s.graduateTable(r.Context(), sess, "grades", true)
		if err != nil {
			mapJWCError(w, err, "获取研究生成绩失败")
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"success": true, "count": payload["count"], "message": fmt.Sprintf("成功获取 %v 条成绩记录", payload["count"])})
		return
	}
	values, err := doOnceValue(r.Context(), s, "grades:"+sess.StudentID, func(ctx context.Context) ([]store.Grade, error) {
		unlock := sess.Lock()
		defer unlock()
		var values []store.Grade
		if err := s.withJWC(ctx, func() error {
			var err error
			values, err = sess.JWC.Grades(ctx, "")
			return err
		}); err != nil {
			return nil, err
		}
		return values, s.store.ReplaceGrades(ctx, sess.StudentID, values)
	})
	if err != nil {
		mapJWCError(w, err, "获取成绩失败")
		return
	}
	terms := map[string]bool{}
	for _, value := range values {
		terms[value.AcademicYear+"-"+value.Semester] = true
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "message": fmt.Sprintf("成功获取 %d 条成绩记录（%d 个学期）", len(values), len(terms)), "count": len(values)})
}

func (s *Server) cetScores(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	values, err := s.store.CETScores(r.Context(), sess.StudentID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取四六级成绩失败")
		return
	}
	if values == nil {
		values = []store.CETScore{}
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "scores": values})
}

func (s *Server) refreshCET(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	values, err := doOnceValue(r.Context(), s, "cet:"+sess.StudentID, func(ctx context.Context) ([]store.CETScore, error) {
		unlock := sess.Lock()
		defer unlock()
		var values []store.CETScore
		if err := s.withJWC(ctx, func() error {
			var err error
			values, err = sess.JWC.CETScores(ctx)
			return err
		}); err != nil {
			return nil, err
		}
		if len(values) == 0 {
			return nil, errNoCETScores
		}
		return values, s.store.ReplaceCETScores(ctx, sess.StudentID, values)
	})
	if err != nil {
		if errors.Is(err, errNoCETScores) {
			writeError(w, http.StatusNotFound, errNoCETScores.Error())
			return
		}
		mapJWCError(w, err, "获取四六级成绩失败")
		return
	}
	if values == nil {
		values = []store.CETScore{}
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "message": fmt.Sprintf("成功获取 %d 条四六级成绩", len(values)), "scores": values})
}

func (s *Server) evaluations(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	values, err := s.store.Evaluations(r.Context(), sess.StudentID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取评价数据失败")
		return
	}
	if values == nil {
		values = []store.Evaluation{}
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "count": len(values), "evaluations": values})
}

func (s *Server) refreshEvaluations(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	values, err := doOnceValue(r.Context(), s, "evaluations:"+sess.StudentID, func(ctx context.Context) ([]store.Evaluation, error) {
		unlock := sess.Lock()
		defer unlock()
		var values []store.Evaluation
		if err := s.withJWC(ctx, func() error {
			var err error
			values, err = sess.JWC.Evaluations(ctx)
			return err
		}); err != nil {
			return nil, err
		}
		return values, s.store.ReplaceEvaluations(ctx, sess.StudentID, values)
	})
	if err != nil {
		mapJWCError(w, err, "获取评价数据失败")
		return
	}
	undone := 0
	for _, value := range values {
		if !value.IsDone {
			undone++
		}
	}
	message := fmt.Sprintf("成功获取 %d 条评价", len(values))
	if undone > 0 {
		message += fmt.Sprintf("，%d 条待完成", undone)
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "message": message, "count": len(values), "undone": undone})
}

func (s *Server) startPrefetch(sess *session.Session, semester, mode string) {
	if sess == nil || sess.JWC == nil {
		return
	}
	if mode == "if_stale" {
		raw, err := s.store.UserSetting(s.ctx, sess.StudentID, "data_cache_at")
		if err != nil {
			s.logger.Warn("读取预抓缓存标记失败", "sid_prefix", maskedSID(sess.StudentID), "error", err)
		} else if raw != "" {
			var unix int64
			_, _ = fmt.Sscan(raw, &unix)
			if unix > 0 && time.Since(time.Unix(unix, 0)) < s.cfg.DataCacheTTL {
				now := time.Now().Unix()
				sess.SetRefreshState(map[string]any{"state": "done", "started_at": now, "fetched_at": now, "updated_at": now, "skipped": true, "ok": []string{}, "failed": []string{}})
				return
			}
		}
	}
	s.wg.Add(1)
	go func() {
		defer s.wg.Done()
		timer := time.NewTimer(3 * time.Second)
		defer timer.Stop()
		select {
		case <-timer.C:
		case <-s.ctx.Done():
			return
		case <-sess.Context().Done():
			return
		}
		startedAt := time.Now().Unix()
		sess.SetRefreshState(map[string]any{"state": "running", "started_at": startedAt, "updated_at": startedAt})
		if isGraduate(sess) {
			ok, failed := s.prefetchGraduate(sess)
			if s.ctx.Err() != nil || sess.Context().Err() != nil {
				return
			}
			state := "done"
			if len(failed) > 0 {
				state = "partial"
			}
			if contains(failed, "session_expired") {
				state = "failed"
			}
			now := time.Now().Unix()
			sess.SetRefreshState(map[string]any{"state": state, "started_at": startedAt, "fetched_at": now, "updated_at": now, "ok": ok, "failed": failed})
			return
		}
		ok, failed := s.prefetchUndergraduate(sess, semester)
		if s.ctx.Err() != nil || sess.Context().Err() != nil {
			return
		}
		state := "done"
		if len(failed) > 0 {
			state = "partial"
		}
		if contains(failed, "session_expired") {
			state = "failed"
		}
		if state == "done" {
			if err := s.store.SetUserSetting(s.ctx, sess.StudentID, "data_cache_at", fmt.Sprint(time.Now().Unix())); err != nil {
				s.logger.Error("保存预抓缓存标记失败", "sid_prefix", maskedSID(sess.StudentID), "error", err)
				state = "partial"
				failed = append(failed, "cache_marker")
			}
		}
		now := time.Now().Unix()
		sess.SetRefreshState(map[string]any{"state": state, "started_at": startedAt, "fetched_at": now, "updated_at": now, "ok": ok, "failed": failed})
	}()
}

func (s *Server) prefetchGraduate(sess *session.Session) (ok, failed []string) {
	ctx, cancel := contextWithSessionTimeout(s.ctx, sess, 2*time.Minute)
	defer cancel()
	steps := []prefetchStep{
		{"courses", func() error { _, err := s.graduateCourses(ctx, sess, true); return err }},
		{"grades", func() error { _, err := s.graduateTable(ctx, sess, "grades", true); return err }},
		{"exams", func() error { _, err := s.graduateTable(ctx, sess, "exams", true); return err }},
	}
	return runPrefetchSteps(steps)
}

func (s *Server) prefetchUndergraduate(sess *session.Session, semester string) (ok, failed []string) {
	ctx, cancel := contextWithSessionTimeout(s.ctx, sess, 4*time.Minute)
	defer cancel()
	steps := []prefetchStep{
		{"calendar", func() error { _, err := s.fetchCalendar(ctx, sess, semester); return err }},
		{"courses", func() error {
			values, err := sess.JWC.Courses(ctx, semester)
			if err == nil {
				err = s.store.ReplaceCourses(ctx, sess.StudentID, semester, values)
			}
			return err
		}},
		{"exams", func() error {
			values, err := sess.JWC.Exams(ctx, semester)
			if err == nil {
				err = s.store.ReplaceExams(ctx, sess.StudentID, semester, values)
			}
			return err
		}},
		{"grades", func() error {
			values, err := sess.JWC.Grades(ctx, "")
			if err == nil {
				err = s.store.ReplaceGrades(ctx, sess.StudentID, values)
			}
			return err
		}},
		{"cet", func() error {
			values, err := sess.JWC.CETScores(ctx)
			if err == nil {
				err = s.store.ReplaceCETScores(ctx, sess.StudentID, values)
			}
			return err
		}},
		{"evaluations", func() error {
			values, err := sess.JWC.Evaluations(ctx)
			if err == nil {
				err = s.store.ReplaceEvaluations(ctx, sess.StudentID, values)
			}
			return err
		}},
		{"programme", func() error { _, err := s.fetchProgramme(ctx, sess); return err }},
		{"profile", func() error { _, err := s.fetchProfile(ctx, sess); return err }},
	}
	unlock := sess.Lock()
	defer unlock()
	wrapped := make([]prefetchStep, 0, len(steps))
	for _, step := range steps {
		step := step
		wrapped = append(wrapped, prefetchStep{name: step.name, fn: func() error { return s.withJWC(ctx, step.fn) }})
	}
	return runPrefetchSteps(wrapped)
}

func runPrefetchSteps(steps []prefetchStep) (ok, failed []string) {
	for _, step := range steps {
		err := step.fn()
		if err != nil {
			if errors.Is(err, jwc.ErrSessionExpired) {
				return ok, append(failed, "session_expired")
			}
			failed = append(failed, step.name)
			if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
				return ok, failed
			}
			continue
		}
		ok = append(ok, step.name)
	}
	return
}

func contains(values []string, wanted string) bool {
	for _, value := range values {
		if value == wanted {
			return true
		}
	}
	return false
}

func contextWithSessionTimeout(parent context.Context, sess *session.Session, timeout time.Duration) (context.Context, context.CancelFunc) {
	base, cancelBase := contextWithSession(parent, sess)
	ctx, cancel := context.WithTimeout(base, timeout)
	return ctx, func() {
		cancel()
		cancelBase()
	}
}

func contextWithSession(parent context.Context, sess *session.Session) (context.Context, context.CancelFunc) {
	ctx, cancel := context.WithCancel(parent)
	if sess == nil {
		return ctx, cancel
	}
	stop := context.AfterFunc(sess.Context(), cancel)
	return ctx, func() {
		stop()
		cancel()
	}
}
