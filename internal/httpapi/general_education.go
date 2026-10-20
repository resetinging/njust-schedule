package httpapi

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/resetinging/njust-schedule/internal/store"
)

const generalEducationVersionKey = "general_education_catalog_at:"

func (s *Server) generalEducationStatus(ctx context.Context, semester string) map[string]any {
	count, countErr := s.store.GeneralEducationCount(ctx, semester)
	raw, settingErr := s.store.Setting(ctx, generalEducationVersionKey+semester)
	updated, _ := strconv.ParseInt(strings.TrimSpace(raw), 10, 64)
	err := errors.Join(countErr, settingErr)
	s.generalEduMu.Lock()
	state := s.generalEduSync
	s.generalEduMu.Unlock()
	needsRefresh := err != nil || count <= 0 || updated <= 0 || time.Since(time.Unix(updated, 0)) >= 24*time.Hour
	return map[string]any{
		"semester": semester, "course_count": count, "updated_at": updated,
		"empty": count <= 0, "needs_refresh": needsRefresh, "db_error": errorText(err),
		"running": state.Running, "running_semester": state.Semester,
		"last_started_at": state.StartedAt, "last_finished_at": state.FinishedAt,
		"last_success": state.Success, "last_count": state.Count, "last_error": state.Error,
	}
}

func (s *Server) generalEducationCourses(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	semester := s.semesterFor(r, sess)
	q := r.URL.Query()
	keyword := strings.TrimSpace(q.Get("q"))
	if !validText(keyword, 100) {
		writeError(w, http.StatusBadRequest, "搜索关键词格式无效或过长")
		return
	}
	page := parseInt(q.Get("page"), 1, 1, 100_000)
	limit := parseInt(q.Get("limit"), 20, 1, 100)
	values, total, err := s.store.GeneralEducationCourses(r.Context(), semester, keyword, limit, (page-1)*limit)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取通识选修课目录失败")
		return
	}
	status := s.generalEducationStatus(r.Context(), semester)
	writeJSON(w, http.StatusOK, map[string]any{
		"success": true, "semester": semester, "courses": values, "count": len(values),
		"total": total, "page": page, "limit": limit, "has_more": page*limit < total,
		"updated_at": status["updated_at"], "needs_refresh": status["needs_refresh"],
	})
}

func (s *Server) generalEducationSyllabus(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	if isGraduate(sess) {
		writeError(w, http.StatusBadRequest, "研究生账号不支持通识选修课大纲")
		return
	}
	semester := s.semesterFor(r, sess)
	courseCode := strings.TrimSpace(r.URL.Query().Get("course_code"))
	if courseCode == "" || len(courseCode) > 64 || !validText(courseCode, 64) {
		writeError(w, http.StatusBadRequest, "课程编号无效")
		return
	}
	course, err := s.store.GeneralEducationCourseByCode(r.Context(), semester, courseCode)
	if errors.Is(err, sql.ErrNoRows) {
		writeError(w, http.StatusNotFound, "课程不存在")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取课程信息失败")
		return
	}
	if !course.HasSyllabus || course.SyllabusID == "" {
		writeError(w, http.StatusNotFound, "该课程未提供课程大纲")
		return
	}
	cached := decodeMap(course.DetailJSON)
	if course.DetailFetchedAt > 0 && time.Since(time.Unix(course.DetailFetchedAt, 0)) < s.cfg.DataCacheTTL && len(cached) > 0 {
		writeJSON(w, http.StatusOK, map[string]any{
			"success": true, "cached": true, "course": course, "syllabus": cached,
		})
		return
	}
	unlock := sess.Lock()
	defer unlock()
	var detail store.GeneralEducationSyllabus
	err = s.withJWC(r.Context(), func() error {
		var fetchErr error
		detail, fetchErr = sess.JWC.GeneralEducationSyllabus(r.Context(), course.SyllabusID)
		return fetchErr
	})
	if err != nil {
		if len(cached) > 0 {
			writeJSON(w, http.StatusOK, map[string]any{
				"success": true, "cached": true, "stale": true, "course": course, "syllabus": cached,
			})
			return
		}
		mapJWCError(w, err, "课程大纲获取失败")
		return
	}
	raw, err := json.Marshal(detail)
	if err != nil || len(raw) > 2<<20 {
		writeError(w, http.StatusBadGateway, "课程大纲内容过大或格式异常")
		return
	}
	if err = s.store.SaveGeneralEducationDetail(r.Context(), semester, courseCode, string(raw), time.Unix(detail.FetchedAt, 0)); err != nil {
		s.logger.Warn("保存通识选修课大纲失败", "course_code", courseCode, "error", err)
	}
	payload := map[string]any{"success": true, "cached": false, "course": course, "syllabus": detail}
	writeJSON(w, http.StatusOK, payload)
}

