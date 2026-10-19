package httpapi

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode"

	"github.com/resetinging/njust-schedule/internal/jwc"
	"github.com/resetinging/njust-schedule/internal/store"
	"golang.org/x/text/unicode/norm"
)

const reminderPhaseDays = 28

var (
	weekRangePattern = regexp.MustCompile(`(\d{1,2})(?:\s*[-~至]\s*(\d{1,2}))?`)
	hhmmPattern      = regexp.MustCompile(`(\d{1,2}):(\d{2})`)
	semesterPattern  = regexp.MustCompile(`^(\d{4})-(\d{4})(?:-(.+))?$`)
)

func normalizeCourseName(value string) string {
	value = strings.ToLower(norm.NFKC.String(strings.TrimSpace(value)))
	value = strings.NewReplacer("（", "(", "）", ")", "【", "[", "】", "]", "‐", "-", "‑", "-", "‒", "-", "–", "-", "—", "-", "−", "-").Replace(value)
	return strings.Map(func(r rune) rune {
		if unicode.IsSpace(r) || r == '\u3000' {
			return -1
		}
		return r
	}, value)
}

func normalizeTeacherKey(value string) string {
	value = norm.NFKC.String(strings.TrimSpace(value))
	if value == "" {
		return "unknown"
	}
	parts := strings.FieldsFunc(value, func(r rune) bool {
		return strings.ContainsRune(",，、;；/", r)
	})
	seen := map[string]bool{}
	names := make([]string, 0, len(parts))
	for _, part := range parts {
		name := strings.Map(func(r rune) rune {
			if unicode.IsSpace(r) {
				return -1
			}
			return r
		}, strings.TrimSpace(part))
		if name != "" && !seen[name] {
			seen[name] = true
			names = append(names, name)
		}
	}
	if len(names) == 0 {
		return "unknown"
	}
	sort.Strings(names)
	return strings.Join(names, ",")
}

func normalizeSemesterTerm(value string) string {
	value = strings.ToLower(norm.NFKC.String(strings.TrimSpace(value)))
	value = strings.NewReplacer("学期", "", "学季", "", " ", "", "\t", "").Replace(value)
	switch value {
	case "1", "01", "一", "第一", "上", "秋", "秋季":
		return "1"
	case "2", "02", "二", "第二", "下", "春", "春季":
		return "2"
	case "3", "03", "三", "第三", "夏", "夏季":
		return "3"
	default:
		return ""
	}
}

func semesterParts(academicYear, semester string) (string, string, bool) {
	year := norm.NFKC.String(strings.TrimSpace(academicYear))
	year = strings.NewReplacer("学年度", "", "学年", "", "—", "-", "–", "-", "−", "-", "/", "-", " ", "").Replace(year)
	match := semesterPattern.FindStringSubmatch(year)
	if len(match) == 0 {
		return "", "", false
	}
	term := strings.TrimSpace(semester)
	if term == "" {
		term = match[3]
	}
	term = normalizeSemesterTerm(term)
	if term == "" {
		return "", "", false
	}
	return match[1] + "-" + match[2], term, true
}

func gradeMatchesSemester(taskSemester string, grade store.Grade) bool {
	taskYear, taskTerm, taskOK := semesterParts(taskSemester, "")
	gradeYear, gradeTerm, gradeOK := semesterParts(grade.AcademicYear, grade.Semester)
	return taskOK && gradeOK && taskYear == gradeYear && taskTerm == gradeTerm
}

func reminderCourseKey(semester, courseName string) string {
	return normalizeSemesterKey(semester) + "|" + normalizeCourseName(courseName)
}

func normalizeSemesterKey(value string) string {
	year, term, ok := semesterParts(value, "")
	if ok {
		return year + "-" + term
	}
	return strings.TrimSpace(norm.NFKC.String(value))
}

func reminderTasksForSemester(tasks []store.ReminderTask, semester string) []store.ReminderTask {
	wanted := normalizeSemesterKey(semester)
	matched := make([]store.ReminderTask, 0, len(tasks))
	for _, task := range tasks {
		if normalizeSemesterKey(task.Semester) == wanted {
			matched = append(matched, task)
		}
	}
	return matched
}

func gradesForReminderTask(task store.ReminderTask, grades []store.Grade) []store.Grade {
	wanted := normalizeCourseName(task.CourseName)
	matches := make([]store.Grade, 0, 1)
	for _, grade := range grades {
		if normalizeCourseName(grade.CourseName) == wanted && gradeMatchesSemester(task.Semester, grade) {
			matches = append(matches, grade)
		}
	}
	return matches
}

func reminderHash(value string) string {
	sum := sha256.Sum256([]byte(value))
	return hex.EncodeToString(sum[:])
}

