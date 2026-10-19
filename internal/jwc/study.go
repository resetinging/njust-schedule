package jwc

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/PuerkitoBio/goquery"
	"github.com/resetinging/njust-schedule/internal/store"
)

const (
	calendarURL  = JWBase + "/jxzl/jxzl_query?Ves632DSdyV=NEW_XSD_WDZM"
	programmeURL = JWBase + "/pyfa/pyfa_query"
	profileURL   = JWBase + "/grxx/xsxx?Ves632DSdyV=NEW_XSD_XJCJ"
	evalURL      = JWBase + "/xspj/xspj_find.do?Ves632DSdyV=NEW_XSD_JXPJ"
)

func (c *Client) Calendar(ctx context.Context, semester string) (map[string]any, error) {
	form := url.Values{}
	if semester != "" {
		form.Set("xnxq01id", semester)
	}
	resp, err := c.request(ctx, http.MethodPost, calendarURL, form)
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
	type weekRow struct {
		Week   int      `json:"week"`
		Monday string   `json:"monday"`
		Sunday string   `json:"sunday"`
		Days   []string `json:"days"`
		Note   string   `json:"note"`
	}
	var weeks []weekRow
	doc.Find("tr").Each(func(_ int, row *goquery.Selection) {
		cells := row.Find("td")
		if cells.Length() == 0 {
			return
		}
		week, _ := strconv.Atoi(strings.TrimSpace(cells.First().Text()))
		if week <= 0 {
			return
		}
		var days []string
		cells.Each(func(_ int, cell *goquery.Selection) {
			if title, ok := cell.Attr("title"); ok {
				if date := chineseDate(title); date != "" {
					days = append(days, date)
				}
			}
		})
		if len(days) < 7 {
			return
		}
		note := ""
		last := cells.Last()
		if _, ok := last.Attr("title"); !ok {
			note = strings.Join(strings.Fields(last.Text()), " ")
		}
		weeks = append(weeks, weekRow{week, days[0], days[6], days[:7], note})
	})
	if len(weeks) == 0 {
		return nil, fmt.Errorf("教学周历解析为空")
	}
	sort.Slice(weeks, func(i, j int) bool { return weeks[i].Week < weeks[j].Week })
	selected, _ := doc.Find("select[name='xnxq01id'] option[selected]").First().Attr("value")
	if selected == "" {
		selected = semester
	}
	return map[string]any{"semester": selected, "first_monday": weeks[0].Monday, "weeks": weeks, "count": len(weeks)}, nil
}

var cnDate = regexp.MustCompile(`(\d{4})年(\d{1,2})月(\d{1,2})`)

func chineseDate(raw string) string {
	m := cnDate.FindStringSubmatch(raw)
	if len(m) != 4 {
		return ""
	}
	month, _ := strconv.Atoi(m[2])
	day, _ := strconv.Atoi(m[3])
	return fmt.Sprintf("%s-%02d-%02d", m[1], month, day)
}

func (c *Client) Programme(ctx context.Context) (map[string]any, error) {
	seen := map[string]bool{}
	var courses []map[string]any
	pages := 0
	totalPages := 1
	for page := 1; page <= 12 && page <= totalPages; page++ {
		resp, err := c.request(ctx, http.MethodPost, programmeURL, url.Values{"kctxs": {""}, "xnxq": {""}, "kcsx": {""}, "pageIndex": {strconv.Itoa(page)}})
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
		if page == 1 {
			if m := regexp.MustCompile(`共\s*(\d+)\s*页`).FindStringSubmatch(doc.Text()); len(m) == 2 {
				totalPages, _ = strconv.Atoi(m[1])
			}
		}
		before := len(courses)
		doc.Find("tr").Each(func(_ int, row *goquery.Selection) {
			cells := selectionTexts(row.Find("td,th"))
			filtered := make([]string, 0, len(cells))
			for _, v := range cells {
				if v != "" {
					filtered = append(filtered, v)
				}
			}
			if len(filtered) < 9 {
				return
			}
			if _, err := strconv.Atoi(filtered[0]); err != nil {
				return
			}
			key := filtered[1] + "\x00" + filtered[2]
			if seen[key] {
				return
			}
			seen[key] = true
			isExam := ""
			if len(filtered) > 9 {
				isExam = filtered[9]
			}
			courses = append(courses, map[string]any{"semester": filtered[1], "code": filtered[2], "name": filtered[3], "dept": filtered[4], "credit": parseFloat(filtered[5]), "hours": parseFloat(filtered[6]), "exam_type": filtered[7], "attribute": filtered[8], "is_exam": isExam})
		})
		pages = page
		if page == 1 && len(courses) == before {
			return nil, fmt.Errorf("培养方案解析为空")
		}
	}
	return map[string]any{"courses": courses, "pages": pages, "count": len(courses)}, nil
}

