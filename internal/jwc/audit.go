package jwc

import (
	"context"
	"fmt"
	"net/http"
	"regexp"
	"strings"

	"github.com/PuerkitoBio/goquery"
	"github.com/resetinging/njust-schedule/internal/store"
)

const auditQueryURL = JWBase + "/kbcx/kbxx_kc"

var weekLinePattern = regexp.MustCompile(`^(.+?)\s*[（(]([^）)]*周)[）)]$`)
var classInfoPattern = regexp.MustCompile(`^\d{6,}(?:\s*[,，]\s*\d{6,})*$`)
var classroomPattern = regexp.MustCompile(`(?i)(?:[ⅠⅡⅢⅣIVX]+[-－A-Za-z]?\d+|\d{3}[-－]\d+|(?:教室|实验|外教|楼|馆|中心).{0,12}\d*)$`)
var catalogWeekPattern = regexp.MustCompile(`[（(]([^()（）]*?\d[^()（）]*?周)[）)]`)
var catalogClassInfoSingle = regexp.MustCompile(`^(?:临班|班)?\s*\d+$`)
var catalogClassInfoCode = regexp.MustCompile(`^[0-9A-Za-z]{6,}$`)
var catalogClassInfoPart = regexp.MustCompile(`^[0-9A-Za-z]{4,}$`)

func (c *Client) AuditCatalog(ctx context.Context, semester string) ([]store.AuditCourse, error) {
	resp, err := c.request(ctx, http.MethodGet, auditQueryURL, nil)
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
		return nil, fmt.Errorf("解析课程课表查询页: %w", err)
	}
	form := doc.Find("form#Form1").First()
	if form.Length() == 0 {
		form = doc.Find("form").FilterFunction(func(_ int, s *goquery.Selection) bool { return s.Find("select[name='xnxqh']").Length() > 0 }).First()
	}
	if form.Length() == 0 {
		return nil, fmt.Errorf("课程课表查询未找到 Form1")
	}
	parsed := parseForm(form)
	if err = validatePostForm(parsed); err != nil {
		return nil, err
	}
	values := parsed.Values
	values.Set("xnxqh", semester)
	values.Set("kc", "")
	if values.Has("zzdKcSX") {
		values.Set("zzdKcSX", "")
	}
	target, err := resolveFormURL(resp.Request.URL.String(), parsed.Action)
	if err != nil {
		return nil, err
	}
	resultResp, err := c.request(ctx, http.MethodPost, target, values)
	if err != nil {
		return nil, err
	}
	resultRaw, err := readResponse(resultResp)
	if err != nil {
		return nil, err
	}
	if c.isLoginPage(resultResp, resultRaw) {
		return nil, ErrSessionExpired
	}
	resultDoc, err := parseDocument(resultRaw)
	if err != nil {
		return nil, fmt.Errorf("解析课程课表结果页: %w", err)
	}
	table := resultDoc.Find("table#kbtable").First()
	if table.Length() == 0 {
		return nil, fmt.Errorf("课程课表查询未找到 kbtable")
	}
	return parseAuditTable(table), nil
}

func parseAuditTable(table *goquery.Selection) []store.AuditCourse {
	rows := table.Find("tr")
	var values []store.AuditCourse
	if looksLikeAuditCatalog(rows) {
		values = parseAuditCatalog(rows)
	} else {
		values = parseAuditGridTable(table)
	}
	return dedupeAuditCourses(values)
}

func dedupeAuditCourses(values []store.AuditCourse) []store.AuditCourse {
	seen := map[string]bool{}
	out := make([]store.AuditCourse, 0, len(values))
	for _, value := range values {
		key := fmt.Sprintf("%s\x00%s\x00%s\x00%s\x00%d\x00%d\x00%d\x00%s",
			value.Name, value.ClassInfo, value.Teacher, value.Classroom,
			value.Day, value.Start, value.End, value.Weeks)
		if seen[key] {
			continue
		}
		seen[key] = true
		out = append(out, value)
	}
	return out
}

