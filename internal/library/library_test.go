package library

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func fixture(t *testing.T, name string) []byte {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("testdata", name))
	if err != nil {
		t.Fatalf("读取 fixture %s 失败: %v", name, err)
	}
	return raw
}

// recordedRequest 是上游收到的请求快照（请求体在 handler 内读取，避免测试读到已消费的 Body）。
type recordedRequest struct {
	Method string
	Path   string
	Query  url.Values
	Header http.Header
	Body   []byte
}

// newUpstream 构造只服务 OPAC 两条路径的 httptest 上游，并返回请求快照。
func newUpstream(t *testing.T, searchBody, itemBody []byte, status int) (*httptest.Server, *[]recordedRequest) {
	t.Helper()
	var requests []recordedRequest
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		requests = append(requests, recordedRequest{
			Method: r.Method, Path: r.URL.Path, Query: r.URL.Query(), Header: r.Header.Clone(), Body: body,
		})
		if status != 0 {
			w.WriteHeader(status)
			return
		}
		switch {
		case strings.HasSuffix(r.URL.Path, searchPath):
			if r.Method != http.MethodPost {
				t.Errorf("检索方法 = %s, want POST", r.Method)
			}
			if got := r.Header.Get("X-Requested-With"); got != "XMLHttpRequest" {
				t.Errorf("X-Requested-With = %q", got)
			}
			w.Header().Set("Content-Type", "application/json")
			w.Write(searchBody)
		case strings.HasSuffix(r.URL.Path, itemPath):
			w.Header().Set("Content-Type", "text/html; charset=UTF-8")
			w.Write(itemBody)
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(server.Close)
	return server, &requests
}

func testClient(server *httptest.Server) *Client {
	base := "http://127.0.0.1:1"
	if server != nil {
		base = server.URL
	}
	return NewClientWithBaseURL(base, 2*time.Second)
}

func TestSearchParsesRealVerifiedShape(t *testing.T) {
	upstream, requests := newUpstream(t, fixture(t, "search_handoff.json"), nil, 0)
	client := testClient(upstream)

	result, err := client.Search(context.Background(), Query{
		Field: Fields[0], Keyword: "高等数学", Page: 1, PageSize: 20,
	})
	if err != nil {
		t.Fatalf("Search() error = %v", err)
	}
	if result.Total != 2582 {
		t.Fatalf("Total = %d, want 2582", result.Total)
	}
	if result.Page != 1 || result.PageSize != 20 {
		t.Fatalf("分页回显错误: %+v", result)
	}
	if len(result.Records) != 2 {
		t.Fatalf("Records = %d, want 2", len(result.Records))
	}
	first := result.Records[0]
	if first.MarcNo != "65743033384e4d567677433044795a4f5939463358413d3d" ||
		first.Title != "高等数学:理工类.上册.第3版" ||
		first.Author != "主编杨海涛" ||
		first.CallNo != "O13/797/V.1" ||
		first.ISBN != "978-7-5608-5255-3" ||
		first.Publisher != "同济大学出版社" ||
		first.PubYear != "2013" ||
		first.DocType != "中文图书" || first.Num != 1 {
		t.Fatalf("首条书目解析错误: %+v", first)
	}

	// 请求体必须与页面真实请求结构一致，分页用 pageCount 传递。
	raw := (*requests)[0].Body
	var payload map[string]any
	if err := json.Unmarshal(raw, &payload); err != nil {
		t.Fatalf("请求体不是 JSON: %v (%s)", err, raw)
	}
	if payload["pageCount"] != float64(1) || payload["pageSize"] != float64(20) {
		t.Fatalf("分页字段错误: %s", raw)
	}
	if payload["locale"] != "zh_CN" || payload["first"] != true {
		t.Fatalf("locale/first 字段错误: %s", raw)
	}
	words := payload["searchWords"].([]any)
	field := words[0].(map[string]any)["fieldList"].([]any)[0].(map[string]any)
	if field["fieldCode"] != "02" || field["fieldValue"] != "高等数学" {
		t.Fatalf("检索字段错误: %s", raw)
	}
}

func TestSearchEmptyIsNotError(t *testing.T) {
	upstream, _ := newUpstream(t, fixture(t, "search_empty.json"), nil, 0)
	result, err := testClient(upstream).Search(context.Background(), Query{
		Field: Fields[0], Keyword: "不存在的关键词", Page: 1, PageSize: 20,
	})
	if err != nil {
		t.Fatalf("空结果不应报错: %v", err)
	}
	if result.Total != 0 || len(result.Records) != 0 {
		t.Fatalf("空结果错误: %+v", result)
	}
}

func TestSearchBusinessAndUpstreamErrors(t *testing.T) {
	t.Run("JSON err 字段", func(t *testing.T) {
		upstream, _ := newUpstream(t, []byte(`{"err":true,"errMsg":"检索条件不合法"}`), nil, 0)
		_, err := testClient(upstream).Search(context.Background(), Query{Field: Fields[0], Keyword: "x", Page: 1, PageSize: 20})
		if !errors.Is(err, ErrBusiness) {
			t.Fatalf("err = %v, want ErrBusiness", err)
		}
	})
	t.Run("HTTP200 出错啦", func(t *testing.T) {
		upstream, _ := newUpstream(t, []byte("出错啦"), nil, 0)
		_, err := testClient(upstream).Search(context.Background(), Query{Field: Fields[0], Keyword: "x", Page: 1, PageSize: 20})
		if !errors.Is(err, ErrBusiness) {
			t.Fatalf("err = %v, want ErrBusiness", err)
		}
	})
	t.Run("非 JSON", func(t *testing.T) {
		upstream, _ := newUpstream(t, []byte("<html>gateway</html>"), nil, 0)
		_, err := testClient(upstream).Search(context.Background(), Query{Field: Fields[0], Keyword: "x", Page: 1, PageSize: 20})
		if !errors.Is(err, ErrUpstream) {
			t.Fatalf("err = %v, want ErrUpstream", err)
		}
	})
	t.Run("HTTP 503", func(t *testing.T) {
		upstream, _ := newUpstream(t, nil, nil, http.StatusServiceUnavailable)
		_, err := testClient(upstream).Search(context.Background(), Query{Field: Fields[0], Keyword: "x", Page: 1, PageSize: 20})
		if !errors.Is(err, ErrUpstream) {
			t.Fatalf("err = %v, want ErrUpstream", err)
		}
	})
}

func TestSearchInputValidation(t *testing.T) {
	client := testClient(nil) // 不会真正发请求
	cases := []struct {
		name  string
		query Query
	}{
		{"空关键词", Query{Field: Fields[0], Keyword: "  ", Page: 1, PageSize: 20}},
		{"超长关键词", Query{Field: Fields[0], Keyword: strings.Repeat("书", MaxKeywordRunes+1), Page: 1, PageSize: 20}},
		{"控制字符", Query{Field: Fields[0], Keyword: "高\x00等", Page: 1, PageSize: 20}},
		{"未知字段", Query{Field: Field{Key: "subject", Code: "04"}, Keyword: "数学", Page: 1, PageSize: 20}},
		{"页码0", Query{Field: Fields[0], Keyword: "数学", Page: 0, PageSize: 20}},
		{"页码超限", Query{Field: Fields[0], Keyword: "数学", Page: MaxPage + 1, PageSize: 20}},
		{"页大小0", Query{Field: Fields[0], Keyword: "数学", Page: 1, PageSize: 0}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if _, err := client.Search(context.Background(), tc.query); !errors.Is(err, ErrInvalidInput) {
				t.Fatalf("err = %v, want ErrInvalidInput", err)
			}
		})
	}
}

