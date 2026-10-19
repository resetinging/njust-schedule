package jwc

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"path"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/PuerkitoBio/goquery"
)

const evalOrigin = "http://202.119.81.112:9080"

var openWindowPattern = regexp.MustCompile(`openWindow\(['\"]([^'\"]+)['\"]`)
var courseNamePattern = regexp.MustCompile(`课程名称[：:]\s*(.+?)(?:\s{2,}|\x{a0}|$)`)

type EvalCourse struct {
	Seq       string `json:"seq"`
	Code      string `json:"code"`
	Name      string `json:"name"`
	Teacher   string `json:"teacher"`
	Score     string `json:"score"`
	Evaluated bool   `json:"evaluated"`
	Submitted bool   `json:"submitted"`
	EvalURL   string `json:"eval_url"`
}

type EvalOption struct {
	Name    string `json:"name"`
	Value   string `json:"value"`
	Label   string `json:"label"`
	Score   string `json:"score"`
	Checked bool   `json:"checked"`
}

type EvalIndicator struct {
	Seq     string       `json:"seq"`
	Label   string       `json:"label"`
	Options []EvalOption `json:"options"`
}

type ProxyResponse struct {
	Status      int
	ContentType string
	Body        []byte
}

func SafeJWPath(raw string) (string, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" || strings.Contains(raw, "\\") {
		return "", errors.New("非法教务路径")
	}
	u, err := url.Parse(raw)
	if err != nil || u.IsAbs() || u.Host != "" || strings.HasPrefix(raw, "//") {
		return "", errors.New("只允许教务站内相对路径")
	}
	decoded := u.EscapedPath()
	fullyDecoded := false
	for i := 0; i < 8; i++ {
		next, decodeErr := url.PathUnescape(decoded)
		if decodeErr != nil {
			return "", errors.New("非法教务路径编码")
		}
		if strings.ContainsAny(next, `\?#`) || strings.IndexFunc(next, func(r rune) bool { return r < 0x20 || r == 0x7f }) >= 0 {
			return "", errors.New("非法教务路径字符")
		}
		if next == decoded {
			fullyDecoded = true
			break
		}
		decoded = next
	}
	if !fullyDecoded {
		return "", errors.New("教务路径编码层级过深")
	}
	for _, segment := range strings.Split(decoded, "/") {
		if segment == ".." || segment == "." {
			return "", errors.New("路径穿越被拒绝")
		}
	}
	normalized := path.Clean("/" + strings.TrimLeft(decoded, "/"))
	if !strings.HasPrefix(normalized, "/njlgdx/") {
		return "", errors.New("只允许 /njlgdx/ 下的教务路径")
	}
	if u.RawQuery != "" {
		normalized += "?" + u.RawQuery
	}
	return normalized, nil
}

func evalHeaders(req *http.Request) {
	req.Header.Set("Referer", evalOrigin+"/njlgdx/xspj/xspj_find.do")
	req.Header.Set("Origin", evalOrigin)
	req.Header.Set("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
	req.Header.Set("Accept-Language", "zh-CN,zh;q=0.9")
	req.Header.Set("Cache-Control", "max-age=0")
}

func (c *Client) warmEvaluation(ctx context.Context) error {
	if time.Since(c.evalWarmAt) < time.Minute {
		return nil
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, evalOrigin+"/njlgdx/xspj/xspj_find.do", nil)
	if err != nil {
		return err
	}
	evalHeaders(req)
	resp, err := c.evalHTTP().Do(req)
	if err != nil {
		return err
	}
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 1<<20))
	_ = resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 400 {
		return fmt.Errorf("评教预热返回 HTTP %d", resp.StatusCode)
	}
	c.evalWarmAt = time.Now()
	return nil
}

