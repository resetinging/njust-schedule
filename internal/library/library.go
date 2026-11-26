// Package library 提供江苏汇文 OPAC（图书馆公共馆藏）的匿名只读客户端。
//
// 边界：
//   - 仅访问公开 OPAC 主机上的固定路径，不接受用户传入的 URL；
//   - 不读取、不保存任何教务 Cookie / SSO / 服务账号凭据；
//   - 搜索结果只解析书目元数据，库存明细必须由用户点选书目后按需请求；
//   - 上游 HTTP 200 但正文为业务错误（如“出错啦”）一律按错误处理，绝不当作空库存。
package library

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"github.com/PuerkitoBio/goquery"
)

const (
	DefaultBaseURL = "http://libopac.njust.edu.cn"
	searchPath     = "/uopac/opac/ajax_search_adv.php"
	itemPath       = "/uopac/opac/ajax_item.php"

	DefaultPageSize = 20
	MaxPageSize     = 50
	// MaxPage 提高为 200：默认 20 条/页可覆盖约 4000 条结果，真实「高等数学」2582 条可完整翻完；
	// 超出上限由服务端返回 truncated 标记，前端不会谎称“已加载全部”。
	MaxPage         = 200
	MaxKeywordRunes = 80
	maxBodyBytes    = 2 << 20 // 2 MiB
)

var (
	ErrInvalidInput = errors.New("library: invalid input")
	ErrUpstream     = errors.New("library: upstream request failed")
	ErrBusiness     = errors.New("library: upstream business error")
)

// marcNoPattern 约束不透明书目 ID：只允许公开 ID 中实际出现的字符，长度 8..128。
var marcNoPattern = regexp.MustCompile(`^[A-Za-z0-9+/=_-]{8,128}$`)

// Field 描述支持的检索字段；Code 是 OPAC 高级检索的真实 fieldCode。
type Field struct {
	Key   string
	Code  string
	Label string
}

var Fields = []Field{
	{Key: "title", Code: "02", Label: "书名"},
	{Key: "author", Code: "03", Label: "作者"},
	{Key: "isbn", Code: "05", Label: "ISBN"},
	{Key: "callno", Code: "08", Label: "索书号"},
}

func FieldByKey(key string) (Field, bool) {
	key = strings.TrimSpace(key)
	for _, field := range Fields {
		if field.Key == key {
			return field, true
		}
	}
	return Field{}, false
}

// ValidateKeyword 返回规范化后的关键词。拒绝控制字符与超长输入。
func ValidateKeyword(raw string) (string, error) {
	keyword := strings.TrimSpace(raw)
	if keyword == "" {
		return "", ErrInvalidInput
	}
	if utf8.RuneCountInString(keyword) > MaxKeywordRunes {
		return "", ErrInvalidInput
	}
	for _, r := range keyword {
		if unicode.IsControl(r) {
			return "", ErrInvalidInput
		}
	}
	return keyword, nil
}

func ValidateMarcNo(raw string) (string, error) {
	marcNo := strings.TrimSpace(raw)
	if !marcNoPattern.MatchString(marcNo) {
		return "", ErrInvalidInput
	}
	return marcNo, nil
}

func ValidatePage(page, pageSize int) error {
	if page < 1 || page > MaxPage {
		return ErrInvalidInput
	}
	if pageSize < 1 || pageSize > MaxPageSize {
		return ErrInvalidInput
	}
	return nil
}

// Query 是一次书目检索请求。
type Query struct {
	Field    Field
	Keyword  string
	Page     int
	PageSize int
}

// Record 是搜索结果中的一条书目（不含库存）。
type Record struct {
	MarcNo    string `json:"marc_no"`
	Title     string `json:"title"`
	Author    string `json:"author"`
	Publisher string `json:"publisher"`
	PubYear   string `json:"pub_year"`
	ISBN      string `json:"isbn"`
	CallNo    string `json:"call_no"`
	DocType   string `json:"doc_type"`
	Num       int    `json:"num"`
}

type SearchResult struct {
	Total    int      `json:"total"`
	Page     int      `json:"page"`
	PageSize int      `json:"page_size"`
	Records  []Record `json:"records"`
}

// Copy 是一册实体馆藏。
type Copy struct {
	CallNo    string `json:"call_no"`
	Barcode   string `json:"barcode"`
	Volume    string `json:"volume"`
	Campus    string `json:"campus"`    // 南京 / 江阴 / 未知
	Location  string `json:"location"`  // 上游原始“校区—馆藏地”文本
	Status    string `json:"status"`    // 上游原始状态
	Available bool   `json:"available"` // 仅当状态明确为“可借”时为 true
}