func (s *Server) adminGeneralEducationStatus(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	payload := s.generalEducationStatus(r.Context(), currentSemester())
	payload["success"] = true
	writeJSON(w, http.StatusOK, payload)
}

func (s *Server) adminGeneralEducationSync(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	semester := currentSemester()
	started := s.startGeneralEducationSync(semester)
	status := s.generalEducationStatus(r.Context(), semester)
	message := "已有通识选修课大纲同步任务正在运行"
	code := http.StatusOK
	if started {
		message = "已开始后台刷新，完成后通识选修课目录会自动更新"
		code = http.StatusAccepted
	}
	writeJSON(w, code, map[string]any{"success": true, "started": started, "message": message, "status": status})
}

func (s *Server) startGeneralEducationSync(semester string) bool {
	s.generalEduMu.Lock()
	if s.generalEduSync.Running {
		s.generalEduMu.Unlock()
		return false
	}
	s.generalEduSync = auditSyncState{Running: true, Semester: semester, StartedAt: time.Now().Unix()}
	s.generalEduMu.Unlock()
	s.wg.Add(1)
	go func() {
		defer s.wg.Done()
		ctx, cancel := context.WithTimeout(s.ctx, time.Hour)
		defer cancel()
		count, pages, err := s.syncGeneralEducationCatalog(ctx, semester)
		success := err == nil
		if err != nil {
			s.logger.Warn("通识选修课大纲同步失败", "semester", semester, "pages", pages, "error", err)
		} else {
			s.logger.Info("通识选修课大纲同步完成", "semester", semester, "pages", pages, "count", count)
		}
		s.generalEduMu.Lock()
		s.generalEduSync.Running = false
		s.generalEduSync.FinishedAt = time.Now().Unix()
		s.generalEduSync.Success = &success
		s.generalEduSync.Count = count
		s.generalEduSync.Error = errorText(err)
		s.generalEduMu.Unlock()
	}()
	return true
}

func (s *Server) syncGeneralEducationCatalog(ctx context.Context, semester string) (int, int, error) {
	var lastErr error
	candidates := s.randomPersistentClients(ctx)
	defer closeSharedJWCCandidates(candidates)
	for _, candidate := range candidates {
		candidateCtx, cancel := contextWithSession(ctx, candidate.sess)
		unlock := func() {}
		if candidate.sess != nil {
			unlock = candidate.sess.Lock()
		}
		var catalog store.GeneralEducationCatalog
		err := s.withJWC(candidateCtx, func() error {
			if err := candidate.client.Resume(candidateCtx, candidate.sid); err != nil {
				return err
			}
			var fetchErr error
			catalog, fetchErr = candidate.client.GeneralEducationCatalog(candidateCtx, semester)
			return fetchErr
		})
		unlock()
		cancel()
		if err == nil && len(catalog.Courses) > 0 {
			if err = s.store.ReplaceGeneralEducationCourses(ctx, semester, catalog.Courses); err == nil {
				if err = s.store.SetSetting(ctx, generalEducationVersionKey+semester, strconv.FormatInt(time.Now().Unix(), 10)); err == nil {
					return len(catalog.Courses), catalog.Pages, nil
				}
			}
		}
		if err != nil {
			lastErr = err
		}
	}

	_, client, err := s.serviceAccountClient(ctx)
	if err == nil {
		defer client.CloseIdleConnections()
		var catalog store.GeneralEducationCatalog
		err = s.withJWC(ctx, func() error {
			var fetchErr error
			catalog, fetchErr = client.GeneralEducationCatalog(ctx, semester)
			return fetchErr
		})
		if err == nil && len(catalog.Courses) > 0 {
			if err = s.store.ReplaceGeneralEducationCourses(ctx, semester, catalog.Courses); err == nil {
				if err = s.store.SetSetting(ctx, generalEducationVersionKey+semester, strconv.FormatInt(time.Now().Unix(), 10)); err == nil {
					return len(catalog.Courses), catalog.Pages, nil
				}
			}
		}
	}
	if err != nil {
		lastErr = err
	}
	if lastErr == nil {
		lastErr = errors.New("没有可用的本科教务 Cookie")
	}
	return 0, 0, lastErr
}
