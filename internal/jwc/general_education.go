package jwc

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/PuerkitoBio/goquery"
	"github.com/resetinging/njust-schedule/internal/store"
)

const (
	generalEducationFindURL   = JWBase + "/view/xkgl/txKcdgFind.jsp"
	generalEducationQueryURL  = JWBase + "/mtxk/txkKcdgQuery"
	generalEducationDetailURL = JWBase + "/view/pyfa/kcdg_View.jsp"
	generalEducationMaxPages  = 100
)

var (
	generalEducationPagePattern  = regexp.MustCompile(`共\s*(\d+)\s*页`)
	generalEducationLinkPattern  = regexp.MustCompile(`kcdgView\(['"]([^'"]+)['"]\)`)
	generalEducationKnownFields  = []string{"课程编号", "课程名称(中)", "授课语种", "课程名称(英)", "开课单位", "课程类别", "课程负责人(执笔人)", "审核人", "学分", "学时", "是否为术科课", "考核方式"}
	generalEducationTableHeaders = []string{"序号", "开课学期", "课程编号", "课程名称", "开课单位", "学分", "总学时", "考核方式", "课程属性", "操作列"}
)

func (c *Client) GeneralEducationCatalog(ctx context.Context, semester string) (store.GeneralEducationCatalog, error) {
	pageResp, err := c.request(ctx, http.MethodGet, generalEducationFindURL, nil)
	if err != nil {
		return store.GeneralEducationCatalog{}, err
	}
	pageRaw, err := readResponse(pageResp)
	if err != nil {
		return store.GeneralEducationCatalog{}, err
	}
	if c.isLoginPage(pageResp, pageRaw) {
		return store.GeneralEducationCatalog{}, ErrSessionExpired
	}
	pageDoc, err := parseDocument(pageRaw)
	if err != nil {
		return store.GeneralEducationCatalog{}, fmt.Errorf("解析通识选修课大纲查询页: %w", err)
	}
	form := pageDoc.Find("form#Form").First()
	if form.Length() == 0 {
		form = pageDoc.Find("form").FilterFunction(func(_ int, value *goquery.Selection) bool {
			return value.Find("select[name='xnxq01id']").Length() > 0
		}).First()
	}
	if form.Length() == 0 {
		return store.GeneralEducationCatalog{}, fmt.Errorf("通识选修课大纲查询未找到表单")
	}
	parsed := parseForm(form)
	if parsed.Method != strings.ToLower(http.MethodPost) {
		return store.GeneralEducationCatalog{}, fmt.Errorf("通识选修课大纲查询提交方式异常: %s", parsed.Method)
	}
	values := parsed.Values
	values.Set("xnxq01id", strings.TrimSpace(semester))
	values.Set("pageIndex", "1")

	seen := map[string]bool{}
	courses := make([]store.GeneralEducationCourse, 0, 260)
	totalPages := 1
	lastPage := 0
	for page := 1; page <= generalEducationMaxPages && page <= totalPages; page++ {
		values.Set("pageIndex", strconv.Itoa(page))
		resp, err := c.request(ctx, http.MethodPost, generalEducationQueryURL, values)
		if err != nil {
			return store.GeneralEducationCatalog{}, err
		}
		raw, err := readResponse(resp)
		if err != nil {
			return store.GeneralEducationCatalog{}, err
		}
		if c.isLoginPage(resp, raw) {
			return store.GeneralEducationCatalog{}, ErrSessionExpired
		}
		doc, err := parseDocument(raw)
		if err != nil {
			return store.GeneralEducationCatalog{}, fmt.Errorf("解析通识选修课大纲第 %d 页: %w", page, err)
		}
		if page == 1 {
			totalPages, err = generalEducationTotalPages(doc)
			if err != nil {
				return store.GeneralEducationCatalog{}, err
			}
		}
		pageCourses, err := parseGeneralEducationCatalogPage(doc, semester)
		if err != nil {
			return store.GeneralEducationCatalog{}, fmt.Errorf("解析通识选修课大纲第 %d 页: %w", page, err)
		}
		for _, value := range pageCourses {
			if seen[value.CourseCode] {
				continue
			}
			seen[value.CourseCode] = true
			courses = append(courses, value)
		}
		lastPage = page
	}
	if lastPage != totalPages || len(courses) == 0 {
		return store.GeneralEducationCatalog{}, fmt.Errorf("通识选修课大纲分页不完整: 已完成 %d/%d 页，解析 %d 门", lastPage, totalPages, len(courses))
	}
	return store.GeneralEducationCatalog{Courses: courses, Pages: totalPages}, nil
}

func generalEducationTotalPages(doc *goquery.Document) (int, error) {
	match := generalEducationPagePattern.FindStringSubmatch(doc.Text())
	if len(match) != 2 {
		return 1, nil
	}
	pages, err := strconv.Atoi(match[1])
	if err != nil || pages < 1 {
		return 0, fmt.Errorf("通识选修课大纲总页数无效: %q", match[1])
	}
	if pages > generalEducationMaxPages {
		return 0, fmt.Errorf("通识选修课大纲页数超过安全上限: %d", pages)
	}
	return pages, nil
}