// Inventory 是一本书的全部馆藏（未按校区过滤）。
type Inventory struct {
	MarcNo    string `json:"marc_no"`
	Copies    []Copy `json:"copies"`
	Total     int    `json:"total"`
	Available int    `json:"available"`
}

// CampusCounts 是全量馆藏的校区分布，用于详情弹层显示“全部/南京/江阴”。
type CampusCounts struct {
	Nanjing  int `json:"nanjing"`
	Jiangyin int `json:"jiangyin"`
	Unknown  int `json:"unknown"`
}

func (inv Inventory) CampusCounts() CampusCounts {
	var counts CampusCounts
	for _, copy := range inv.Copies {
		switch copy.Campus {
		case "南京":
			counts.Nanjing++
		case "江阴":
			counts.Jiangyin++
		default:
			counts.Unknown++
		}
	}
	return counts
}

// FilterCampus 按校区过滤明细并同步重算 total/available（统计与明细一致）。
// scope: all | nanjing | jiangyin
func (inv Inventory) FilterCampus(scope string) (Inventory, error) {
	scope = strings.TrimSpace(scope)
	if scope == "" {
		scope = "all"
	}
	if scope != "all" && scope != "nanjing" && scope != "jiangyin" {
		return Inventory{}, ErrInvalidInput
	}
	filtered := Inventory{MarcNo: inv.MarcNo, Copies: make([]Copy, 0, len(inv.Copies))}
	want := map[string]string{"nanjing": "南京", "jiangyin": "江阴"}[scope]
	for _, copy := range inv.Copies {
		if scope != "all" && copy.Campus != want {
			continue
		}
		filtered.Copies = append(filtered.Copies, copy)
	}
	filtered.Total = len(filtered.Copies)
	for _, copy := range filtered.Copies {
		if copy.Available {
			filtered.Available++
		}
	}
	return filtered, nil
}

// Client 访问图书馆 OPAC，匿名、无 Cookie。
type Client struct {
	baseURL string
	http    *http.Client
	maxBody int64
}

func NewClient(timeout time.Duration) *Client {
	return NewClientWithBaseURL(DefaultBaseURL, timeout)
}

// NewClientWithBaseURL 仅用于测试/本地联调（httptest）；生产只使用固定上游 host。
func NewClientWithBaseURL(baseURL string, timeout time.Duration) *Client {
	if timeout <= 0 {
		timeout = 10 * time.Second
	}
	return &Client{
		baseURL: strings.TrimRight(strings.TrimSpace(baseURL), "/"),
		http: &http.Client{
			Timeout: timeout,
			Transport: &http.Transport{
				Proxy:                 http.ProxyFromEnvironment,
				MaxIdleConns:          16,
				MaxIdleConnsPerHost:   8,
				IdleConnTimeout:       90 * time.Second,
				TLSHandshakeTimeout:   5 * time.Second,
				ResponseHeaderTimeout: timeout,
			},
		},
		maxBody: maxBodyBytes,
	}
}

func (c *Client) CloseIdleConnections() {
	if c != nil && c.http != nil {
		c.http.CloseIdleConnections()
	}
}

type searchRequest struct {
	SearchWords []searchWord `json:"searchWords"`
	Filters     []any        `json:"filters"`
	Limiter     []any        `json:"limiter"`
	SortField   string       `json:"sortField"`
	SortType    string       `json:"sortType"`
	PageSize    int          `json:"pageSize"`
	PageCount   int          `json:"pageCount"`
	Locale      string       `json:"locale"`
	First       bool         `json:"first"`
}

type searchWord struct {
	FieldList []searchField `json:"fieldList"`
}

type searchField struct {
	FieldCode  string `json:"fieldCode"`
	FieldValue string `json:"fieldValue"`
}

type searchEnvelope struct {
	Total   *int               `json:"total"`
	Content *[]json.RawMessage `json:"content"`
	Err     *bool              `json:"err"`
	ErrMsg  string             `json:"errMsg"`
}

type searchRecord struct {
	Author      string `json:"author"`
	CallNo      string `json:"callNo"`
	DocTypeName string `json:"docTypeName"`
	ISBN        string `json:"isbn"`
	MarcRecNo   string `json:"marcRecNo"`
	Num         int    `json:"num"`
	PubYear     string `json:"pubYear"`
	Publisher   string `json:"publisher"`
	Title       string `json:"title"`
}