func TestItemParsesVerifiedCopies(t *testing.T) {
	upstream, requests := newUpstream(t, nil, fixture(t, "item_handoff.html"), 0)
	client := testClient(upstream)

	inv, err := client.Item(context.Background(), "65743033384e4d567677433044795a4f5939463358413d3d")
	if err != nil {
		t.Fatalf("Item() error = %v", err)
	}
	if inv.Total != 5 || inv.Available != 5 {
		t.Fatalf("total/available = %d/%d, want 5/5", inv.Total, inv.Available)
	}
	counts := inv.CampusCounts()
	if counts.Jiangyin != 2 || counts.Nanjing != 2 || counts.Unknown != 1 {
		t.Fatalf("campus counts = %+v", counts)
	}
	first := inv.Copies[0]
	if first.CallNo != "O13/797/V.1" || first.Barcode != "B0000001" ||
		first.Campus != "江阴" || first.Location != "江阴综合书库305室" ||
		first.Status != "可借" || !first.Available {
		t.Fatalf("首册解析错误: %+v", first)
	}
	if got := (*requests)[0].Query.Get("marc_no"); got != "65743033384e4d567677433044795a4f5939463358413d3d" {
		t.Fatalf("marc_no 查询参数 = %q", got)
	}
}

func TestItemUnknownStatusNeverCountedAvailable(t *testing.T) {
	upstream, _ := newUpstream(t, nil, fixture(t, "item_unknown_status.html"), 0)
	inv, err := testClient(upstream).Item(context.Background(), "QUJDREVGR0hJSktMTU5PUA==")
	if err != nil {
		t.Fatalf("Item() error = %v", err)
	}
	if inv.Total != 5 || inv.Available != 1 {
		t.Fatalf("total/available = %d/%d, want 5/1", inv.Total, inv.Available)
	}
	for _, copy := range inv.Copies {
		if copy.Status != "可借" && copy.Available {
			t.Fatalf("非明确可借状态被计为可借: %+v", copy)
		}
	}
	counts := inv.CampusCounts()
	if counts.Nanjing != 3 || counts.Jiangyin != 1 || counts.Unknown != 1 {
		t.Fatalf("campus counts = %+v", counts)
	}
}