func parseGeneralEducationCatalogPage(doc *goquery.Document, semester string) ([]store.GeneralEducationCourse, error) {
	table := doc.Find("table#dataList").First()
	if table.Length() == 0 {
		return nil, fmt.Errorf("未找到 dataList 表格")
	}
	var courses []store.GeneralEducationCourse
	table.Find("tr").Each(func(index int, row *goquery.Selection) {
		if index == 0 {
			return
		}
		cells := selectionTexts(row.Find("td"))
		if len(cells) < 9 || strings.TrimSpace(cells[2]) == "" || strings.TrimSpace(cells[3]) == "" {
			return
		}
		if len(cells) >= len(generalEducationTableHeaders) && strings.TrimSpace(cells[0]) == generalEducationTableHeaders[0] {
			return
		}
		syllabusID := ""
		row.Find("a[onclick]").EachWithBreak(func(_ int, link *goquery.Selection) bool {
			onclick, _ := link.Attr("onclick")
			match := generalEducationLinkPattern.FindStringSubmatch(onclick)
			if len(match) == 2 {
				syllabusID = strings.TrimSpace(match[1])
				return false
			}
			return true
		})
		courses = append(courses, store.GeneralEducationCourse{
			Semester: semester, CourseCode: strings.TrimSpace(cells[2]),
			CourseName: strings.TrimSpace(cells[3]), Department: at(cells, 4),
			Credit: at(cells, 5), Hours: at(cells, 6), Assessment: at(cells, 7),
			Attribute: at(cells, 8), SyllabusID: syllabusID, HasSyllabus: syllabusID != "",
		})
	})
	if len(courses) == 0 {
		return nil, fmt.Errorf("课程目录为空")
	}
	return courses, nil
}

func (c *Client) GeneralEducationSyllabus(ctx context.Context, syllabusID string) (store.GeneralEducationSyllabus, error) {
	syllabusID = strings.TrimSpace(syllabusID)
	if syllabusID == "" {
		return store.GeneralEducationSyllabus{}, fmt.Errorf("课程大纲编号为空")
	}
	target := generalEducationDetailURL + "?jx02id=" + url.QueryEscape(syllabusID)
	resp, err := c.request(ctx, http.MethodGet, target, nil)
	if err != nil {
		return store.GeneralEducationSyllabus{}, err
	}
	raw, err := readResponse(resp)
	if err != nil {
		return store.GeneralEducationSyllabus{}, err
	}
	if c.isLoginPage(resp, raw) {
		return store.GeneralEducationSyllabus{}, ErrSessionExpired
	}
	doc, err := parseDocument(raw)
	if err != nil {
		return store.GeneralEducationSyllabus{}, fmt.Errorf("解析课程大纲: %w", err)
	}
	value, err := parseGeneralEducationSyllabus(doc, syllabusID)
	if err != nil {
		return store.GeneralEducationSyllabus{}, err
	}
	value.FetchedAt = time.Now().Unix()
	return value, nil
}

func parseGeneralEducationSyllabus(doc *goquery.Document, syllabusID string) (store.GeneralEducationSyllabus, error) {
	table := doc.Find("table#dataList").First()
	if table.Length() == 0 {
		return store.GeneralEducationSyllabus{}, fmt.Errorf("课程大纲未找到 dataList 表格")
	}
	value := store.GeneralEducationSyllabus{
		SyllabusID: syllabusID,
		Title:      strings.TrimSpace(doc.Find("title").First().Text()),
		Fields:     map[string]string{},
	}
	known := map[string]bool{}
	for _, label := range generalEducationKnownFields {
		known[label] = true
	}
	table.Find("tr").Each(func(_ int, row *goquery.Selection) {
		rawCells := row.Find("td,th")
		cells := make([]string, 0, rawCells.Length())
		rawCells.Each(func(_ int, cell *goquery.Selection) {
			cells = append(cells, strings.TrimSpace(cell.Text()))
		})
		filtered := make([]string, 0, len(cells))
		for _, cell := range cells {
			if cell != "" {
				filtered = append(filtered, strings.Join(strings.Fields(cell), " "))
			}
		}
		if len(filtered) > 0 {
			value.Rows = append(value.Rows, filtered)
		}
		for i := 0; i+1 < len(cells); i++ {
			label := strings.Join(strings.Fields(cells[i]), " ")
			if !known[label] {
				continue
			}
			fieldValue := strings.Join(strings.Fields(cells[i+1]), " ")
			if fieldValue != "" {
				value.Fields[label] = fieldValue
			}
		}
	})
	doc.Find("input[name],textarea[name]").Each(func(_ int, input *goquery.Selection) {
		name := strings.TrimSpace(input.AttrOr("name", ""))
		fieldValue := strings.TrimSpace(input.Text())
		if input.Is("input") {
			fieldValue = strings.TrimSpace(input.AttrOr("value", ""))
		}
		if name != "" && fieldValue != "" {
			value.Fields[name] = fieldValue
		}
	})
	value.RawText = strings.Join(strings.Fields(table.Text()), " ")
	if value.RawText == "" {
		return store.GeneralEducationSyllabus{}, fmt.Errorf("课程大纲内容为空")
	}
	return value, nil
}