// Search 调用高级检索接口，只返回书目元数据，不逐条抓取库存。
func (c *Client) Search(ctx context.Context, query Query) (SearchResult, error) {
	if err := ValidatePage(query.Page, query.PageSize); err != nil {
		return SearchResult{}, err
	}
	if _, ok := FieldByKey(query.Field.Key); !ok {
		return SearchResult{}, ErrInvalidInput
	}
	keyword, err := ValidateKeyword(query.Keyword)
	if err != nil {
		return SearchResult{}, err
	}

	payload := searchRequest{
		SearchWords: []searchWord{{FieldList: []searchField{{FieldCode: query.Field.Code, FieldValue: keyword}}}},
		Filters:     []any{},
		Limiter:     []any{},
		SortField:   "relevance",
		SortType:    "desc",
		PageSize:    query.PageSize,
		PageCount:   query.Page,
		Locale:      "zh_CN",
		First:       true,
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return SearchResult{}, fmt.Errorf("%w: 构造检索请求失败", ErrUpstream)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+searchPath, bytes.NewReader(body))
	if err != nil {
		return SearchResult{}, fmt.Errorf("%w: 构造检索请求失败", ErrUpstream)
	}
	setCommonHeaders(req)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Requested-With", "XMLHttpRequest")
	req.Header.Set("Accept", "application/json, text/javascript, */*; q=0.01")

	raw, err := c.do(req)
	if err != nil {
		return SearchResult{}, err
	}
	if bytes.Contains(raw, []byte("出错啦")) {
		return SearchResult{}, fmt.Errorf("%w: 检索接口返回业务错误", ErrBusiness)
	}
	var decoded searchEnvelope
	if err := json.Unmarshal(raw, &decoded); err != nil {
		return SearchResult{}, fmt.Errorf("%w: 检索响应不是有效 JSON", ErrUpstream)
	}
	if decoded.Err != nil && *decoded.Err {
		return SearchResult{}, fmt.Errorf("%w: %s", ErrBusiness, sanitizeMessage(decoded.ErrMsg))
	}
	// 上游 HTTP 200 也可能返回 {}、null、{"message":...} 或缺少 content 的错误结构；
	// 只有 total 为非负整数且 content 为数组时才可能是合法结果（空数组合法）。
	if decoded.Total == nil || decoded.Content == nil {
		return SearchResult{}, fmt.Errorf("%w: 检索响应缺少 total/content", ErrBusiness)
	}
	if *decoded.Total < 0 {
		return SearchResult{}, fmt.Errorf("%w: 非法 total", ErrBusiness)
	}
	if len(*decoded.Content) > query.PageSize {
		return SearchResult{}, fmt.Errorf("%w: 检索响应超过请求页大小", ErrBusiness)
	}
	// 合理性：offset 为当前页首条在完整结果中的位置。
	// - 非空 content 必须满足 offset+len(content)<=total，且不能出现在 offset>=total 的越界页；
	// - total>0 时，只有 offset>=total 的空页合法；首页空 content 或 total=0 却非空均非法。
	offset := (query.Page - 1) * query.PageSize
	contentLen := len(*decoded.Content)
	if contentLen == 0 {
		if *decoded.Total > 0 && offset < *decoded.Total {
			return SearchResult{}, fmt.Errorf("%w: 检索响应 total 与 content 不一致", ErrBusiness)
		}
	} else if offset >= *decoded.Total || offset+contentLen > *decoded.Total {
		return SearchResult{}, fmt.Errorf("%w: 检索响应 content 超出 total 范围", ErrBusiness)
	}

	records := make([]Record, 0, len(*decoded.Content))
	for index, rawRecord := range *decoded.Content {
		var item searchRecord
		if err := json.Unmarshal(rawRecord, &item); err != nil {
			return SearchResult{}, fmt.Errorf("%w: 第 %d 条书目结构不合法", ErrBusiness, index+1)
		}
		marcNo := strings.TrimSpace(item.MarcRecNo)
		title := strings.TrimSpace(item.Title)
		if !marcNoPattern.MatchString(marcNo) || title == "" {
			return SearchResult{}, fmt.Errorf("%w: 第 %d 条书目缺少标题或书目 ID", ErrBusiness, index+1)
		}
		if item.Num < 0 {
			return SearchResult{}, fmt.Errorf("%w: 第 %d 条书目 num 不合法", ErrBusiness, index+1)
		}
		records = append(records, Record{
			MarcNo:    marcNo,
			Title:     title,
			Author:    strings.TrimSpace(item.Author),
			Publisher: strings.TrimSpace(item.Publisher),
			PubYear:   strings.TrimSpace(item.PubYear),
			ISBN:      strings.TrimSpace(item.ISBN),
			CallNo:    strings.TrimSpace(item.CallNo),
			DocType:   strings.TrimSpace(item.DocTypeName),
			Num:       item.Num,
		})
	}
	return SearchResult{Total: *decoded.Total, Page: query.Page, PageSize: query.PageSize, Records: records}, nil
}