func (c *Client) Profile(ctx context.Context) (map[string]any, error) {
	resp, err := c.request(ctx, http.MethodGet, profileURL, nil)
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
	table := doc.Find("table#xjkpTable").First()
	if table.Length() == 0 {
		table = doc.Selection
	}
	fields := map[string]string{}
	stopped := false
	table.Find("tr").EachWithBreak(func(_ int, row *goquery.Selection) bool {
		cells := selectionTexts(row.Find("td,th"))
		joined := strings.ReplaceAll(strings.Join(cells, ""), " ", "")
		for _, word := range []string{"学习及工作简历", "起始年月", "家庭情况", "家庭成员"} {
			if strings.Contains(joined, word) {
				stopped = true
				return false
			}
		}
		labeled := 0
		for _, cell := range cells {
			if strings.ContainsAny(cell, "：:") {
				labeled++
			}
		}
		if labeled >= 2 {
			for _, cell := range cells {
				parts := strings.FieldsFunc(cell, func(r rune) bool { return r == '：' || r == ':' })
				if len(parts) >= 2 && strings.TrimSpace(parts[0]) != "" && strings.TrimSpace(parts[1]) != "" {
					fields[strings.TrimSpace(parts[0])] = strings.TrimSpace(strings.Join(parts[1:], ":"))
				}
			}
		} else {
			for i := 0; i+1 < len(cells); i += 2 {
				if cells[i] != "" && cells[i+1] != "" {
					fields[cells[i]] = cells[i+1]
				}
			}
		}
		return true
	})
	_ = stopped
	if len(fields) == 0 {
		return nil, fmt.Errorf("学籍卡片解析为空")
	}
	base := map[string]string{"college": fields["院系"], "major": fields["专业"], "duration": fields["学制"], "class_name": fields["班级"], "student_id": fields["学号"]}
	result := map[string]any{"fields": fields, "base": base}
	if identity := c.ehallIdentity(ctx); len(identity) > 0 {
		result["identity"] = identity
	}
	return result, nil
}

func (c *Client) ehallIdentity(ctx context.Context) map[string]string {
	resp, err := c.request(ctx, http.MethodGet, "https://ehall2.njust.edu.cn/getLoginUser", nil)
	if err != nil {
		return nil
	}
	var payload struct {
		Data map[string]any `json:"data"`
	}
	if err = jsonNewDecoder(resp.Body).Decode(&payload); err != nil {
		_ = resp.Body.Close()
		return nil
	}
	_ = resp.Body.Close()
	out := map[string]string{"name": firstString(payload.Data, "userName"), "category": firstString(payload.Data, "categoryName"), "dept": firstString(payload.Data, "deptName")}
	if out["category"] == "" && out["dept"] == "" {
		return nil
	}
	return out
}

func (c *Client) Evaluations(ctx context.Context) ([]store.Evaluation, error) {
	resp, err := c.request(ctx, http.MethodGet, evalURL, nil)
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
	table := doc.Find("table.Nsb_r_list").First()
	if table.Length() == 0 {
		return nil, fmt.Errorf("评价页面未找到数据表格")
	}
	var out []store.Evaluation
	table.Find("tr").Each(func(i int, row *goquery.Selection) {
		if i == 0 {
			return
		}
		cells := selectionTexts(row.Find("td"))
		if len(cells) < 7 || at(cells, 3) == "" {
			return
		}
		var items []map[string]any
		row.Find("td").Eq(7).Find("a").Each(func(_ int, a *goquery.Selection) {
			href, _ := a.Attr("href")
			items = append(items, map[string]any{"name": strings.TrimSpace(a.Text()), "url": href})
		})
		out = append(out, store.Evaluation{Semester: at(cells, 1), Category: at(cells, 2), Batch: at(cells, 3), StartDate: at(cells, 4), EndDate: at(cells, 5), IsDone: at(cells, 6) == "是", Items: items})
	})
	return out, nil
}

// Tiny wrappers keep imports explicit while avoiding package-wide decoder state.
type jsonDecoder interface{ Decode(any) error }

func jsonNewDecoder(r io.Reader) jsonDecoder { return json.NewDecoder(r) }
