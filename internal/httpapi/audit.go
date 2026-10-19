package httpapi

import (
	"encoding/json"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/naughtygopher/webgo/v7"
	"github.com/resetinging/njust-schedule/internal/store"
)

const auditOptionsChunkSize = 2000

func (s *Server) auditVersion(r *http.Request, semester string) (int64, error) {
	raw, err := s.store.Setting(r.Context(), "audit_catalog_at:"+semester)
	if err != nil {
		return 0, err
	}
	value, _ := strconv.ParseInt(strings.TrimSpace(raw), 10, 64)
	return value, nil
}

func queryFlag(r *http.Request, name string) bool {
	value := strings.ToLower(strings.TrimSpace(r.URL.Query().Get(name)))
	return value == "1" || value == "true" || value == "yes"
}

func (s *Server) auditCourses(w http.ResponseWriter, r *http.Request) {
	if _, ok := s.requireSession(w, r); !ok {
		return
	}
	qv := r.URL.Query()
	semester := strings.TrimSpace(qv.Get("semester"))
	if semester == "" {
		semester = currentSemester()
	}
	name := strings.TrimSpace(qv.Get("name"))
	teacher := strings.TrimSpace(qv.Get("teacher"))
	classroom := strings.TrimSpace(qv.Get("classroom"))
	if classroom == "" {
		classroom = strings.TrimSpace(qv.Get("location"))
	}
	if !validText(name, 200) || !validText(teacher, 200) || !validText(classroom, 200) {
		writeError(w, http.StatusBadRequest, "查询条件格式无效或过长")
		return
	}
	names, namesErr := parseStringList(qv.Get("names"), 50, 200)
	teachers, teachersErr := parseStringList(qv.Get("teachers"), 50, 200)
	classrooms, classroomsErr := parseStringList(qv.Get("classrooms"), 50, 200)
	if namesErr != nil || teachersErr != nil || classroomsErr != nil {
		writeError(w, http.StatusBadRequest, "查询条件格式无效或过长")
		return
	}
	if len(names) == 0 && name != "" {
		names = []string{name}
	}
	if len(teachers) == 0 && teacher != "" {
		teachers = []string{teacher}
	}
	if len(classrooms) == 0 && classroom != "" {
		classrooms = []string{classroom}
	}
	page := parseInt(qv.Get("page"), 1, 1, 1_000_000)
	limit := parseInt(qv.Get("limit"), 20, 1, 50)
	start := parseInt(qv.Get("jc1"), 0, 0, 13)
	end := parseInt(qv.Get("jc2"), 0, 0, 13)
	if start > 0 && end > 0 && start > end {
		start, end = end, start
	}
	keyword := strings.TrimSpace(qv.Get("q"))
	if !validText(keyword, 100) {
		writeError(w, http.StatusBadRequest, "搜索关键词格式无效或过长")
		return
	}
	query := store.AuditQuery{
		Semester: semester, Names: names, Teachers: teachers, Classrooms: classrooms,
		Keyword: keyword, Weekday: parseInt(qv.Get("weekday"), 0, 0, 7),
		Start: start, End: end, Limit: limit, Offset: (page - 1) * limit,
		NameExact: queryFlag(r, "name_exact"), TeacherExact: queryFlag(r, "teacher_exact"), ClassroomExact: queryFlag(r, "classroom_exact"),
	}
	values, total, err := s.store.AuditGroups(r.Context(), query)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "查询蹭课课程失败")
		return
	}
	version, err := s.auditVersion(r, semester)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取蹭课目录版本失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"success": true, "semester": semester, "courses": values, "count": len(values),
		"total": total, "page": page, "limit": limit, "has_more": page*limit < total,
		"updated_at": version,
		"fields":     []string{"name", "class_info", "teacher", "classroom", "schedules", "schedule_count"},
	})
}

func optionValues(options map[string]any, field string) []string {
	key := field
	if field == "name" {
		key = "names"
	} else if field == "teacher" {
		key = "teachers"
	} else if field == "classroom" {
		key = "classrooms"
	}
	values, _ := options[key].([]string)
	return values
}

func (s *Server) auditOptions(w http.ResponseWriter, r *http.Request) {
	if _, ok := s.requireSession(w, r); !ok {
		return
	}
	q := r.URL.Query()
	semester := strings.TrimSpace(q.Get("semester"))
	if semester == "" {
		semester = currentSemester()
	}
	field := strings.TrimSpace(q.Get("field"))
	if field == "" {
		field = "name"
	}
	if field == "location" {
		field = "classroom"
	}
	version, err := s.auditVersion(r, semester)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取蹭课目录版本失败")
		return
	}
	if field == "version" {
		count, err := s.store.AuditCount(r.Context(), semester)
		if err != nil {
			writeError(w, http.StatusInternalServerError, "读取蹭课目录失败")
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"success": true, "semester": semester, "field": field, "catalog_version": version, "count": count})
		return
	}
	options, err := s.store.AuditOptions(r.Context(), semester)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取蹭课候选项失败")
		return
	}
	if field == "all" {
		relations, _ := options["relations"].([][]any)
		parts := max(1, (len(relations)+auditOptionsChunkSize-1)/auditOptionsChunkSize)
		partRaw, hasPart := q["part"]
		part := 0
		if hasPart {
			part = parseInt(strings.Join(partRaw, ""), -1, -1, parts)
			if part < 0 || part >= parts {
				writeError(w, http.StatusBadRequest, "分片编号超出范围")
				return
			}
		} else {
			parts = 1
		}
		start := 0
		end := len(relations)
		if hasPart {
			start = part * auditOptionsChunkSize
			end = min(len(relations), start+auditOptionsChunkSize)
		}
		payload := map[string]any{
			"success": true, "semester": semester, "field": field, "catalog_version": version,
			"part": part, "parts": parts, "relations_total": len(relations), "relations_offset": start,
			"relations": relations[start:end],
		}
		if part == 0 {
			payload["names"] = optionValues(options, "name")
			payload["teachers"] = optionValues(options, "teacher")
			payload["classrooms"] = optionValues(options, "classroom")
		}
		writeJSON(w, http.StatusOK, payload)
		return
	}
	if field != "name" && field != "teacher" && field != "classroom" {
		writeError(w, http.StatusBadRequest, "不支持的候选字段")
		return
	}
	keyword := strings.ToLower(strings.TrimSpace(q.Get("q")))
	if !validText(keyword, 100) {
		writeError(w, http.StatusBadRequest, "搜索关键词格式无效或过长")
		return
	}
	limit := parseInt(q.Get("limit"), 20, 1, 50)
	values := optionValues(options, field)
	filtered := make([]string, 0, min(limit, len(values)))
	for _, value := range values {
		if keyword == "" || strings.Contains(strings.ToLower(value), keyword) {
			filtered = append(filtered, value)
			if len(filtered) >= limit {
				break
			}
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "semester": semester, "field": field, "options": filtered, "count": len(filtered)})
}

