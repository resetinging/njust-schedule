package jwc

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"

	"github.com/PuerkitoBio/goquery"
	"github.com/resetinging/njust-schedule/internal/store"
	"golang.org/x/net/html"
)

const (
	ehallBase      = "https://ehall2.njust.edu.cn"
	yjsBase        = "https://yjs.njust.edu.cn"
	yjsStudentBase = yjsBase + "/Gstudent/"
	yjsServiceID   = "854314156332171264"
)

type GraduateStat struct {
	Name     string  `json:"name"`
	Required float64 `json:"required"`
	Earned   float64 `json:"earned"`
	Planned  float64 `json:"planned"`
}

type GraduateTable struct {
	Stats     []GraduateStat `json:"stats"`
	Rows      [][]string     `json:"rows"`
	Semesters []string       `json:"semesters"`
}

var (
	yjsSemesterRE = regexp.MustCompile(`\d{4}-\d{4}[^\s<【】]{0,6}?学期`)
	yjsCourseRE   = regexp.MustCompile(`^\s*(.+?)\s*(\d+班)?\s*[｛{]([^［\[]+?)\s*[［\[]教师[:：](.+?)\s*[,，]\s*地点[:：]([^\]］]+)[\]］]\s*[｝}]`)
	yjsStatRE     = regexp.MustCompile(`(总学分|必修课|选修课|必修环节|学位课)\s*【培养方案要求最低[:：]\s*([\d.]+)\s*已修[:：]\s*([\d.]+)\s*培养计划制定[:：]\s*([\d.]+)】`)
	yjsMenuRE     = func(name string) *regexp.Regexp {
		return regexp.MustCompile(`name:\s*['"]` + regexp.QuoteMeta(name) + `['"][^}]{0,240}?url:\s*['"]([^'"]+)['"]`)
	}
)

func (c *Client) identifyEHall(ctx context.Context) error {
	resp, err := c.request(ctx, http.MethodGet, ehallBase+"/getLoginUser", nil)
	if err != nil {
		return err
	}
	raw, err := readResponse(resp)
	if err != nil {
		return err
	}
	var payload any
	if json.Unmarshal(raw, &payload) != nil {
		return fmt.Errorf("服务大厅用户信息返回异常")
	}
	find := func(keys ...string) string {
		wanted := map[string]bool{}
		for _, key := range keys {
			wanted[strings.ToLower(key)] = true
		}
		var walk func(any) string
		walk = func(value any) string {
			switch current := value.(type) {
			case map[string]any:
				for key, item := range current {
					if wanted[strings.ToLower(key)] {
						if text := strings.TrimSpace(fmt.Sprint(item)); text != "" {
							return text
						}
					}
				}
				for _, item := range current {
					if text := walk(item); text != "" {
						return text
					}
				}
			case []any:
				for _, item := range current {
					if text := walk(item); text != "" {
						return text
					}
				}
			}
			return ""
		}
		return walk(payload)
	}
	if sid := find("userAccount", "userId", "userCode", "account"); regexp.MustCompile(`^\d{8,20}$`).MatchString(sid) {
		c.StudentID = sid
	}
	if name := find("userName", "name", "xm"); name != "" {
		c.StudentName = name
	}
	return nil
}

func (c *Client) finishGraduateSSO(ctx context.Context, method string) error {
	resp, err := c.request(ctx, http.MethodGet, ehallBase+"/serviceShow?isMobile=0&serviceId="+yjsServiceID, nil)
	if err != nil {
		return fmt.Errorf("访问研究生系统入口: %w", err)
	}
	raw, err := readResponse(resp)
	if err != nil {
		return err
	}
	var payload map[string]any
	if err = json.Unmarshal(raw, &payload); err != nil {
		return fmt.Errorf("服务大厅返回异常")
	}
	data, _ := payload["data"].(map[string]any)
	serviceURL := strings.TrimSpace(fmt.Sprint(data["serviceUrl"]))
	if serviceURL == "<nil>" {
		serviceURL = ""
	}
	if serviceURL == "" {
		if grants, ok := data["grantData"].([]any); ok && len(grants) > 0 {
			if first, ok := grants[0].(map[string]any); ok {
				serviceURL = strings.TrimSpace(fmt.Sprint(first["serviceUrl"]))
			}
		}
	}
	if serviceURL == "" {
		return fmt.Errorf("服务大厅未返回研究生系统入口")
	}
	home, err := c.request(ctx, http.MethodGet, serviceURL, nil)
	if err != nil {
		return err
	}
	homeRaw, err := readResponse(home)
	if err != nil {
		return err
	}
	if !strings.Contains(home.Request.URL.String(), "Gstudent") && strings.Contains(string(homeRaw), "登录窗口") {
		return fmt.Errorf("研究生系统未接受服务票据")
	}
	_ = c.identifyEHall(ctx)
	c.AccountType = "graduate"
	c.LoginMethod = method
	return nil
}