func parseWeekNumbers(value string) []int {
	value = strings.ReplaceAll(norm.NFKC.String(value), "周", "")
	values := map[int]bool{}
	for _, match := range weekRangePattern.FindAllStringSubmatch(value, -1) {
		start, _ := strconv.Atoi(match[1])
		end := start
		if match[2] != "" {
			end, _ = strconv.Atoi(match[2])
		}
		if start > end {
			start, end = end, start
		}
		start, end = max(1, start), min(30, end)
		for week := start; week <= end; week++ {
			values[week] = true
		}
	}
	out := make([]int, 0, len(values))
	for week := range values {
		out = append(out, week)
	}
	sort.Ints(out)
	return out
}

func mapInt(value any) int {
	switch raw := value.(type) {
	case float64:
		return int(raw)
	case json.Number:
		value, _ := raw.Int64()
		return int(value)
	default:
		value, _ := strconv.Atoi(strings.TrimSpace(fmt.Sprint(raw)))
		return value
	}
}

func mapFloat(value any) float64 {
	result, _ := strconv.ParseFloat(strings.TrimSpace(fmt.Sprint(value)), 64)
	return result
}

func calendarCourseEnd(courses []store.Course, calendar map[string]any) *time.Time {
	byWeek := map[int][]string{}
	var lastDate time.Time
	weeks, _ := calendar["weeks"].([]any)
	for _, raw := range weeks {
		item, _ := raw.(map[string]any)
		week := mapInt(item["week"])
		daysRaw, _ := item["days"].([]any)
		days := make([]string, 0, len(daysRaw))
		for _, day := range daysRaw {
			text := fmt.Sprint(day)
			days = append(days, text)
			if len(text) >= 10 {
				if parsed, err := time.ParseInLocation("2006-01-02", text[:10], beijing); err == nil && parsed.After(lastDate) {
					lastDate = parsed
				}
			}
		}
		if week > 0 && len(days) >= 7 {
			byWeek[week] = days
		}
	}
	var latest time.Time
	for _, course := range courses {
		weekNumbers := parseWeekNumbers(course.Weeks)
		if course.WeekType == 1 || course.WeekType == 2 {
			filtered := weekNumbers[:0]
			for _, week := range weekNumbers {
				if course.WeekType == 1 && week%2 == 1 || course.WeekType == 2 && week%2 == 0 {
					filtered = append(filtered, week)
				}
			}
			weekNumbers = filtered
		}
		if len(weekNumbers) == 0 && lastDate.After(latest) {
			latest = lastDate
		}
		for _, week := range weekNumbers {
			days := byWeek[week]
			if course.Day < 1 || course.Day > len(days) || len(days[course.Day-1]) < 10 {
				continue
			}
			parsed, err := time.ParseInLocation("2006-01-02", days[course.Day-1][:10], beijing)
			if err == nil && parsed.After(latest) {
				latest = parsed
			}
		}
	}
	if latest.IsZero() {
		return nil
	}
	value := time.Date(latest.Year(), latest.Month(), latest.Day(), 23, 59, 0, 0, beijing)
	return &value
}

func gradeNextCheck(now, started time.Time) *time.Time {
	if now.IsZero() || started.IsZero() {
		return nil
	}
	startDay := time.Date(started.Year(), started.Month(), started.Day(), 0, 0, 0, 0, beijing)
	for dayOffset := 0; dayOffset <= reminderPhaseDays; dayOffset++ {
		day := time.Date(now.Year(), now.Month(), now.Day()+dayOffset, 0, 0, 0, 0, beijing)
		elapsed := int(day.Sub(startDay).Hours() / 24)
		if elapsed < 0 {
			continue
		}
		if elapsed >= reminderPhaseDays {
			return nil
		}
		hours := []int{10, 14, 18}
		if elapsed >= 7 && elapsed < 21 {
			hours = make([]int, 0, 18)
			for hour := 6; hour <= 23; hour++ {
				hours = append(hours, hour)
			}
		}
		for _, hour := range hours {
			candidate := time.Date(day.Year(), day.Month(), day.Day(), hour, 0, 0, 0, beijing)
			if candidate.After(now) && !candidate.Before(started) {
				return &candidate
			}
		}
	}
	return nil
}

func reminderExpired(now, started time.Time) bool {
	if now.IsZero() || started.IsZero() {
		return false
	}
	startDay := time.Date(started.Year(), started.Month(), started.Day(), 0, 0, 0, 0, beijing)
	nowDay := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, beijing)
	return int(nowDay.Sub(startDay).Hours()/24) >= reminderPhaseDays
}

func assessmentType(value string) string {
	if strings.TrimSpace(value) == "考试" {
		return "exam"
	}
	return "assessment"
}