func parseAuditGridTable(table *goquery.Selection) []store.AuditCourse {
	rows := table.Find("tr")
	dayColumns := map[int]int{}
	rows.First().Find("td,th").Each(func(i int, cell *goquery.Selection) {
		text := cell.Text()
		for char, day := range dayNumber {
			if strings.Contains(text, char) {
				dayColumns[i] = day
				break
			}
		}
	})
	blockRanges := map[string][2]int{"一": [2]int{1, 3}, "二": [2]int{4, 5}, "三": [2]int{6, 7}, "四": [2]int{8, 10}, "五": [2]int{11, 13}, "1-3": [2]int{1, 3}, "4-5": [2]int{4, 5}, "6-7": [2]int{6, 7}, "8-10": [2]int{8, 10}, "11-13": [2]int{11, 13}}
	seen := map[string]bool{}
	var out []store.AuditCourse
	rows.Each(func(rowIndex int, row *goquery.Selection) {
		if rowIndex == 0 {
			return
		}
		cells := row.Find("td,th")
		if cells.Length() < 2 {
			return
		}
		label := strings.TrimSpace(cells.First().Text())
		period := [2]int{}
		for key, value := range blockRanges {
			if strings.Contains(label, key) {
				period = value
				break
			}
		}
		if period[0] == 0 {
			return
		}
		cells.Each(func(column int, cell *goquery.Selection) {
			day := dayColumns[column]
			if day == 0 {
				return
			}
			contents := cell.Find("div.kbcontent")
			if contents.Length() == 0 {
				contents = cell.Find("div")
			}
			contents.Each(func(_ int, content *goquery.Selection) {
				html, _ := content.Html()
				lines := splitHTMLLines(strings.ReplaceAll(html, "----------", "<br>"))
				if len(lines) < 2 {
					return
				}
				name := strings.TrimSpace(lines[0])
				if name == "" || name == "&nbsp;" {
					return
				}
				rest := lines[1:]
				for i := 0; i < len(rest); i++ {
					match := weekLinePattern.FindStringSubmatch(rest[i])
					if len(match) != 3 {
						continue
					}
					teacher := strings.TrimSpace(match[1])
					weeks := strings.TrimSpace(strings.TrimSuffix(match[2], "周"))
					classInfo := ""
					if i > 0 && classInfoPattern.MatchString(strings.ReplaceAll(rest[i-1], " ", "")) {
						classInfo = strings.ReplaceAll(rest[i-1], "，", ",")
					}
					room := ""
					if i+1 < len(rest) && looksClassroom(rest[i+1]) {
						room = strings.TrimSpace(rest[i+1])
					}
					if looksClassroom(teacher) && room == "" {
						room = teacher
						teacher = ""
					}
					entry := store.AuditCourse{Name: name, ClassInfo: classInfo, Teacher: teacher, Classroom: room, Day: day, Start: period[0], End: period[1], Weeks: weeks}
					key := fmt.Sprintf("%s|%s|%s|%s|%d|%d|%d|%s", entry.Name, entry.ClassInfo, entry.Teacher, entry.Classroom, entry.Day, entry.Start, entry.End, entry.Weeks)
					if !seen[key] {
						seen[key] = true
						out = append(out, entry)
					}
				}
			})
		})
	})
	return out
}

func looksLikeAuditCatalog(rows *goquery.Selection) bool {
	if rows.Length() < 2 {
		return false
	}
	hasSixColumnHeader := false
	rows.First().Find("td,th").EachWithBreak(func(_ int, cell *goquery.Selection) bool {
		if strings.TrimSpace(cell.AttrOr("colspan", "1")) == "6" {
			hasSixColumnHeader = true
			return false
		}
		return true
	})
	return hasSixColumnHeader && rows.Eq(1).Find("td,th").Length() > 13
}

func parseAuditCatalog(rows *goquery.Selection) []store.AuditCourse {
	periods := [][2]int{{1, 3}, {4, 5}, {6, 7}, {8, 10}, {11, 13}, {14, 14}}
	var out []store.AuditCourse
	rows.Slice(2, rows.Length()).Each(func(_ int, row *goquery.Selection) {
		cells := row.Find("td,th")
		if cells.Length() == 0 {
			return
		}
		courseName := strings.Join(strings.Fields(cells.Eq(0).Text()), " ")
		if courseName == "" {
			return
		}
		cells.Slice(1, cells.Length()).Each(func(index int, cell *goquery.Selection) {
			slotIndex := index % len(periods)
			day := index/len(periods) + 1
			if day > 7 {
				return
			}
			cell.Find("div.kbcontent, div.kbcontent1").Each(func(_ int, detail *goquery.Selection) {
				out = append(out, parseAuditCatalogEntry(detail, courseName, day, periods[slotIndex])...)
			})
		})
	})
	return out
}

