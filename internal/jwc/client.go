package jwc

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/PuerkitoBio/goquery"
	"github.com/resetinging/njust-schedule/internal/store"
)

const (
	maxResponseBody = 16 << 20
	SSOBase         = "https://ids.njust.edu.cn"
	SSOLoginURL     = "https://ids.njust.edu.cn/authserver/login?service=https%3A%2F%2Fehall2.njust.edu.cn%2Flogin"
	JWBase          = "https://bkjw.njust.edu.cn/njlgdx"
	JWSSOEntry      = JWBase + "/indexsso.jsp"
	mainURL         = JWBase + "/framework/main.jsp"
	appURL          = JWBase + "/app.do"
	scheduleURL     = JWBase + "/xskb/xskb_list.do?Ves632DSdyV=NEW_XSD_PYGL"
	examQueryURL    = JWBase + "/xsks/xsksap_query?Ves632DSdyV=NEW_XSD_KSBM"
	examListURL     = JWBase + "/xsks/xsksap_list"
	gradeQueryURL   = JWBase + "/kscj/cjcx_query?Ves632DSdyV=NEW_XSD_XJCJ"
	gradeListURL    = JWBase + "/kscj/cjcx_list"
	cetURL          = JWBase + "/kscj/djkscj_list"
)

var (
	ErrSessionExpired  = errors.New("会话已过期，请重新登录")
	ErrCaptchaRequired = errors.New("智慧理工要求验证码，请改用二维码登录")
)

type Client struct {
	HTTP          *http.Client
	StudentID     string
	StudentName   string
	AccountType   string
	LoginMethod   string
	LastError     string
	mu            sync.Mutex
	qrToken       string
	qrLT          string
	qrExecution   string
	qrLoginURL    string
	qrValues      url.Values
	qrImage       []byte
	evalWarmAt    time.Time
	yjsMenuHTML   string
	captchaSolver CaptchaSolver
}

type CaptchaSolver interface {
	Solve(ctx context.Context, image []byte) (string, error)
}

type parsedForm struct {
	Action  string
	Method  string
	Enctype string
	Values  url.Values
}

func New(cookies []store.Cookie) *Client {
	jar := newPersistentCookieJar()
	transport := http.DefaultTransport.(*http.Transport).Clone()
	httpClient := &http.Client{Jar: jar, Timeout: 30 * time.Second, Transport: transport}
	c := &Client{HTTP: httpClient, AccountType: "undergraduate"}
	c.ApplyCookies(cookies)
	return c
}

func (c *Client) SetTimeout(timeout time.Duration) {
	if timeout > 0 {
		c.HTTP.Timeout = timeout
	}
}

func (c *Client) SetCaptchaSolver(solver CaptchaSolver) {
	c.captchaSolver = solver
}

func (c *Client) CloseIdleConnections() {
	if c != nil && c.HTTP != nil {
		c.HTTP.CloseIdleConnections()
	}
}

func (c *Client) Lock() func() { c.mu.Lock(); return c.mu.Unlock }

func (c *Client) ApplyCookies(values []store.Cookie) {
	byDomain := map[string][]*http.Cookie{}
	for _, item := range values {
		domain := strings.TrimPrefix(strings.TrimSpace(item.Domain), ".")
		if domain == "" {
			continue
		}
		path := item.Path
		if path == "" {
			path = "/"
		}
		byDomain[domain] = append(byDomain[domain], &http.Cookie{Name: item.Name, Value: item.Value, Path: path, Domain: item.Domain})
	}
	for domain, items := range byDomain {
		u, _ := url.Parse("https://" + domain)
		c.HTTP.Jar.SetCookies(u, items)
	}
}

func (c *Client) Cookies() []store.Cookie {
	if jar, ok := c.HTTP.Jar.(*persistentCookieJar); ok {
		return jar.PersistentCookies()
	}
	return nil
}

func (c *Client) request(ctx context.Context, method, rawURL string, form url.Values) (*http.Response, error) {
	var body io.Reader
	if form != nil {
		body = strings.NewReader(form.Encode())
	}
	req, err := http.NewRequestWithContext(ctx, method, rawURL, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36")
	req.Header.Set("Accept-Language", "zh-CN,zh;q=0.9")
	if form != nil {
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	}
	return c.HTTP.Do(req)
}

func readResponse(resp *http.Response) ([]byte, error) {
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, maxResponseBody+1))
	if err != nil {
		return nil, err
	}
	if len(raw) > maxResponseBody {
		return nil, fmt.Errorf("教务响应超过 %d MiB 上限", maxResponseBody>>20)
	}
	return raw, nil
}

func parseDocument(raw []byte) (*goquery.Document, error) {
	return goquery.NewDocumentFromReader(strings.NewReader(string(raw)))
}

func selectedForm(doc *goquery.Document, selector string) (string, url.Values, bool) {
	form := doc.Find(selector).First()
	if form.Length() == 0 {
		return "", nil, false
	}
	parsed := parseForm(form)
	return parsed.Action, parsed.Values, true
}