func (c *Client) evalHTTP() *http.Client {
	return &http.Client{
		Jar: c.HTTP.Jar, Timeout: 20 * time.Second, Transport: c.HTTP.Transport,
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			if len(via) >= 5 || req.URL.Scheme != "http" || req.URL.Host != "202.119.81.112:9080" {
				return errors.New("教务重定向目标被拒绝")
			}
			_, err := SafeJWPath(req.URL.RequestURI())
			return err
		},
	}
}

func (c *Client) Proxy(ctx context.Context, method, rawPath, rawQuery string, body io.Reader, contentType string) (ProxyResponse, error) {
	safePath, err := SafeJWPath(rawPath)
	if err != nil {
		return ProxyResponse{}, err
	}
	if rawQuery != "" {
		u, _ := url.Parse(safePath)
		query, parseErr := url.ParseQuery(strings.TrimPrefix(rawQuery, "?"))
		if parseErr != nil {
			return ProxyResponse{}, errors.New("查询参数格式错误")
		}
		values := u.Query()
		for key, items := range query {
			for _, item := range items {
				values.Add(key, item)
			}
		}
		u.RawQuery = values.Encode()
		safePath = u.RequestURI()
	}
	if err = c.warmEvaluation(ctx); err != nil {
		return ProxyResponse{}, err
	}
	req, err := http.NewRequestWithContext(ctx, method, evalOrigin+safePath, body)
	if err != nil {
		return ProxyResponse{}, err
	}
	evalHeaders(req)
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	resp, err := c.evalHTTP().Do(req)
	if err != nil {
		return ProxyResponse{}, err
	}
	raw, err := readResponse(resp)
	if err != nil {
		return ProxyResponse{}, err
	}
	text := string(raw)
	if strings.Contains(text, "非法访问") || strings.Contains(text, "非法操作") {
		return ProxyResponse{}, &HTTPStatusError{Status: http.StatusForbidden, Message: "教务系统拒绝了请求"}
	}
	return ProxyResponse{Status: resp.StatusCode, ContentType: resp.Header.Get("Content-Type"), Body: raw}, nil
}

type HTTPStatusError struct {
	Status  int
	Message string
}

func (e *HTTPStatusError) Error() string { return e.Message }

func ParseEvalCourses(raw []byte) (string, []EvalCourse, map[string]string, error) {
	doc, err := goquery.NewDocumentFromReader(bytes.NewReader(raw))
	if err != nil {
		return "", nil, nil, err
	}
	title := cleanText(doc.Find(".Nsb_r_title").First().Text())
	if title == "" {
		title = "评教课程"
	}
	hidden := hiddenInputs(doc.Find("form#Form1").First())
	var courses []EvalCourse
	doc.Find("table#dataList tr").Each(func(index int, row *goquery.Selection) {
		if index == 0 {
			return
		}
		cells := row.Find("td")
		if cells.Length() < 8 {
			return
		}
		href, _ := cells.Eq(7).Find("a").First().Attr("href")
		evalURL := ""
		if match := openWindowPattern.FindStringSubmatch(href); len(match) == 2 {
			evalURL = match[1]
		}
		courses = append(courses, EvalCourse{Seq: cleanText(cells.Eq(0).Text()), Code: cleanText(cells.Eq(1).Text()), Name: cleanText(cells.Eq(2).Text()), Teacher: cleanText(cells.Eq(3).Text()), Score: cleanText(cells.Eq(4).Text()), Evaluated: cleanText(cells.Eq(5).Text()) == "是", Submitted: cleanText(cells.Eq(6).Text()) == "是", EvalURL: evalURL})
	})
	if len(courses) == 0 {
		return title, nil, hidden, errors.New("未找到课程列表")
	}
	return title, courses, hidden, nil
}