func programmeMatch(name, semester string, credit float64, values []any) (map[string]any, bool) {
	target := normalizeCourseName(name)
	candidates := make([]map[string]any, 0)
	for _, raw := range values {
		item, ok := raw.(map[string]any)
		if !ok || semester != "" && strings.TrimSpace(fmt.Sprint(item["semester"])) != semester || normalizeCourseName(fmt.Sprint(item["name"])) != target {
			continue
		}
		candidates = append(candidates, item)
	}
	if len(candidates) == 0 {
		return nil, false
	}
	if len(candidates) == 1 {
		return candidates[0], true
	}
	if credit > 0 {
		filtered := candidates[:0]
		for _, item := range candidates {
			if diff := mapFloat(item["credit"]) - credit; diff > -0.01 && diff < 0.01 {
				filtered = append(filtered, item)
			}
		}
		if len(filtered) == 1 {
			return filtered[0], true
		}
		if len(filtered) > 0 {
			candidates = filtered
		}
	}
	modes := map[string]bool{}
	for _, item := range candidates {
		modes[assessmentType(fmt.Sprint(item["exam_type"]))] = true
	}
	return candidates[0], len(modes) == 1
}

func (s *Server) syncUserReminderTasks(ctx context.Context, sid, semester string) error {
	if sid == "" {
		return nil
	}
	if semester == "" {
		var err error
		semester, err = s.store.UserSetting(ctx, sid, "semester")
		if err != nil {
			return fmt.Errorf("读取提醒学期: %w", err)
		}
	}
	if semester == "" {
		return nil
	}
	quotas, err := s.store.SubscriptionStatus(ctx, sid)
	if err != nil {
		return err
	}
	for _, kind := range []string{"exam", "grade"} {
		if quotas[kind].Count <= 0 {
			if _, err = s.store.DisableReminderKind(ctx, sid, semester, kind); err != nil {
				return err
			}
		}
	}
	if quotas["exam"].Count <= 0 && quotas["grade"].Count <= 0 {
		return nil
	}
	courses, err := s.store.Courses(ctx, sid, semester)
	if err != nil || len(courses) == 0 {
		return err
	}
	calendarRaw, err := s.store.Setting(ctx, calendarKey(semester))
	if err != nil {
		return err
	}
	programmeRaw, err := s.store.UserSetting(ctx, sid, "programme")
	if err != nil {
		return err
	}
	calendar := decodeMap(calendarRaw)
	programme := decodeMap(programmeRaw)
	programmeCourses, _ := programme["courses"].([]any)
	if len(programmeCourses) == 0 {
		return nil
	}
	type courseGroup struct {
		name, teacher, teacherNorm string
		credit                     float64
		courses                    []store.Course
	}
	groups := map[string]*courseGroup{}
	for _, course := range courses {
		name := strings.TrimSpace(course.Name)
		if name == "" {
			continue
		}
		teacherNorm := normalizeTeacherKey(course.Teacher)
		key := normalizeCourseName(name) + "|" + teacherNorm
		group := groups[key]
		if group == nil {
			group = &courseGroup{name: name, teacher: course.Teacher, teacherNorm: teacherNorm, credit: mapFloat(course.Credits)}
			groups[key] = group
		}
		group.courses = append(group.courses, course)
	}
	now := time.Now().In(beijing)
	seen := map[string]map[string]bool{"exam": {}, "grade": {}}
	for _, group := range groups {
		programmeItem, ok := programmeMatch(group.name, semester, group.credit, programmeCourses)
		if !ok {
			continue
		}
		mode := assessmentType(fmt.Sprint(programmeItem["exam_type"]))
		endAt := calendarCourseEnd(group.courses, calendar)
		courseKey := reminderHash(normalizeCourseName(group.name))
		teacherKey := reminderHash(group.teacherNorm)
		seenKey := courseKey + "|" + teacherKey
		if quotas["exam"].Count > 0 && mode == "exam" {
			stage, next := "scheduled", endAt
			if endAt == nil || !now.Before(*endAt) {
				stage, next = "wait_exam", &now
			}
			input := store.ReminderTaskInput{StudentID: sid, Semester: semester, Kind: "exam", CourseKey: courseKey, CourseName: group.name, TeacherKey: teacherKey, Teacher: group.teacher, AssessmentType: mode, Stage: stage, CourseEndAt: endAt, ExamWaitStartedAt: endAt, NextCheckAt: next, Status: "active"}
			if err = s.store.UpsertReminderTask(ctx, input); err != nil {
				return err
			}
			seen["exam"][seenKey] = true
		}
		if quotas["grade"].Count > 0 {
			stage, status := "scheduled", "active"
			next := endAt
			input := store.ReminderTaskInput{StudentID: sid, Semester: semester, Kind: "grade", CourseKey: courseKey, CourseName: group.name, TeacherKey: teacherKey, Teacher: group.teacher, AssessmentType: mode, CourseEndAt: endAt, Status: status}
			if mode == "exam" {
				input.ExamWaitStartedAt = endAt
				if endAt == nil || !now.Before(*endAt) {
					stage, next = "pending_exam", &now
				}
			} else {
				started := now
				if endAt != nil {
					started = *endAt
				}
				input.GradeWaitStartedAt = &started
				if !now.Before(started) {
					stage = "wait_grade"
					if reminderExpired(now, started) {
						stage, status, next = "expired", "expired", nil
					} else {
						next = gradeNextCheck(now.Add(-time.Second), started)
					}
				}
			}
			input.Stage, input.Status, input.NextCheckAt = stage, status, next
			if err = s.store.UpsertReminderTask(ctx, input); err != nil {
				return err
			}
			seen["grade"][seenKey] = true
		}
	}
	for kind, keys := range seen {
		if quotas[kind].Count > 0 {
			if _, err = s.store.DisableUnseenReminderTasks(ctx, sid, semester, kind, keys); err != nil {
				return err
			}
		}
	}
	return nil
}

