package jwc

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/PuerkitoBio/goquery"
	"github.com/resetinging/njust-schedule/internal/store"
)

func firstString(item map[string]any, keys ...string) string {
	for _, key := range keys {
		if value, ok := item[key]; ok && value != nil {
			text := strings.TrimSpace(fmt.Sprint(value))
			if text != "" && text != "<nil>" {
				return text
			}
		}
	}
	return ""
}
func asFloat(value any) float64 {
	n, _ := strconv.ParseFloat(strings.TrimSpace(fmt.Sprint(value)), 64)
	return n
}
func apiItems(raw any) []map[string]any {
	switch value := raw.(type) {
	case []any:
		out := make([]map[string]any, 0, len(value))
		for _, item := range value {
			if row, ok := item.(map[string]any); ok {
				out = append(out, row)
			}
		}
		return out
	case map[string]any:
		if data, ok := value["data"]; ok {
			return apiItems(data)
		}
	}
	return nil
}

func (c *Client) Courses(ctx context.Context, semester string) ([]store.Course, error) {
	query := url.Values{"method": {"getKbcxAzc"}, "xh": {c.StudentID}, "xnxqid": {semester}}
	var raw any
	if err := c.JSON(ctx, http.MethodPost, appURL+"?"+query.Encode(), nil, &raw); err == nil {
		courses := parseCourseItems(apiItems(raw))
		if len(courses) > 0 {
			return dedupeCourses(courses), nil
		}
	}
	return c.coursesHTML(ctx, semester)
}

func parseCourseItems(items []map[string]any) []store.Course {
	courses := make([]store.Course, 0, len(items))
	for _, item := range items {
		name := firstString(item, "kcmc")
		kcsj := firstString(item, "kcsj")
		day, start, end := 0, 0, 0
		if len(kcsj) >= 5 {
			day, _ = strconv.Atoi(kcsj[:1])
			start, _ = strconv.Atoi(kcsj[1:3])
			end, _ = strconv.Atoi(kcsj[3:5])
		}
		if name == "" || day < 1 || day > 7 || start < 1 || end < start {
			continue
		}
		weekType := 0
		if v := firstString(item, "sjbz"); v == "1" {
			weekType = 1
		} else if v == "2" {
			weekType = 2
		}
		rawJSON, _ := json.Marshal(item)
		courses = append(courses, store.Course{Name: name, Teacher: firstString(item, "jsxm", "jsm"), Classroom: firstString(item, "jsmc", "jsm"), Day: day, Start: start, End: end, Weeks: firstString(item, "kkzc", "zcsm"), WeekType: weekType, Credits: firstString(item, "xf"), CourseType: firstString(item, "kclb", "kcType"), RawData: string(rawJSON)})
	}
	return courses
}

func dedupeCourses(values []store.Course) []store.Course {
	seen := map[string]bool{}
	out := make([]store.Course, 0, len(values))
	for _, v := range values {
		key := fmt.Sprintf("%s\x00%s\x00%s\x00%d\x00%d\x00%d\x00%s", v.Name, v.Teacher, v.Classroom, v.Day, v.Start, v.End, v.Weeks)
		if !seen[key] {
			seen[key] = true
			out = append(out, v)
		}
	}
	return out
}