func ParseEvalForm(raw []byte) (string, map[string]string, []EvalIndicator, string, error) {
	doc, err := goquery.NewDocumentFromReader(bytes.NewReader(raw))
	if err != nil {
		return "", nil, nil, "", err
	}
	courseName := ""
	if match := courseNamePattern.FindStringSubmatch(doc.Find("th.Nsb_r_list_thb").First().Text()); len(match) == 2 {
		courseName = strings.TrimSpace(match[1])
	}
	form := doc.Find("form#Form1").First()
	hidden := hiddenInputs(form)
	action, _ := form.Attr("action")
	var indicators []EvalIndicator
	doc.Find("#table1 tr").Each(func(_ int, row *goquery.Selection) {
		cells := row.Find("td")
		if cells.Length() < 2 {
			return
		}
		label := cleanText(cells.Eq(0).Text())
		if label == "" || strings.Contains(label, "评价指标") {
			return
		}
		seq, _ := cells.Eq(0).Find(`input[name="pj06xh"]`).First().Attr("value")
		scores := map[string]string{}
		cells.Eq(1).Find(`input[type="hidden"]`).Each(func(_ int, input *goquery.Selection) {
			name, _ := input.Attr("name")
			value, _ := input.Attr("value")
			if strings.HasPrefix(name, "pj0601fz_") {
				hidden[name] = value
				parts := strings.Split(name, "_")
				scores[parts[len(parts)-1]] = value
			}
		})
		indicator := EvalIndicator{Seq: seq, Label: label}
		cells.Eq(1).Find(`input[type="radio"]`).Each(func(_ int, radio *goquery.Selection) {
			name, _ := radio.Attr("name")
			value, _ := radio.Attr("value")
			_, checked := radio.Attr("checked")
			optionLabel := cleanText(radio.Parent().Text())
			indicator.Options = append(indicator.Options, EvalOption{Name: name, Value: value, Label: optionLabel, Score: scores[value], Checked: checked})
		})
		indicators = append(indicators, indicator)
	})
	if courseName == "" && len(indicators) == 0 {
		return "", hidden, nil, action, errors.New("未找到评价表单")
	}
	return courseName, hidden, indicators, action, nil
}

func hiddenInputs(form *goquery.Selection) map[string]string {
	values := map[string]string{}
	form.Find(`input[type="hidden"]`).Each(func(_ int, input *goquery.Selection) {
		name, _ := input.Attr("name")
		value, _ := input.Attr("value")
		if name != "" {
			values[name] = value
		}
	})
	return values
}

func cleanText(value string) string { return strings.Join(strings.Fields(value), " ") }

func OrderedEvalForm(values map[string]any, submitType string) string {
	formLevel := map[string]string{}
	groups := map[int]map[string]string{}
	for key, raw := range values {
		value := fmt.Sprint(raw)
		switch {
		case strings.HasPrefix(key, "pj0601fz_"):
			parts := strings.SplitN(key, "_", 3)
			seq, err := strconv.Atoi(parts[1])
			if err == nil {
				if groups[seq] == nil {
					groups[seq] = map[string]string{}
				}
				groups[seq][key] = value
			}
		case strings.HasPrefix(key, "pj0601id_"):
			seq, err := strconv.Atoi(strings.TrimPrefix(key, "pj0601id_"))
			if err == nil {
				if groups[seq] == nil {
					groups[seq] = map[string]string{}
				}
				groups[seq][key] = value
			}
		case key != "pj06xh" && key != "issubmit":
			formLevel[key] = value
		}
	}
	keys := sortedKeys(formLevel)
	seqs := make([]int, 0, len(groups))
	for seq := range groups {
		seqs = append(seqs, seq)
	}
	sort.Ints(seqs)
	pairs := make([]string, 0, len(values)+len(seqs)+1)
	appendPair := func(key, value string) { pairs = append(pairs, url.QueryEscape(key)+"="+url.QueryEscape(value)) }
	for _, key := range keys {
		appendPair(key, formLevel[key])
	}
	for _, seq := range seqs {
		appendPair("pj06xh", strconv.Itoa(seq))
		for _, key := range sortedKeys(groups[seq]) {
			appendPair(key, groups[seq][key])
		}
	}
	appendPair("issubmit", submitType)
	return strings.Join(pairs, "&")
}

func sortedKeys(values map[string]string) []string {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}