// Item 获取一本书的逐册馆藏。只由 MARC ID 构造固定路径，禁止任意 URL。
func (c *Client) Item(ctx context.Context, rawMarcNo string) (Inventory, error) {
	marcNo, err := ValidateMarcNo(rawMarcNo)
	if err != nil {
		return Inventory{}, err
	}
	target := c.baseURL + itemPath + "?marc_no=" + url.QueryEscape(marcNo)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, target, nil)
	if err != nil {
		return Inventory{}, fmt.Errorf("%w: 构造明细请求失败", ErrUpstream)
	}
	setCommonHeaders(req)
	req.Header.Set("X-Requested-With", "XMLHttpRequest")
	req.Header.Set("Accept", "text/html, */*; q=0.01")

	raw, err := c.do(req)
	if err != nil {
		return Inventory{}, err
	}
	if bytes.Contains(raw, []byte("出错啦")) {
		return Inventory{}, fmt.Errorf("%w: 明细接口返回业务错误", ErrBusiness)
	}
	doc, err := goquery.NewDocumentFromReader(bytes.NewReader(raw))
	if err != nil {
		return Inventory{}, fmt.Errorf("%w: 明细响应无法解析", ErrUpstream)
	}
	table := doc.Find("table#item")
	if table.Length() == 0 {
		return Inventory{}, fmt.Errorf("%w: 明细响应缺少馆藏表格", ErrBusiness)
	}

	inventory := Inventory{MarcNo: marcNo, Copies: make([]Copy, 0, 8)}
	table.Find("tr").Each(func(_ int, row *goquery.Selection) {
		cells := row.Find("td")
		if cells.Length() < 5 {
			return
		}
		values := make([]string, 0, 5)
		cells.Each(func(_ int, cell *goquery.Selection) {
			values = append(values, strings.TrimSpace(cell.Text()))
		})
		if len(values) < 5 || values[0] == "索书号" {
			return
		}
		callNo, barcode, volume := values[0], values[1], values[2]
		location, status := values[3], values[4]
		if callNo == "" && barcode == "" && status == "" {
			return
		}
		campus := "未知"
		if strings.HasPrefix(location, "南京") {
			campus = "南京"
		} else if strings.HasPrefix(location, "江阴") {
			campus = "江阴"
		}
		copy := Copy{
			CallNo: callNo, Barcode: barcode, Volume: volume,
			Campus: campus, Location: location, Status: status,
			Available: status == "可借",
		}
		inventory.Copies = append(inventory.Copies, copy)
		if copy.Available {
			inventory.Available++
		}
	})
	inventory.Total = len(inventory.Copies)
	return inventory, nil
}

func (c *Client) do(req *http.Request) ([]byte, error) {
	resp, err := c.http.Do(req)
	if err != nil {
		if ctxErr := req.Context().Err(); ctxErr != nil {
			return nil, ctxErr
		}
		return nil, fmt.Errorf("%w: %v", ErrUpstream, sanitizeMessage(err.Error()))
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
		return nil, fmt.Errorf("%w: HTTP %d", ErrUpstream, resp.StatusCode)
	}
	limit := c.maxBody
	if limit <= 0 {
		limit = maxBodyBytes
	}
	raw, err := io.ReadAll(io.LimitReader(resp.Body, limit+1))
	if err != nil {
		return nil, fmt.Errorf("%w: 读取响应失败", ErrUpstream)
	}
	if int64(len(raw)) > limit {
		return nil, fmt.Errorf("%w: 响应体超过上限", ErrUpstream)
	}
	return raw, nil
}

func setCommonHeaders(req *http.Request) {
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
	req.Header.Set("Referer", DefaultBaseURL+"/uopac/opac/search_adv.php")
}

// sanitizeMessage 仅保留短文本，避免上游异常信息过长或包含无关细节。
func sanitizeMessage(raw string) string {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return "上游返回错误"
	}
	runes := []rune(raw)
	if len(runes) > 120 {
		raw = string(runes[:120])
	}
	return raw
}