func (s *Server) auditFavorites(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	semester := strings.TrimSpace(r.URL.Query().Get("semester"))
	if semester == "" {
		semester = currentSemester()
	}
	values, err := s.store.AuditFavorites(r.Context(), sess.StudentID, semester)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取收藏失败")
		return
	}
	if values == nil {
		values = []store.AuditFavorite{}
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "semester": semester, "favorites": values})
}

func (s *Server) saveAuditFavorite(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	var body struct {
		Semester  string                `json:"semester"`
		Course    *store.AuditGroup     `json:"course"`
		Name      string                `json:"name"`
		ClassInfo string                `json:"class_info"`
		Teacher   string                `json:"teacher"`
		Classroom string                `json:"classroom"`
		Schedules []store.AuditSchedule `json:"schedules"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	semester := strings.TrimSpace(body.Semester)
	if semester == "" {
		semester = currentSemester()
	} else if !validSemester(semester, false) {
		writeError(w, http.StatusBadRequest, "学期格式无效")
		return
	}
	group := store.AuditGroup{Name: body.Name, ClassInfo: body.ClassInfo, Teacher: body.Teacher, Classroom: body.Classroom, Schedules: body.Schedules}
	if body.Course != nil {
		group = *body.Course
	}
	group.Name = strings.TrimSpace(group.Name)
	if group.Name == "" || len(group.Schedules) == 0 {
		writeError(w, http.StatusBadRequest, "课程名称和上课安排不能为空")
		return
	}
	if err := normalizeAuditFavorite(&group); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	group.ScheduleCount = len(group.Schedules)
	value, err := s.store.SaveAuditFavorite(r.Context(), sess.StudentID, semester, group)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "保存收藏失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "semester": semester, "favorite": value})
}

func normalizeAuditFavorite(group *store.AuditGroup) error {
	group.Name = strings.TrimSpace(group.Name)
	group.ClassInfo = strings.TrimSpace(group.ClassInfo)
	group.Teacher = strings.TrimSpace(group.Teacher)
	group.Classroom = strings.TrimSpace(group.Classroom)
	if !validText(group.Name, 200) {
		return &httpError{Status: http.StatusBadRequest, Message: "课程名称格式无效或过长"}
	}
	if !validText(group.ClassInfo, 12_000) || len(group.ClassInfo) > 48_000 {
		return &httpError{Status: http.StatusBadRequest, Message: "班级信息格式无效或过长"}
	}
	if !validText(group.Teacher, 200) || !validText(group.Classroom, 200) {
		return &httpError{Status: http.StatusBadRequest, Message: "教师或教室信息格式无效或过长"}
	}
	if len(group.Schedules) > 64 {
		return &httpError{Status: http.StatusBadRequest, Message: "上课安排数量过多"}
	}
	for i := range group.Schedules {
		item := &group.Schedules[i]
		item.Weeks = strings.TrimSpace(item.Weeks)
		item.Teacher = strings.TrimSpace(item.Teacher)
		item.Classroom = strings.TrimSpace(item.Classroom)
		if item.Day < 1 || item.Day > 7 || item.Start < 1 || item.Start > 13 || item.End < item.Start || item.End > 13 {
			return &httpError{Status: http.StatusBadRequest, Message: "上课安排时间无效"}
		}
		if !validText(item.Weeks, 100) || !validText(item.Teacher, 200) || !validText(item.Classroom, 200) {
			return &httpError{Status: http.StatusBadRequest, Message: "上课安排内容格式无效或过长"}
		}
	}
	raw, err := json.Marshal(group.Schedules)
	if err != nil || len(raw) > 60_000 || !utf8.Valid(raw) {
		return &httpError{Status: http.StatusBadRequest, Message: "上课安排数据过大"}
	}
	return nil
}

func (s *Server) deleteAuditFavorite(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	id, err := strconv.ParseInt(webgo.Context(r).Params()["favoriteID"], 10, 64)
	if err != nil || id < 1 {
		writeError(w, http.StatusBadRequest, "收藏编号无效")
		return
	}
	deleted, err := s.store.DeleteAuditFavorite(r.Context(), sess.StudentID, id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "删除收藏失败")
		return
	}
	if !deleted {
		writeError(w, http.StatusNotFound, "收藏不存在")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true})
}

func sortedStrings(values []string) []string {
	result := append([]string(nil), values...)
	sort.Strings(result)
	return result
}