func TestItemEmptyInventoryIsNotError(t *testing.T) {
	upstream, _ := newUpstream(t, nil, fixture(t, "item_empty.html"), 0)
	inv, err := testClient(upstream).Item(context.Background(), "QUJDREVGR0hJSktMTU5PUA==")
	if err != nil {
		t.Fatalf("空馆藏不应报错: %v", err)
	}
	if inv.Total != 0 || inv.Available != 0 || len(inv.Copies) != 0 {
		t.Fatalf("空馆藏解析错误: %+v", inv)
	}
}

func TestItemBusinessErrorAndInvalidHTML(t *testing.T) {
	t.Run("出错啦", func(t *testing.T) {
		upstream, _ := newUpstream(t, nil, fixture(t, "item_error.html"), 0)
		_, err := testClient(upstream).Item(context.Background(), "QUJDREVGR0hJSktMTU5PUA==")
		if !errors.Is(err, ErrBusiness) {
			t.Fatalf("err = %v, want ErrBusiness", err)
		}
	})
	t.Run("缺少馆藏表格", func(t *testing.T) {
		upstream, _ := newUpstream(t, nil, []byte("<html><body>not found</body></html>"), 0)
		_, err := testClient(upstream).Item(context.Background(), "QUJDREVGR0hJSktMTU5PUA==")
		if !errors.Is(err, ErrBusiness) {
			t.Fatalf("err = %v, want ErrBusiness", err)
		}
	})
	t.Run("HTTP 500", func(t *testing.T) {
		upstream, _ := newUpstream(t, nil, nil, http.StatusInternalServerError)
		_, err := testClient(upstream).Item(context.Background(), "QUJDREVGR0hJSktMTU5PUA==")
		if !errors.Is(err, ErrUpstream) {
			t.Fatalf("err = %v, want ErrUpstream", err)
		}
	})
}