func (c *Client) validateGraduate(ctx context.Context) error {
	resp, err := c.request(ctx, http.MethodGet, yjsStudentBase+"Default.aspx", nil)
	if err != nil {
		return err
	}
	raw, err := readResponse(resp)
	if err != nil {
		return err
	}
	if strings.Contains(string(raw), "登录窗口") && !strings.Contains(resp.Request.URL.String(), "Gstudent") {
		return ErrSessionExpired
	}
	c.AccountType = "graduate"
	return nil
}

func (c *Client) graduateMenuURL(ctx context.Context, name string) (string, error) {
	if c.yjsMenuHTML == "" {
		resp, err := c.request(ctx, http.MethodGet, yjsStudentBase+"LeftMenu.aspx", nil)
		if err != nil {
			return "", err
		}
		raw, err := readResponse(resp)
		if err != nil {
			return "", err
		}
		if strings.Contains(string(raw), "登录窗口") && !strings.Contains(resp.Request.URL.String(), "Gstudent") {
			return "", ErrSessionExpired
		}
		c.yjsMenuHTML = string(raw)
	}
	match := yjsMenuRE(name).FindStringSubmatch(c.yjsMenuHTML)
	if len(match) < 2 {
		return "", fmt.Errorf("研究生系统菜单里没有“%s”", name)
	}
	base, _ := url.Parse(yjsStudentBase)
	target, err := url.Parse(match[1])
	if err != nil {
		return "", err
	}
	return base.ResolveReference(target).String(), nil
}

func (c *Client) graduatePage(ctx context.Context, menu string) ([]byte, error) {
	target, err := c.graduateMenuURL(ctx, menu)
	if err != nil {
		return nil, err
	}
	resp, err := c.request(ctx, http.MethodGet, target, nil)
	if err != nil {
		return nil, err
	}
	raw, err := readResponse(resp)
	if err != nil {
		return nil, err
	}
	if strings.Contains(string(raw), "登录窗口") && !strings.Contains(resp.Request.URL.String(), "Gstudent") {
		return nil, ErrSessionExpired
	}
	return raw, nil
}

func normalizeYJSWeeks(raw string) string {
	replacer := strings.NewReplacer("周", "", "、", ",", "，", ",", "－", "-", "—", "-", "~", "-", "～", "-")
	parts := strings.Split(replacer.Replace(raw), ",")
	out := parts[:0]
	for _, part := range parts {
		if part = strings.TrimSpace(part); part != "" {
			out = append(out, part)
		}
	}
	return strings.Join(out, ",")
}

func splitCellLines(selection *goquery.Selection) []string {
	var text strings.Builder
	var walk func(*html.Node)
	walk = func(node *html.Node) {
		if node.Type == html.TextNode {
			text.WriteString(node.Data)
			return
		}
		if node.Type == html.ElementNode && node.Data == "br" {
			text.WriteByte('\n')
			return
		}
		block := node.Type == html.ElementNode && (node.Data == "div" || node.Data == "p" || node.Data == "li")
		if block && text.Len() > 0 {
			text.WriteByte('\n')
		}
		for child := node.FirstChild; child != nil; child = child.NextSibling {
			walk(child)
		}
		if block {
			text.WriteByte('\n')
		}
	}
	for _, node := range selection.Nodes {
		for child := node.FirstChild; child != nil; child = child.NextSibling {
			walk(child)
		}
	}
	parts := strings.Split(strings.ReplaceAll(text.String(), "\u00a0", " "), "\n")
	lines := make([]string, 0, len(parts))
	for _, part := range parts {
		if part = strings.TrimSpace(part); part != "" {
			lines = append(lines, part)
		}
	}
	return lines
}