func parseAuditCatalogEntry(detail *goquery.Selection, courseName string, day int, period [2]int) []store.AuditCourse {
	raw, _ := detail.Html()
	lines := fragmentLines(raw)
	var out []store.AuditCourse
	cursor := 0
	for cursor < len(lines) {
		weekIndex := -1
		var weekMatch []string
		for index := cursor; index < len(lines); index++ {
			if match := catalogWeekPattern.FindStringSubmatch(lines[index]); len(match) == 2 {
				weekIndex = index
				weekMatch = match
				break
			}
		}
		if weekIndex < 0 {
			break
		}
		before := append([]string(nil), lines[cursor:weekIndex]...)
		location := catalogWeekPattern.FindStringIndex(lines[weekIndex])
		if location != nil {
			if inline := strings.Trim(strings.TrimSpace(lines[weekIndex][:location[0]]), " ,，;；"); inline != "" {
				before = append(before, inline)
			}
		}
		if len(before) == 0 {
			cursor = weekIndex + 1
			continue
		}
		classInfo := strings.TrimSpace(before[0])
		classroomBeforeWeek := ""
		for _, value := range before[1:] {
			if looksLikeCatalogClassroom(value) {
				classroomBeforeWeek = value
				break
			}
		}
		var teachers []string
		for _, value := range before[1:] {
			value = strings.Trim(strings.TrimSpace(value), " ,，;；")
			if value != "" && value != classroomBeforeWeek {
				teachers = append(teachers, value)
			}
		}
		classroom := ""
		nextIndex := weekIndex + 1
		if nextIndex < len(lines) {
			candidate := strings.TrimSpace(lines[nextIndex])
			if !catalogWeekPattern.MatchString(candidate) && !looksLikeCatalogClassInfo(candidate) {
				classroom = candidate
				nextIndex++
			}
		}
		if classroom == "" {
			classroom = classroomBeforeWeek
		}
		name := courseName
		if name == "" {
			name = classInfo
		}
		weeks := strings.ReplaceAll(weekMatch[1], "周", "")
		weeks = strings.NewReplacer("（", "", "）", "", "(", "", ")", "", " ", "").Replace(weeks)
		out = append(out, store.AuditCourse{
			Name: name, ClassInfo: classInfo, Teacher: strings.Join(teachers, ","),
			Classroom: classroom, Day: day, Start: period[0], End: period[1],
			Weeks: weeks,
		})
		if nextIndex > weekIndex+1 {
			cursor = nextIndex
		} else {
			cursor = weekIndex + 1
		}
	}
	return out
}

func looksLikeCatalogClassInfo(value string) bool {
	text := strings.TrimSpace(value)
	if text == "" {
		return false
	}
	if catalogClassInfoSingle.MatchString(text) {
		return true
	}
	if catalogClassInfoCode.MatchString(text) && strings.IndexAny(text, "0123456789") >= 0 {
		return true
	}
	parts := strings.FieldsFunc(text, func(r rune) bool { return r == ',' || r == '，' })
	if len(parts) <= 1 {
		return false
	}
	for _, part := range parts {
		part = strings.TrimSpace(part)
		if !catalogClassInfoPart.MatchString(part) || strings.IndexAny(part, "0123456789") < 0 {
			return false
		}
	}
	return true
}

func looksLikeCatalogClassroom(value string) bool {
	text := strings.TrimSpace(value)
	if text == "" {
		return false
	}
	if regexp.MustCompile(`^(?:设传外教|设传教室|设传实验)\s*\d+$`).MatchString(text) {
		return true
	}
	return looksClassroom(text)
}

func looksClassroom(value string) bool {
	text := strings.TrimSpace(value)
	if text == "" {
		return false
	}
	if regexp.MustCompile(`^(?:设传外教|设传教室|设传实验)\s*\d+$`).MatchString(text) {
		return true
	}
	return classroomPattern.MatchString(text)
}