func firstHHMM(value string) string {
	match := hhmmPattern.FindStringSubmatch(value)
	if len(match) < 3 {
		return ""
	}
	hour, _ := strconv.Atoi(match[1])
	return fmt.Sprintf("%02d:%s", hour, match[2])
}

func examStart(exam store.Exam) (time.Time, bool) {
	if len(exam.Date) < 10 {
		return time.Time{}, false
	}
	hm := firstHHMM(exam.Time)
	if hm == "" {
		hm = "08:00"
	}
	value, err := time.ParseInLocation("2006-01-02 15:04", exam.Date[:10]+" "+hm, beijing)
	return value, err == nil
}

func examEnd(exam store.Exam) *time.Time {
	start, ok := examStart(exam)
	if !ok {
		return nil
	}
	matches := hhmmPattern.FindAllStringSubmatch(exam.Time, -1)
	if len(matches) >= 2 {
		hour, _ := strconv.Atoi(matches[len(matches)-1][1])
		minute, _ := strconv.Atoi(matches[len(matches)-1][2])
		value := time.Date(start.Year(), start.Month(), start.Day(), hour, minute, 0, 0, beijing)
		if !value.Before(start) {
			return &value
		}
	}
	value := time.Date(start.Year(), start.Month(), start.Day(), 23, 59, 0, 0, beijing)
	return &value
}

func clipRunes(value string, limit int) string {
	runes := []rune(value)
	if len(runes) > limit {
		runes = runes[:limit]
	}
	return string(runes)
}

func examDuration(value string) string {
	matches := hhmmPattern.FindAllStringSubmatch(value, -1)
	if len(matches) < 2 {
		return "考试"
	}
	h1, _ := strconv.Atoi(matches[0][1])
	m1, _ := strconv.Atoi(matches[0][2])
	h2, _ := strconv.Atoi(matches[1][1])
	m2, _ := strconv.Atoi(matches[1][2])
	minutes := h2*60 + m2 - h1*60 - m1
	if minutes <= 0 {
		return "考试"
	}
	if minutes%60 == 0 {
		return fmt.Sprintf("%d小时", minutes/60)
	}
	return fmt.Sprintf("%d分钟", minutes)
}

func examTemplateData(exam store.Exam) map[string]any {
	when := strings.TrimSpace(exam.Date + " " + firstHHMM(exam.Time))
	detail := strings.Trim(strings.TrimSpace("座位"+exam.Seat+" · "+exam.Type), " ·")
	return map[string]any{
		"thing1": map[string]string{"value": clipRunes("考试提醒", 20)},
		"thing2": map[string]string{"value": clipRunes(examDuration(exam.Time), 20)},
		"time3":  map[string]string{"value": clipRunes(when, 20)},
		"thing4": map[string]string{"value": clipRunes(defaultText(exam.Location, "以教务为准"), 20)},
		"thing5": map[string]string{"value": clipRunes(detail, 20)},
	}
}

func gradeTemplateData(grade store.Grade, now time.Time) map[string]any {
	detail := grade.Score
	if grade.GradePoint != 0 {
		detail = fmt.Sprintf("%s · %.2g绩点", detail, grade.GradePoint)
	}
	return map[string]any{
		"thing1": map[string]string{"value": "成绩发布"},
		"thing2": map[string]string{"value": clipRunes(grade.CourseName, 20)},
		"time3":  map[string]string{"value": now.Format("2006-01-02 15:04")},
		"thing4": map[string]string{"value": "教务成绩查询"},
		"thing5": map[string]string{"value": clipRunes(defaultText(detail, "已出成绩"), 20)},
	}
}