var timePattern = regexp.MustCompile(`星期([一二三四五六日])\((\d+)-(\d+)小节\)`)
var dayNumber = map[string]int{"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7}

func (c *Client) coursesHTML(ctx context.Context, semester string) ([]store.Course, error) {
	resp, err := c.request(ctx, http.MethodGet, scheduleURL, nil)
	if err != nil {
		return nil, err
	}
	raw, err := readResponse(resp)
	if err != nil {
		return nil, err
	}
	if c.isLoginPage(resp, raw) {
		return nil, ErrSessionExpired
	}
	doc, err := parseDocument(raw)
	if err != nil {
		return nil, err
	}
	if semester != "" {
		form := doc.Find("form#Form1").First()
		if form.Length() > 0 {
			parsed := parseForm(form)
			if err = validatePostForm(parsed); err != nil {
				return nil, err
			}
			values := parsed.Values
			if values.Has("xnxq01id") {
				values.Set("xnxq01id", semester)
				values.Set("zc", "")
				target, targetErr := resolveFormURL(resp.Request.URL.String(), parsed.Action)
				if targetErr != nil {
					return nil, targetErr
				}
				postResp, postErr := c.request(ctx, http.MethodPost, target, values)
				if postErr != nil {
					return nil, postErr
				}
				posted, readErr := readResponse(postResp)
				if readErr != nil {
					return nil, readErr
				}
				if c.isLoginPage(postResp, posted) {
					return nil, ErrSessionExpired
				}
				doc, err = parseDocument(posted)
				if err != nil {
					return nil, err
				}
			}
		}
	}
	courses := parseScheduleDocument(doc)
	if len(courses) == 0 {
		return nil, fmt.Errorf("课表解析为空")
	}
	return dedupeCourses(courses), nil
}

func (c *Client) Exams(ctx context.Context, semester string) ([]store.Exam, error) {
	query := url.Values{"method": {"getXsksap"}, "xh": {c.StudentID}, "xnxqid": {semester}}
	var raw any
	if err := c.JSON(ctx, http.MethodPost, appURL+"?"+query.Encode(), nil, &raw); err == nil {
		out := parseExamItems(apiItems(raw))
		if len(out) > 0 {
			return out, nil
		}
	}
	return c.examsHTML(ctx, semester)
}

func parseExamItems(items []map[string]any) []store.Exam {
	out := make([]store.Exam, 0, len(items))
	for _, item := range items {
		name := firstString(item, "kcmc")
		if name == "" {
			continue
		}
		out = append(out, store.Exam{CourseName: name, Date: firstString(item, "ksrq", "examDate"), Time: firstString(item, "kssj", "examTime"), Location: firstString(item, "ksdd", "examRoom"), Seat: firstString(item, "zwh", "seatNum"), Type: defaultString(firstString(item, "kslx"), "期末考试")})
	}
	return out
}

func (c *Client) examsHTML(ctx context.Context, semester string) ([]store.Exam, error) {
	doc, err := c.postHTMLDocument(ctx, examListURL, url.Values{
		"xnxqid": {semester},
		"method": {"query"},
	})
	if err == nil {
		if values, ok := parseExamTable(doc); ok {
			return values, nil
		}
	}
	doc, getErr := c.getHTMLDocument(ctx, examListURL)
	if getErr != nil {
		if err != nil {
			return nil, err
		}
		return nil, getErr
	}
	values, ok := parseExamTable(doc)
	if !ok {
		return nil, fmt.Errorf("考试页面未找到数据表格")
	}
	return values, nil
}

func parseExamTable(doc *goquery.Document) ([]store.Exam, bool) {
	table := findDataTable(doc, []string{"考试", "课程名称", "考场"})
	if table.Length() == 0 {
		return nil, false
	}
	var out []store.Exam
	table.Find("tr").Each(func(i int, row *goquery.Selection) {
		if i == 0 {
			return
		}
		texts := selectionTexts(row.Find("td,th"))
		if len(texts) < 6 || at(texts, 3) == "" {
			return
		}
		date, timeText := splitDateTime(at(texts, 4))
		out = append(out, store.Exam{CourseName: at(texts, 3), Date: date, Time: timeText, Location: at(texts, 5), Seat: at(texts, 6), Type: "期末考试"})
	})
	if out == nil {
		out = []store.Exam{}
	}
	return out, true
}

func (c *Client) Grades(ctx context.Context, semester string) ([]store.Grade, error) {
	query := url.Values{"method": {"getCjcx"}, "xh": {c.StudentID}, "xnxqid": {semester}}
	var raw any
	if err := c.JSON(ctx, http.MethodPost, appURL+"?"+query.Encode(), nil, &raw); err == nil {
		out := parseGradeItems(apiItems(raw))
		if len(out) > 0 {
			return out, nil
		}
	}
	return c.gradesHTML(ctx, semester)
}

func parseGradeItems(items []map[string]any) []store.Grade {
	out := make([]store.Grade, 0, len(items))
	for _, item := range items {
		name := firstString(item, "kcmc")
		if name == "" {
			continue
		}
		out = append(out, store.Grade{AcademicYear: firstString(item, "xn", "xnm"), Semester: firstString(item, "xq", "xqm"), CourseCode: firstString(item, "kcdm", "kch"), CourseName: name, Score: firstString(item, "cj", "kscj"), Credit: asFloat(item["xf"]), GradePoint: asFloat(firstValue(item, "jd", "jdn")), CourseType: firstString(item, "kclb", "kclbmc"), CourseNature: firstString(item, "kcxz", "kcxzmc"), ExamType: defaultString(firstString(item, "kslx", "khfsmc"), "正常考试")})
	}
	return out
}

func firstValue(item map[string]any, keys ...string) any {
	for _, k := range keys {
		if v, ok := item[k]; ok && fmt.Sprint(v) != "" {
			return v
		}
	}
	return nil
}

func (c *Client) gradesHTML(ctx context.Context, semester string) ([]store.Grade, error) {
	doc, err := c.postHTMLDocument(ctx, gradeListURL, url.Values{"xnxqid": {semester}})
	if err == nil {
		if values, ok := parseGradeTable(doc); ok {
			return values, nil
		}
	}
	doc, getErr := c.getHTMLDocument(ctx, gradeListURL)
	if getErr != nil {
		if err != nil {
			return nil, err
		}
		return nil, getErr
	}
	values, ok := parseGradeTable(doc)
	if !ok {
		return nil, fmt.Errorf("成绩页面未找到数据表格")
	}
	return values, nil
}

func parseGradeTable(doc *goquery.Document) ([]store.Grade, bool) {
	table := findDataTable(doc, []string{"课程名称", "成绩", "学分"})
	if table.Length() == 0 {
		return nil, false
	}
	headers := selectionTexts(table.Find("tr").First().Find("td,th"))
	column := map[string]int{}
	for i, text := range headers {
		switch text {
		case "课程名称":
			column["name"] = i
		case "课程编号", "课程代码":
			column["code"] = i
		case "成绩":
			column["score"] = i
		case "学分":
			column["credit"] = i
		case "绩点":
			column["point"] = i
		case "课程属性":
			column["type"] = i
		case "课程性质":
			column["nature"] = i
		case "考核方式", "考试类型", "考试性质":
			column["exam"] = i
		case "开课学期", "学年学期":
			column["semester"] = i
		}
	}
	if _, ok := column["name"]; !ok {
		column = map[string]int{"semester": 1, "code": 2, "name": 3, "score": 4, "credit": 6, "exam": 8, "type": 9, "nature": 10}
	}
	var out []store.Grade
	table.Find("tr").Each(func(i int, row *goquery.Selection) {
		if i == 0 {
			return
		}
		texts := selectionTexts(row.Find("td,th"))
		name := at(texts, column["name"])
		if name == "" || strings.Contains(name, "合计") || strings.Contains(name, "平均") {
			return
		}
		year, sem := parseSemester(at(texts, column["semester"]))
		point := ""
		if index, ok := column["point"]; ok {
			point = at(texts, index)
		}
		out = append(out, store.Grade{AcademicYear: year, Semester: sem, CourseCode: at(texts, column["code"]), CourseName: name, Score: at(texts, column["score"]), Credit: parseFloat(at(texts, column["credit"])), GradePoint: parseFloat(point), CourseType: at(texts, column["type"]), CourseNature: at(texts, column["nature"]), ExamType: defaultString(at(texts, column["exam"]), "正常考试")})
	})
	if out == nil {
		out = []store.Grade{}
	}
	return out, true
}

func (c *Client) CETScores(ctx context.Context) ([]store.CETScore, error) {
	resp, err := c.request(ctx, http.MethodGet, cetURL, nil)
	if err != nil {
		return nil, err
	}
	raw, err := readResponse(resp)
	if err != nil {
		return nil, err
	}
	if c.isLoginPage(resp, raw) {
		return nil, ErrSessionExpired
	}
	doc, _ := parseDocument(raw)
	table := doc.Find("table#dataList").First()
	if table.Length() == 0 {
		return nil, fmt.Errorf("四六级页面未找到数据表格")
	}
	best := map[string]store.CETScore{}
	table.Find("tr").Each(func(_ int, row *goquery.Selection) {
		texts := selectionTexts(row.Find("td"))
		if len(texts) < 9 {
			return
		}
		kind := ""
		if strings.Contains(texts[1], "CET6") {
			kind = "CET6"
		} else if strings.Contains(texts[1], "CET4") {
			kind = "CET4"
		}
		score := parseFloat(texts[4])
		if kind != "" && score > best[kind].Score {
			best[kind] = store.CETScore{Type: kind, Score: score, ExamDate: texts[8]}
		}
	})
	out := make([]store.CETScore, 0, len(best))
	for _, kind := range []string{"CET4", "CET6"} {
		if value, ok := best[kind]; ok {
			out = append(out, value)
		}
	}
	return out, nil
}

func findDataTable(doc *goquery.Document, keywords []string) *goquery.Selection {
	preferred := doc.Find("table#dataList").First()
	if preferred.Length() > 0 {
		return preferred
	}
	preferred = doc.Find("table.Nsb_r_list").First()
	if preferred.Length() > 0 {
		return preferred
	}
	var found *goquery.Selection
	doc.Find("table").EachWithBreak(func(_ int, s *goquery.Selection) bool {
		text := s.Find("tr").First().Text()
		for _, kw := range keywords {
			if strings.Contains(text, kw) {
				found = s
				return false
			}
		}
		return true
	})
	if found == nil {
		return doc.Find("table.__missing__")
	}
	return found
}

func selectionTexts(s *goquery.Selection) []string {
	out := make([]string, 0, s.Length())
	s.Each(func(_ int, item *goquery.Selection) {
		out = append(out, strings.Join(strings.Fields(item.Text()), " "))
	})
	return out
}
func at(values []string, index int) string {
	if index < 0 || index >= len(values) {
		return ""
	}
	return strings.TrimSpace(values[index])
}
func parseFloat(raw string) float64 { v, _ := strconv.ParseFloat(strings.TrimSpace(raw), 64); return v }
func defaultString(value, fallback string) string {
	if strings.TrimSpace(value) == "" {
		return fallback
	}
	return value
}
func parseSemester(raw string) (string, string) {
	parts := strings.Split(raw, "-")
	if len(parts) >= 3 {
		return parts[0] + "-" + parts[1], parts[2]
	}
	return raw, ""
}
func splitDateTime(raw string) (string, string) {
	parts := strings.SplitN(strings.TrimSpace(raw), " ", 2)
	if len(parts) == 2 {
		return parts[0], parts[1]
	}
	return raw, ""
}

var brPattern = regexp.MustCompile(`(?i)<br\s*/?>|</br>`)
var tagPattern = regexp.MustCompile(`<[^>]+>`)
var hyphenPattern = regexp.MustCompile(`-{10,}`)

func splitHTMLLines(raw string) []string {
	parts := brPattern.Split(raw, -1)
	var out []string
	for _, part := range parts {
		text := strings.TrimSpace(tagPattern.ReplaceAllString(part, ""))
		if text != "" {
			out = append(out, text)
		}
	}
	return out
}

var _ = sort.Strings