func ParseGraduateCourses(raw []byte) ([]store.Course, []string, error) {
	doc, err := goquery.NewDocumentFromReader(strings.NewReader(string(raw)))
	if err != nil {
		return nil, nil, err
	}
	table := doc.Find("table").FilterFunction(func(_ int, selection *goquery.Selection) bool {
		id, _ := selection.Attr("id")
		return strings.HasSuffix(id, "dgData")
	}).First()
	semesters := uniqueMatches(yjsSemesterRE.FindAllString(string(raw), -1))
	if table.Length() == 0 {
		return []store.Course{}, semesters, nil
	}
	rows := table.Find("tr")
	if rows.Length() == 0 {
		return []store.Course{}, semesters, nil
	}
	var dayColumns []int
	column := 0
	rows.First().Find("th,td").Each(func(_ int, cell *goquery.Selection) {
		if strings.HasPrefix(strings.TrimSpace(cell.Text()), "星期") {
			dayColumns = append(dayColumns, column)
		}
		column += positiveAttr(cell, "colspan")
	})
	occupied := map[int]int{}
	var courses []store.Course
	rows.Slice(1, goquery.ToEnd).Each(func(_ int, row *goquery.Selection) {
		for key, value := range occupied {
			if value <= 1 {
				delete(occupied, key)
			} else {
				occupied[key] = value - 1
			}
		}
		type cellValue struct {
			text string
			span int
		}
		cells := map[int]cellValue{}
		col := 0
		row.Find("td,th").Each(func(_ int, cell *goquery.Selection) {
			for occupied[col] > 0 {
				col++
			}
			rs, cs := positiveAttr(cell, "rowspan"), positiveAttr(cell, "colspan")
			cells[col] = cellValue{strings.Join(splitCellLines(cell), "\n"), rs}
			if rs > 1 {
				for offset := 0; offset < cs; offset++ {
					occupied[col+offset] = rs
				}
			}
			col += cs
		})
		sectionRaw := strings.TrimSpace(cells[1].text)
		section, err := strconv.Atoi(sectionRaw)
		if err != nil {
			return
		}
		for dayIndex, dayColumn := range dayColumns {
			cell, ok := cells[dayColumn]
			if !ok {
				continue
			}
			for _, piece := range strings.Split(cell.text, "\n") {
				match := yjsCourseRE.FindStringSubmatch(piece)
				if len(match) < 6 {
					continue
				}
				courses = append(courses, store.Course{Name: strings.TrimSpace(match[1]), Teacher: strings.TrimSpace(match[4]), Classroom: strings.TrimSpace(match[5]), Day: dayIndex + 1, Start: section, End: section + cell.span - 1, Weeks: normalizeYJSWeeks(match[3])})
			}
		}
	})
	if courses == nil {
		courses = []store.Course{}
	}
	return courses, semesters, nil
}

func ParseGraduateTable(raw []byte) (GraduateTable, error) {
	doc, err := goquery.NewDocumentFromReader(strings.NewReader(string(raw)))
	if err != nil {
		return GraduateTable{}, err
	}
	plain := strings.Join(strings.Fields(doc.Text()), " ")
	result := GraduateTable{Stats: []GraduateStat{}, Rows: [][]string{}, Semesters: uniqueMatches(yjsSemesterRE.FindAllString(string(raw), -1))}
	seen := map[string]bool{}
	for _, match := range yjsStatRE.FindAllStringSubmatch(plain, -1) {
		if len(match) < 5 || seen[match[1]] {
			continue
		}
		seen[match[1]] = true
		required, _ := strconv.ParseFloat(match[2], 64)
		earned, _ := strconv.ParseFloat(match[3], 64)
		planned, _ := strconv.ParseFloat(match[4], 64)
		result.Stats = append(result.Stats, GraduateStat{match[1], required, earned, planned})
	}
	doc.Find("table").FilterFunction(func(_ int, selection *goquery.Selection) bool {
		id, _ := selection.Attr("id")
		return strings.HasSuffix(id, "dgData")
	}).First().Find("tr").Each(func(_ int, row *goquery.Selection) {
		var cells []string
		row.Find("td,th").Each(func(_ int, cell *goquery.Selection) { cells = append(cells, strings.TrimSpace(cell.Text())) })
		if len(cells) > 0 {
			result.Rows = append(result.Rows, cells)
		}
	})
	return result, nil
}

func (c *Client) GraduateCourses(ctx context.Context) ([]store.Course, []string, error) {
	raw, err := c.graduatePage(ctx, "学期课表信息查询")
	if err != nil {
		return nil, nil, err
	}
	return ParseGraduateCourses(raw)
}

func (c *Client) GraduateGrades(ctx context.Context) (GraduateTable, error) {
	raw, err := c.graduatePage(ctx, "课程成绩信息查询")
	if err != nil {
		return GraduateTable{}, err
	}
	return ParseGraduateTable(raw)
}

func (c *Client) GraduateExams(ctx context.Context) (GraduateTable, error) {
	raw, err := c.graduatePage(ctx, "学期考试信息查询")
	if err != nil {
		return GraduateTable{}, err
	}
	return ParseGraduateTable(raw)
}

func positiveAttr(selection *goquery.Selection, name string) int {
	value, _ := strconv.Atoi(strings.TrimSpace(attr(selection, name)))
	if value < 1 {
		return 1
	}
	return value
}

func attr(selection *goquery.Selection, name string) string {
	value, _ := selection.Attr(name)
	return value
}

func uniqueMatches(values []string) []string {
	seen := map[string]bool{}
	out := make([]string, 0, len(values))
	for _, value := range values {
		if !seen[value] {
			seen[value] = true
			out = append(out, value)
		}
	}
	return out
}