func TestMarcNoValidationAndURLConstruction(t *testing.T) {
	bad := []string{"", "abc", "6574 3033", "../../etc/passwd", "65743033384e4d56?x=1", strings.Repeat("a", 129)}
	for _, marcNo := range bad {
		if _, err := ValidateMarcNo(marcNo); !errors.Is(err, ErrInvalidInput) {
			t.Fatalf("ValidateMarcNo(%q) err = %v, want ErrInvalidInput", marcNo, err)
		}
	}
	valid := "QUJDREVGR0hJSktMTU5PUA=="
	if got, err := ValidateMarcNo(valid); err != nil || got != valid {
		t.Fatalf("合法 marc 被拒绝: %q, %v", got, err)
	}

	upstream, requests := newUpstream(t, nil, fixture(t, "item_empty.html"), 0)
	if _, err := testClient(upstream).Item(context.Background(), valid); err != nil {
		t.Fatalf("Item() error = %v", err)
	}
	req := (*requests)[0]
	if req.Path != itemPath {
		t.Fatalf("请求 path = %q, want %q", req.Path, itemPath)
	}
	host := strings.TrimPrefix(upstream.URL, "http://")
	if got := strings.TrimPrefix(upstream.URL, "http://"); !strings.HasPrefix(got, host) {
		t.Fatalf("请求 host 异常: %s", host)
	}
}

func TestFilterCampusKeepsStatisticsAndDetailsConsistent(t *testing.T) {
	upstream, _ := newUpstream(t, nil, fixture(t, "item_handoff.html"), 0)
	inv, err := testClient(upstream).Item(context.Background(), "QUJDREVGR0hJSktMTU5PUA==")
	if err != nil {
		t.Fatal(err)
	}
	nanjing, err := inv.FilterCampus("nanjing")
	if err != nil {
		t.Fatal(err)
	}
	if nanjing.Total != 2 || nanjing.Available != 2 {
		t.Fatalf("南京过滤错误: total=%d avail=%d", nanjing.Total, nanjing.Available)
	}
	for _, copy := range nanjing.Copies {
		if copy.Campus != "南京" {
			t.Fatalf("南京过滤混入其他校区: %+v", copy)
		}
	}
	jiangyin, err := inv.FilterCampus("jiangyin")
	if err != nil {
		t.Fatal(err)
	}
	if jiangyin.Total != 2 || jiangyin.Available != 2 {
		t.Fatalf("江阴过滤错误: total=%d avail=%d", jiangyin.Total, jiangyin.Available)
	}
	all, err := inv.FilterCampus("all")
	if err != nil {
		t.Fatal(err)
	}
	if all.Total != 5 || all.Available != 5 {
		t.Fatalf("全部过滤错误: total=%d avail=%d", all.Total, all.Available)
	}
	if _, err := inv.FilterCampus("beijing"); !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("非法校区应返回 ErrInvalidInput, got %v", err)
	}
}

func TestContextCancellation(t *testing.T) {
	slow := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(300 * time.Millisecond)
		w.Write([]byte(`{"total":0,"content":[]}`))
	}))
	t.Cleanup(slow.Close)
	client := NewClientWithBaseURL(slow.URL, 5*time.Second)
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Millisecond)
	defer cancel()
	start := time.Now()
	_, err := client.Search(ctx, Query{Field: Fields[0], Keyword: "数学", Page: 1, PageSize: 20})
	if err == nil {
		t.Fatal("超时未返回错误")
	}
	if time.Since(start) > 2*time.Second {
		t.Fatalf("取消响应过慢: %v", time.Since(start))
	}
}

func TestResponseBodyLimit(t *testing.T) {
	big := strings.Repeat("x", maxBodyBytes+10)
	upstream, _ := newUpstream(t, []byte(big), nil, 0)
	_, err := testClient(upstream).Search(context.Background(), Query{Field: Fields[0], Keyword: "数学", Page: 1, PageSize: 20})
	if !errors.Is(err, ErrUpstream) {
		t.Fatalf("err = %v, want ErrUpstream (超限)", err)
	}
}