func defaultText(value, fallback string) string {
	if strings.TrimSpace(value) == "" {
		return fallback
	}
	return strings.TrimSpace(value)
}

func ambiguousReminderNames(tasks []store.ReminderTask) map[string]bool {
	values := map[string]map[string]bool{}
	for _, task := range tasks {
		name := normalizeCourseName(task.CourseName)
		if values[name] == nil {
			values[name] = map[string]bool{}
		}
		values[name][task.TeacherKey] = true
	}
	out := map[string]bool{}
	for name, teachers := range values {
		out[name] = len(teachers) > 1
	}
	return out
}

func findExamForTask(task store.ReminderTask, exams []store.Exam, ambiguous map[string]bool) (store.Exam, bool) {
	wanted := normalizeCourseName(task.CourseName)
	if ambiguous[wanted] {
		return store.Exam{}, false
	}
	var found store.Exam
	count := 0
	for _, exam := range exams {
		if normalizeCourseName(exam.CourseName) == wanted {
			found, count = exam, count+1
		}
	}
	return found, count == 1
}

type reminderExamGroup struct {
	semester            string
	examIndexes         []int
	pendingGradeIndexes []int
}

func reminderExamGroups(examTasks, gradeTasks []store.ReminderTask) []reminderExamGroup {
	groups := make([]reminderExamGroup, 0)
	indexes := map[string]int{}
	groupFor := func(semester string) *reminderExamGroup {
		key := normalizeSemesterKey(semester)
		if index, ok := indexes[key]; ok {
			return &groups[index]
		}
		indexes[key] = len(groups)
		groups = append(groups, reminderExamGroup{semester: semester})
		return &groups[len(groups)-1]
	}
	for index := range examTasks {
		group := groupFor(examTasks[index].Semester)
		group.examIndexes = append(group.examIndexes, index)
	}
	for index := range gradeTasks {
		if gradeTasks[index].Stage != "pending_exam" {
			continue
		}
		group := groupFor(gradeTasks[index].Semester)
		group.pendingGradeIndexes = append(group.pendingGradeIndexes, index)
	}
	return groups
}

func (s *Server) persistentReminderClient(ctx context.Context, sid string) (*jwc.Client, error) {
	record, ok := s.auth.PersistentSession(ctx, sid)
	if !ok || strings.EqualFold(record.AccountType, "graduate") {
		return nil, errors.New("无有效本科教务 Cookie")
	}
	client := jwc.New(record.Cookies)
	client.StudentID = sid
	client.AccountType = record.AccountType
	client.SetTimeout(s.cfg.JWCRequestTimeout)
	if err := s.withJWC(ctx, func() error { return client.Resume(ctx, sid) }); err != nil {
		client.CloseIdleConnections()
		return nil, err
	}
	return client, nil
}

func (s *Server) sendDueExamReminders(ctx context.Context) error {
	now := time.Now().In(beijing)
	today := now.Format("2006-01-02")
	tomorrow := now.AddDate(0, 0, 1).Format("2006-01-02")
	exams, err := s.store.DueExams(ctx, today, tomorrow)
	if err != nil {
		return err
	}
	for _, item := range exams {
		if err := ctx.Err(); err != nil {
			return err
		}
		exam := item.Exam
		start, ok := examStart(exam)
		if !ok || !now.Before(start) {
			continue
		}
		if now.Format("2006-01-02") == start.Format("2006-01-02") {
			if now.Hour() < 6 {
				continue
			}
		} else if now.Hour() < 18 {
			continue
		}
		tasks, err := s.store.ActiveReminderTasks(ctx, item.StudentID, "exam")
		if err != nil {
			return err
		}
		tasks = reminderTasksForSemester(tasks, item.Semester)
		ambiguous := ambiguousReminderNames(tasks)
		matched := false
		for _, task := range tasks {
			if normalizeCourseName(task.CourseName) == normalizeCourseName(exam.CourseName) && !ambiguous[normalizeCourseName(task.CourseName)] && task.Stage == "wait_exam" {
				matched = true
				break
			}
		}
		if !matched {
			continue
		}
		claim := fmt.Sprintf("exam_reminded:%d", exam.ID)
		claimed, err := s.store.TryClaimUserSetting(ctx, item.StudentID, claim, "pending:"+strconv.FormatInt(now.Unix(), 10))
		if err != nil {
			return fmt.Errorf("占用考试提醒: %w", err)
		}
		if !claimed {
			continue
		}
		if err = s.sendReminder(ctx, item.StudentID, "exam", s.cfg.SubscribeExam, "pages/main/main?feature=exams", examTemplateData(exam)); err != nil {
			if releaseErr := s.store.DeleteClaim(ctx, item.StudentID, claim); releaseErr != nil {
				err = errors.Join(err, fmt.Errorf("释放考试提醒发送占用: %w", releaseErr))
			}
			s.logger.Warn("考试提醒发送失败", "sid_prefix", maskedSID(item.StudentID), "exam", exam.CourseName, "error", err)
			continue
		}
		if err = s.store.MarkReminderClaimSent(ctx, item.StudentID, claim, now); err != nil {
			return fmt.Errorf("完成考试提醒占用: %w", err)
		}
	}
	return nil
}

