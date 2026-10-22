package httpapi

import (
	"context"
	"fmt"
	"net/http"
	"strings"

	"github.com/resetinging/njust-schedule/internal/jwc"
	"github.com/resetinging/njust-schedule/internal/session"
	"github.com/resetinging/njust-schedule/internal/store"
)

func isGraduate(sess *session.Session) bool {
	return sess != nil && (strings.EqualFold(sess.AccountType, "graduate") || strings.HasPrefix(sess.StudentID, "1"))
}

func (s *Server) graduateCourses(ctx context.Context, sess *session.Session, force bool) (map[string]any, error) {
	key := sess.StudentID + ":yjs:courses"
	if !force {
		if cached, ok := s.cacheGet(key); ok {
			if value, valid := cached.(map[string]any); valid {
				return value, nil
			}
		}
	}
	return doOnceValue(ctx, s, "graduate-courses:"+sess.StudentID, func(callCtx context.Context) (map[string]any, error) {
		unlock := sess.Lock()
		defer unlock()
		var values []store.Course
		var sourceSemesters []string
		err := s.withJWC(callCtx, func() error {
			var err error
			values, sourceSemesters, err = sess.JWC.GraduateCourses(callCtx)
			return err
		})
		if err != nil {
			return nil, err
		}
		semesters := normalizeSemesterList(sourceSemesters)
		semester := ""
		if len(semesters) > 0 {
			semester = semesters[0]
		}
		if semester == "" {
			semester = currentSemester()
		}
		if err = s.store.ReplaceCourses(callCtx, sess.StudentID, semester, values); err != nil {
			return nil, err
		}
		if err = s.store.SetUserSetting(callCtx, sess.StudentID, "semester", semester); err != nil {
			return nil, err
		}
		payload := map[string]any{"success": true, "account_type": "graduate", "semester": semester, "semesters": semesters, "count": len(values), "courses": nonNilCourses(values)}
		s.cacheSet(key, payload, s.cfg.DataCacheTTL)
		return payload, nil
	})
}

func (s *Server) graduateTable(ctx context.Context, sess *session.Session, kind string, force bool) (map[string]any, error) {
	key := sess.StudentID + ":yjs:" + kind
	if !force {
		if cached, ok := s.cacheGet(key); ok {
			if value, valid := cached.(map[string]any); valid {
				return value, nil
			}
		}
	}
	return doOnceValue(ctx, s, "graduate-"+kind+":"+sess.StudentID, func(callCtx context.Context) (map[string]any, error) {
		unlock := sess.Lock()
		defer unlock()
		var table jwc.GraduateTable
		err := s.withJWC(callCtx, func() error {
			var err error
			if kind == "grades" {
				table, err = sess.JWC.GraduateGrades(callCtx)
			} else {
				table, err = sess.JWC.GraduateExams(callCtx)
			}
			return err
		})
		if err != nil {
			return nil, err
		}
		payload := map[string]any{"success": true, "account_type": "graduate", "count": len(table.Rows), "rows": table.Rows, "semesters": table.Semesters}
		if kind == "grades" {
			payload["stats"] = table.Stats
		}
		if len(table.Semesters) > 0 {
			payload["semester"] = table.Semesters[0]
		}
		s.cacheSet(key, payload, s.cfg.DataCacheTTL)
		return payload, nil
	})
}

func (s *Server) yjsCourses(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	if !isGraduate(sess) {
		writeError(w, http.StatusBadRequest, "该接口仅研究生账号可用")
		return
	}
	payload, err := s.graduateCourses(r.Context(), sess, false)
	if err != nil {
		mapJWCError(w, err, "获取研究生课表失败")
		return
	}
	writeJSON(w, http.StatusOK, payload)
}

func (s *Server) yjsExams(w http.ResponseWriter, r *http.Request) {
	s.yjsTable(w, r, "exams")
}

func (s *Server) yjsGrades(w http.ResponseWriter, r *http.Request) {
	s.yjsTable(w, r, "grades")
}

func (s *Server) yjsTable(w http.ResponseWriter, r *http.Request, kind string) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	if !isGraduate(sess) {
		writeError(w, http.StatusBadRequest, "该接口仅研究生账号可用")
		return
	}
	payload, err := s.graduateTable(r.Context(), sess, kind, false)
	if err != nil {
		label := map[string]string{"grades": "成绩", "exams": "考试"}[kind]
		mapJWCError(w, err, fmt.Sprintf("获取研究生%s失败", label))
		return
	}
	writeJSON(w, http.StatusOK, payload)
}