func parseForm(form *goquery.Selection) parsedForm {
	action, _ := form.Attr("action")
	method, _ := form.Attr("method")
	enctype, _ := form.Attr("enctype")
	result := parsedForm{
		Action:  strings.TrimSpace(action),
		Method:  strings.ToLower(strings.TrimSpace(method)),
		Enctype: strings.ToLower(strings.TrimSpace(strings.Split(enctype, ";")[0])),
		Values:  url.Values{},
	}
	if result.Method == "" {
		result.Method = http.MethodGet
	}
	if result.Enctype == "" {
		result.Enctype = "application/x-www-form-urlencoded"
	}
	form.Find("input, textarea, select").Each(func(_ int, control *goquery.Selection) {
		if _, disabled := control.Attr("disabled"); disabled {
			return
		}
		name, ok := control.Attr("name")
		name = strings.TrimSpace(name)
		if !ok || name == "" {
			return
		}
		switch goquery.NodeName(control) {
		case "input":
			kind, _ := control.Attr("type")
			kind = strings.ToLower(strings.TrimSpace(kind))
			switch kind {
			case "submit", "button", "reset", "image", "file":
				return
			case "checkbox", "radio":
				if _, checked := control.Attr("checked"); !checked {
					return
				}
			}
			value, exists := control.Attr("value")
			if !exists && (kind == "checkbox" || kind == "radio") {
				value = "on"
			}
			result.Values.Add(name, value)
		case "textarea":
			result.Values.Add(name, control.Text())
		case "select":
			options := control.Find("option[selected]")
			if options.Length() == 0 {
				options = control.Find("option").First()
			}
			options.Each(func(_ int, option *goquery.Selection) {
				if _, disabled := option.Attr("disabled"); disabled {
					return
				}
				value, exists := option.Attr("value")
				if !exists {
					value = option.Text()
				}
				result.Values.Add(name, value)
			})
		}
	})
	return result
}

func validatePostForm(form parsedForm) error {
	if form.Method != strings.ToLower(http.MethodPost) {
		return fmt.Errorf("智慧理工登录表单提交方式异常: %s", form.Method)
	}
	if form.Enctype != "application/x-www-form-urlencoded" {
		return fmt.Errorf("智慧理工登录表单编码异常: %s", form.Enctype)
	}
	return nil
}

func formField(form *goquery.Selection, values url.Values, id string) string {
	control := form.Find("#" + id).First()
	if name, ok := control.Attr("name"); ok {
		if value := strings.TrimSpace(values.Get(name)); value != "" {
			return value
		}
	}
	value, _ := control.Attr("value")
	return strings.TrimSpace(value)
}

func resolveFormURL(base, ref string) (string, error) {
	u, err := url.Parse(base)
	if err != nil {
		return "", fmt.Errorf("表单基准地址无效: %w", err)
	}
	r, err := url.Parse(ref)
	if err != nil {
		return "", fmt.Errorf("表单提交地址无效: %w", err)
	}
	target := u.ResolveReference(r)
	if (target.Scheme != "http" && target.Scheme != "https") || !strings.EqualFold(target.Host, u.Host) {
		return "", errors.New("表单提交地址不在当前教务站点")
	}
	return target.String(), nil
}

func (c *Client) isLoginPage(resp *http.Response, raw []byte) bool {
	finalURL := ""
	if resp != nil && resp.Request != nil && resp.Request.URL != nil {
		finalURL = resp.Request.URL.String()
	}
	text := strings.ToLower(string(raw))
	return strings.Contains(finalURL, "authserver/login") || strings.Contains(finalURL, "logon.do") || strings.Contains(text, "name=\"randomcode\"") || strings.Contains(text, "name=\"username\"") && strings.Contains(text, "name=\"password\"")
}

func (c *Client) Validate(ctx context.Context) error {
	if c.AccountType == "graduate" || strings.HasPrefix(c.StudentID, "1") {
		return c.validateGraduate(ctx)
	}
	resp, err := c.request(ctx, http.MethodGet, mainURL, nil)
	if err != nil {
		return err
	}
	raw, err := readResponse(resp)
	if err != nil {
		return err
	}
	if resp.StatusCode != http.StatusOK || c.isLoginPage(resp, raw) {
		return ErrSessionExpired
	}
	c.extractIdentity(string(raw))
	return nil
}

func (c *Client) extractIdentity(html string) {
	doc, err := goquery.NewDocumentFromReader(strings.NewReader(html))
	if err == nil {
		if c.StudentName == "" {
			loginName := strings.TrimSpace(doc.Find("#Top1_divLoginName").First().Text())
			if loginName != "" {
				if index := strings.IndexAny(loginName, "(（"); index > 0 {
					loginName = strings.TrimSpace(loginName[:index])
				}
				c.StudentName = loginName
			}
		}
		text := strings.Join(strings.Fields(doc.Text()), " ")
		if c.StudentName == "" {
			for _, marker := range []string{"，同学", ",同学"} {
				if i := strings.Index(text, marker); i > 0 {
					left := []rune(text[:i])
					start := len(left) - 4
					if start < 0 {
						start = 0
					}
					candidate := strings.TrimSpace(string(left[start:]))
					fields := strings.Fields(candidate)
					if len(fields) > 0 {
						c.StudentName = fields[len(fields)-1]
					}
					break
				}
			}
		}
	}
	if c.StudentID == "" {
		for _, field := range strings.FieldsFunc(html, func(r rune) bool { return r < '0' || r > '9' }) {
			if len(field) >= 8 && len(field) <= 14 {
				if len(field) == 12 && strings.HasPrefix(field, "9") {
					c.StudentID = field
					break
				}
			}
		}
	}
}

func (c *Client) JSON(ctx context.Context, method, rawURL string, form url.Values, target any) error {
	resp, err := c.request(ctx, method, rawURL, form)
	if err != nil {
		return err
	}
	raw, err := readResponse(resp)
	if err != nil {
		return err
	}
	if c.isLoginPage(resp, raw) {
		return ErrSessionExpired
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("教务返回 HTTP %d", resp.StatusCode)
	}
	if err := json.Unmarshal(raw, target); err != nil {
		return fmt.Errorf("解析教务 JSON: %w", err)
	}
	return nil
}