func (s *Server) sendReminder(ctx context.Context, sid, kind, template, page string, data map[string]any) error {
	if template == "" {
		return errors.New("未配置订阅模板")
	}
	openid, err := s.store.UserSetting(ctx, sid, "openid")
	if err != nil || openid == "" {
		return errors.New("用户没有 openid")
	}
	reserved, err := s.store.ReserveSubscription(ctx, sid, kind)
	if err != nil {
		return err
	}
	if !reserved {
		return errors.New("没有可用订阅额度")
	}
	result := s.sendSubscribePage(ctx, openid, template, page, data)
	if result["ok"] != true {
		sendErr := fmt.Errorf("微信订阅消息失败: %v %v", result["errcode"], result["errmsg"])
		if refundErr := s.store.RefundSubscription(ctx, sid, kind); refundErr != nil {
			return errors.Join(sendErr, fmt.Errorf("退回订阅额度失败: %w", refundErr))
		}
		return sendErr
	}
	return nil
}

func (s *Server) scheduleNextGrade(task *store.ReminderTask, now time.Time) {
	started := now
	if task.GradeWaitStartedAt != nil {
		started = *task.GradeWaitStartedAt
	} else if task.CourseEndAt != nil {
		started = *task.CourseEndAt
	}
	if reminderExpired(now, started) {
		task.Stage, task.Status, task.NextCheckAt = "expired", "expired", nil
		return
	}
	task.NextCheckAt = gradeNextCheck(now.Add(-time.Second), started)
	if task.NextCheckAt == nil {
		task.Stage, task.Status = "expired", "expired"
	}
}

func (s *Server) runReminderPool(ctx context.Context, limit int) error {
	now := time.Now().In(beijing)
	tasks, err := s.store.DueReminderTasks(ctx, now, max(1, limit))
	if err != nil || len(tasks) == 0 {
		return err
	}
	byStudent := map[string][]store.ReminderTask{}
	for _, task := range tasks {
		byStudent[task.StudentID] = append(byStudent[task.StudentID], task)
	}
	for sid, userTasks := range byStudent {
		if err := ctx.Err(); err != nil {
			return err
		}
		quotas, quotaErr := s.store.SubscriptionStatus(ctx, sid)
		if quotaErr != nil {
			return quotaErr
		}
		allowed := userTasks[:0]
		for _, task := range userTasks {
			if quotas[task.Kind].Count <= 0 {
				task.Status, task.NextCheckAt = "disabled", nil
				if err := s.store.SaveReminderTask(ctx, task); err != nil {
					return fmt.Errorf("禁用无额度提醒任务 %d: %w", task.ID, err)
				}
				continue
			}
			allowed = append(allowed, task)
		}
		if len(allowed) == 0 {
			continue
		}
		client, clientErr := s.persistentReminderClient(ctx, sid)
		if clientErr != nil {
			for _, task := range allowed {
				task.LastCheckAt = &now
				task.FailCount++
				if task.Kind == "grade" && task.Stage == "wait_grade" {
					s.scheduleNextGrade(&task, now)
				} else {
					next := now.Add(6 * time.Hour)
					task.NextCheckAt = &next
				}
				if err := s.store.SaveReminderTask(ctx, task); err != nil {
					return fmt.Errorf("保存提醒任务重试状态 %d: %w", task.ID, err)
				}
			}
			continue
		}
		if userErr := func() error {
			defer client.CloseIdleConnections()
			examTasks, gradeTasks := make([]store.ReminderTask, 0), make([]store.ReminderTask, 0)
			for _, task := range allowed {
				if task.Kind == "exam" {
					examTasks = append(examTasks, task)
				} else {
					if task.Stage == "scheduled" && (task.NextCheckAt == nil || !now.Before(*task.NextCheckAt)) {
						if task.AssessmentType == "exam" {
							task.Stage = "pending_exam"
							if task.ExamWaitStartedAt == nil {
								task.ExamWaitStartedAt = firstTime(task.CourseEndAt, now)
							}
						} else {
							task.Stage = "wait_grade"
							if task.GradeWaitStartedAt == nil {
								task.GradeWaitStartedAt = firstTime(task.CourseEndAt, now)
							}
						}
					}
					gradeTasks = append(gradeTasks, task)
				}
			}
			for _, group := range reminderExamGroups(examTasks, gradeTasks) {
				if err := ctx.Err(); err != nil {
					return err
				}
				var exams []store.Exam
				examErr := s.withJWC(ctx, func() error {
					var fetchErr error
					exams, fetchErr = client.Exams(ctx, group.semester)
					return fetchErr
				})
				if examErr == nil {
					examErr = s.store.ReplaceExams(ctx, sid, group.semester, exams)
					if saveErr := s.auth.SavePersistentSession(ctx, sid, client.AccountType, client.Cookies()); saveErr != nil {
						s.logger.Warn("保存提醒池教务 Cookie 失败", "sid_prefix", maskedSID(sid), "error", saveErr)
					}
				}
				allExamTasks := make([]store.ReminderTask, 0, len(group.examIndexes)+len(group.pendingGradeIndexes))
				for _, index := range group.examIndexes {
					allExamTasks = append(allExamTasks, examTasks[index])
				}
				for _, index := range group.pendingGradeIndexes {
					allExamTasks = append(allExamTasks, gradeTasks[index])
				}
				ambiguous := ambiguousReminderNames(allExamTasks)
				for _, index := range group.examIndexes {
					if err := ctx.Err(); err != nil {
						return err
					}
					task := &examTasks[index]
					if examErr != nil {
						task.FailCount++
						next := now.Add(6 * time.Hour)
						task.NextCheckAt = &next
					} else if exam, found := findExamForTask(*task, exams, ambiguous); found {
						if value, valid := examStart(exam); valid {
							task.ExamAt = &value
						}
						task.ExamFinishedAt = examEnd(exam)
						if task.ExamFinishedAt != nil && !now.Before(*task.ExamFinishedAt) {
							task.Stage, task.Status, task.NextCheckAt = "done", "done", nil
						} else {
							task.Stage = "wait_exam"
							next := now.AddDate(0, 0, 1)
							if task.ExamFinishedAt != nil && task.ExamFinishedAt.Before(next) {
								next = *task.ExamFinishedAt
							}
							task.NextCheckAt = &next
						}
					} else {
						started := derefTime(task.ExamWaitStartedAt, derefTime(task.CourseEndAt, now))
						if reminderExpired(now, started) {
							task.Stage, task.Status, task.NextCheckAt = "expired", "expired", nil
						} else {
							next := now.AddDate(0, 0, 1)
							task.NextCheckAt = &next
						}
					}
					task.LastCheckAt = &now
					if err := s.store.SaveReminderTask(ctx, *task); err != nil {
						return fmt.Errorf("保存考试提醒任务 %d: %w", task.ID, err)
					}
				}
				for _, index := range group.pendingGradeIndexes {
					if err := ctx.Err(); err != nil {
						return err
					}
					task := &gradeTasks[index]
					if examErr != nil {
						task.FailCount++
						next := now.Add(6 * time.Hour)
						task.NextCheckAt = &next
					} else if exam, found := findExamForTask(*task, exams, ambiguous); found {
						if value, valid := examStart(exam); valid {
							task.ExamAt = &value
						}
						task.ExamFinishedAt = examEnd(exam)
						if task.ExamFinishedAt != nil && !now.Before(*task.ExamFinishedAt) {
							task.Stage, task.GradeWaitStartedAt = "wait_grade", task.ExamFinishedAt
							s.scheduleNextGrade(task, now)
						} else {
							next := now.Add(6 * time.Hour)
							if task.ExamFinishedAt != nil {
								next = *task.ExamFinishedAt
							}
							task.NextCheckAt = &next
						}
					} else {
						started := derefTime(task.ExamWaitStartedAt, derefTime(task.CourseEndAt, now))
						if reminderExpired(now, started) {
							task.Stage, task.GradeWaitStartedAt = "wait_grade", &now
							s.scheduleNextGrade(task, now)
						} else {
							next := now.AddDate(0, 0, 1)
							task.NextCheckAt = &next
						}
					}
					task.LastCheckAt = &now
					if err := s.store.SaveReminderTask(ctx, *task); err != nil {
						return fmt.Errorf("保存成绩提醒考试阶段 %d: %w", task.ID, err)
					}
				}
			}
			ready := make([]store.ReminderTask, 0)
			for _, task := range gradeTasks {
				if task.Stage == "wait_grade" {
					ready = append(ready, task)
				}
			}
			if len(ready) == 0 {
				return nil
			}
			var grades []store.Grade
			gradeErr := s.withJWC(ctx, func() error {
				var fetchErr error
				grades, fetchErr = client.Grades(ctx, "")
				return fetchErr
			})
			if gradeErr == nil {
				gradeErr = s.store.ReplaceGrades(ctx, sid, grades)
				if saveErr := s.auth.SavePersistentSession(ctx, sid, client.AccountType, client.Cookies()); saveErr != nil {
					s.logger.Warn("保存提醒池教务 Cookie 失败", "sid_prefix", maskedSID(sid), "error", saveErr)
				}
			}
			active, err := s.store.ActiveReminderTasks(ctx, sid, "grade")
			if err != nil {
				return fmt.Errorf("读取有效成绩提醒任务: %w", err)
			}
			activeCount := map[string]int{}
			for _, task := range active {
				activeCount[reminderCourseKey(task.Semester, task.CourseName)]++
			}
			for _, task := range ready {
				task.LastCheckAt = &now
				if gradeErr != nil {
					task.FailCount++
					s.scheduleNextGrade(&task, now)
					if err := s.store.SaveReminderTask(ctx, task); err != nil {
						return fmt.Errorf("保存成绩提醒失败状态 %d: %w", task.ID, err)
					}
					continue
				}
				matches := gradesForReminderTask(task, grades)
				if len(matches) != 1 || activeCount[reminderCourseKey(task.Semester, task.CourseName)] != 1 {
					s.scheduleNextGrade(&task, now)
					if err := s.store.SaveReminderTask(ctx, task); err != nil {
						return fmt.Errorf("保存歧义成绩提醒状态 %d: %w", task.ID, err)
					}
					continue
				}
				task.GradeFirstSeenAt = &now
				claim := fmt.Sprintf("grade_reminded:%d", task.ID)
				claimed, claimErr := s.store.TryClaimUserSetting(ctx, sid, claim, "pending:"+strconv.FormatInt(now.Unix(), 10))
				if claimErr != nil {
					return fmt.Errorf("占用成绩提醒任务 %d: %w", task.ID, claimErr)
				}
				if !claimed {
					state, stateErr := s.store.ReminderClaimState(ctx, sid, claim)
					if stateErr != nil {
						return fmt.Errorf("读取成绩提醒占用状态 %d: %w", task.ID, stateErr)
					}
					if state == "sent" {
						task.Stage, task.Status, task.SentAt, task.NextCheckAt = "done", "done", &now, nil
						if err := s.store.SaveReminderTask(ctx, task); err != nil {
							return fmt.Errorf("对账已发送提醒任务 %d: %w", task.ID, err)
						}
						continue
					}
					s.scheduleNextGrade(&task, now)
					if err := s.store.SaveReminderTask(ctx, task); err != nil {
						return fmt.Errorf("保存已占用提醒任务 %d: %w", task.ID, err)
					}
					continue
				}
				if sendErr := s.sendReminder(ctx, sid, "grade", s.cfg.SubscribeGrade, "pages/main/main?feature=grades", gradeTemplateData(matches[0], now)); sendErr != nil {
					if releaseErr := s.store.DeleteClaim(ctx, sid, claim); releaseErr != nil {
						return errors.Join(sendErr, fmt.Errorf("释放成绩提醒发送占用: %w", releaseErr))
					}
					s.scheduleNextGrade(&task, now)
					if err := s.store.SaveReminderTask(ctx, task); err != nil {
						return fmt.Errorf("保存成绩提醒重试状态 %d: %w", task.ID, err)
					}
					continue
				}
				task.Stage, task.Status, task.SentAt, task.NextCheckAt = "done", "done", &now, nil
				if err := s.store.CompleteReminderTask(ctx, task, claim, now); err != nil {
					return fmt.Errorf("完成成绩提醒任务 %d: %w", task.ID, err)
				}
				if err := s.store.BoostReminderGroup(ctx, task.Semester, task.CourseKey, task.TeacherKey, sid, now); err != nil {
					return fmt.Errorf("加速同组成绩提醒: %w", err)
				}
				remaining, err := s.store.SubscriptionStatus(ctx, sid)
				if err != nil {
					return fmt.Errorf("读取提醒剩余额度: %w", err)
				}
				if remaining["grade"].Count <= 0 {
					if err := s.store.DisableOtherReminderTasks(ctx, sid, "grade", task.ID); err != nil {
						return fmt.Errorf("停用无额度成绩提醒: %w", err)
					}
				}
			}
			return nil
		}(); userErr != nil {
			return userErr
		}
	}
	return nil
}

func firstTime(value *time.Time, fallback time.Time) *time.Time {
	if value != nil {
		copy := *value
		return &copy
	}
	return &fallback
}

func derefTime(value *time.Time, fallback time.Time) time.Time {
	if value != nil {
		return *value
	}
	return fallback
}
