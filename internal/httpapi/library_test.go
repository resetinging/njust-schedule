package httpapi

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/resetinging/njust-schedule/internal/config"
	"github.com/resetinging/njust-schedule/internal/library"
	"github.com/resetinging/njust-schedule/internal/session"
)

func libraryFixture(t *testing.T, name string) []byte {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("..", "library", "testdata", name))
	if err != nil {
		t.Fatalf("读取 fixture %s 失败: %v", name, err)
	}
	return raw
}

// newLibraryUpstream 构造可切换成功/失败的上游，并统计访问次数。
func newLibraryUpstream(t *testing.T, searchBody, itemBody []byte) (*httptest.Server, *int32, *atomic.Bool) {
	t.Helper()
	var calls int32
	failing := &atomic.Bool{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&calls, 1)
		if failing.Load() {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		switch {
		case strings.HasSuffix(r.URL.Path, "/ajax_search_adv.php"):
			w.Header().Set("Content-Type", "application/json")
			w.Write(searchBody)
		case strings.HasSuffix(r.URL.Path, "/ajax_item.php"):
			w.Header().Set("Content-Type", "text/html; charset=UTF-8")
			w.Write(itemBody)
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(server.Close)
	return server, &calls, failing
}

func newLibraryTestServer(t *testing.T, upstreamURL string, accountType string) (*Server, string) {
	t.Helper()
	manager, err := session.NewManager(time.Hour, 10, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = manager.Close() })
	token, err := manager.Add(context.Background(), &session.Session{
		StudentID: "20230001", AccountType: accountType,
	})
	if err != nil {
		t.Fatal(err)
	}
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	server := &Server{
		cfg:      config.Config{JWCRequestTimeout: time.Minute},
		sessions: manager, logger: logger,
		cache: map[string]cacheEntry{}, dedupe: map[string]*inflight{}, rates: map[string][]time.Time{},
		library:      library.NewClientWithBaseURL(upstreamURL, 2*time.Second),
		librarySlots: make(chan struct{}, 2),
		ctx:          context.Background(),
	}
	return server, token
}

func libraryRequest(t *testing.T, token, target string) *http.Request {
	t.Helper()
	request := httptest.NewRequest(http.MethodGet, target, nil)
	if token != "" {
		request.Header.Set(tokenHeader, token)
	}
	return request
}

type librarySearchPayload struct {
	Success   bool              `json:"success"`
	Field     string            `json:"field"`
	Query     string            `json:"query"`
	Page      int               `json:"page"`
	PageSize  int               `json:"page_size"`
	Total     int               `json:"total"`
	HasMore   bool              `json:"has_more"`
	Stale     bool              `json:"stale"`
	UpdatedAt int64             `json:"updated_at"`
	Records   []json.RawMessage `json:"records"`
}

func TestLibrarySearchRequiresLogin(t *testing.T) {
	upstream, _, _ := newLibraryUpstream(t, libraryFixture(t, "search_handoff.json"), nil)
	server, token := newLibraryTestServer(t, upstream.URL, "undergraduate")

	recorder := httptest.NewRecorder()
	server.librarySearch(recorder, libraryRequest(t, "", "/api/library/search?field=title&q=高等数学"))
	if recorder.Code != http.StatusUnauthorized {
		t.Fatalf("未登录 status = %d, want 401", recorder.Code)
	}

	recorder = httptest.NewRecorder()
	server.librarySearch(recorder, libraryRequest(t, token, "/api/library/search?field=title&q="+url.QueryEscape("高等数学")))
	if recorder.Code != http.StatusOK {
		t.Fatalf("登录后 status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
}

func TestLibrarySearchResponseAndCache(t *testing.T) {
	upstream, calls, _ := newLibraryUpstream(t, libraryFixture(t, "search_handoff.json"), nil)
	server, token := newLibraryTestServer(t, upstream.URL, "undergraduate")
	target := "/api/library/search?field=title&q=" + url.QueryEscape("高等数学") + "&page=1"

	var payload librarySearchPayload
	recorder := httptest.NewRecorder()
	server.librarySearch(recorder, libraryRequest(t, token, target))
	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if !payload.Success || payload.Total != 2582 || payload.Field != "title" || payload.Query != "高等数学" {
		t.Fatalf("响应错误: %+v", payload)
	}
	if !payload.HasMore || payload.Page != 1 || payload.PageSize != 20 || payload.Stale || payload.UpdatedAt == 0 {
		t.Fatalf("分页/缓存标记错误: %+v", payload)
	}
	if len(payload.Records) != 2 {
		t.Fatalf("records = %d, want 2", len(payload.Records))
	}

	// 第二次同 key 必须命中共享缓存，不再打上游。
	recorder = httptest.NewRecorder()
	server.librarySearch(recorder, libraryRequest(t, token, target))
	if recorder.Code != http.StatusOK {
		t.Fatalf("缓存命中 status = %d", recorder.Code)
	}
	if got := atomic.LoadInt32(calls); got != 1 {
		t.Fatalf("上游调用次数 = %d, want 1", got)
	}
}

func TestLibrarySearchGraduateSharesFeature(t *testing.T) {
	upstream, _, _ := newLibraryUpstream(t, libraryFixture(t, "search_handoff.json"), nil)
	server, token := newLibraryTestServer(t, upstream.URL, "graduate")
	recorder := httptest.NewRecorder()
	server.librarySearch(recorder, libraryRequest(t, token, "/api/library/search?q="+url.QueryEscape("高等数学")))
	if recorder.Code != http.StatusOK {
		t.Fatalf("研究生查询 status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
}

func TestLibrarySearchInputValidation(t *testing.T) {
	upstream, _, _ := newLibraryUpstream(t, libraryFixture(t, "search_handoff.json"), nil)
	server, token := newLibraryTestServer(t, upstream.URL, "undergraduate")
	cases := []string{
		"/api/library/search",
		"/api/library/search?q=" + url.QueryEscape("数学") + "&field=subject",
		"/api/library/search?q=" + url.QueryEscape("数学") + "&page=0",
		"/api/library/search?q=" + url.QueryEscape("数学") + "&page=" + strconv.Itoa(library.MaxPage+1),
		"/api/library/search?q=" + url.QueryEscape(strings.Repeat("书", 81)),
	}
	for _, target := range cases {
		recorder := httptest.NewRecorder()
		server.librarySearch(recorder, libraryRequest(t, token, target))
		if recorder.Code != http.StatusBadRequest {
			t.Fatalf("%s status = %d, want 400 (%s)", target, recorder.Code, recorder.Body.String())
		}
	}
}

func TestLibrarySearchStaleFallbackAndNoCacheError(t *testing.T) {
	upstream, calls, failing := newLibraryUpstream(t, libraryFixture(t, "search_handoff.json"), nil)
	server, token := newLibraryTestServer(t, upstream.URL, "undergraduate")
	target := "/api/library/search?q=" + url.QueryEscape("高等数学")

	recorder := httptest.NewRecorder()
	server.librarySearch(recorder, libraryRequest(t, token, target))
	if recorder.Code != http.StatusOK {
		t.Fatalf("首次查询失败: %d %s", recorder.Code, recorder.Body.String())
	}

	// 把缓存改为“过期但在 24h 旧值宽限期内”，并让上游失败。
	key := "library:search:title:1:20:高等数学"
	server.cacheMu.Lock()
	entry := server.cache[key]
	entry.expiresAt = time.Now().Add(-time.Minute)
	server.cache[key] = entry
	server.cacheMu.Unlock()
	failing.Store(true)

	recorder = httptest.NewRecorder()
	server.librarySearch(recorder, libraryRequest(t, token, target))
	if recorder.Code != http.StatusOK {
		t.Fatalf("旧缓存回退 status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	var payload librarySearchPayload
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if !payload.Stale || payload.Total != 2582 || len(payload.Records) != 2 {
		t.Fatalf("旧缓存回退响应错误: %+v", payload)
	}
	if got := atomic.LoadInt32(calls); got != 2 {
		t.Fatalf("过期缓存应尝试上游刷新, calls = %d", got)
	}

	// 无缓存时上游失败必须明确报错，不能返回空结果冒充成功。
	delete(server.cache, "library:search:title:1:20:不存在")
	recorder = httptest.NewRecorder()
	server.librarySearch(recorder, libraryRequest(t, token, "/api/library/search?q="+url.QueryEscape("不存在")))
	if recorder.Code != http.StatusBadGateway {
		t.Fatalf("无缓存失败 status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	var failed struct {
		Success bool `json:"success"`
	}
	_ = json.Unmarshal(recorder.Body.Bytes(), &failed)
	if failed.Success {
		t.Fatal("失败响应不应包含 success=true")
	}
}

func TestLibraryItemCampusFilterAndCounts(t *testing.T) {
	upstream, _, _ := newLibraryUpstream(t, nil, libraryFixture(t, "item_handoff.html"))
	server, token := newLibraryTestServer(t, upstream.URL, "undergraduate")
	marcNo := "65743033384e4d567677433044795a4f5939463358413d3d"

	target := "/api/library/item?marc_no=" + url.QueryEscape(marcNo) + "&campus=jiangyin"
	recorder := httptest.NewRecorder()
	server.libraryItem(recorder, libraryRequest(t, token, target))
	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	var payload struct {
		Success      bool                 `json:"success"`
		MarcNo       string               `json:"marc_no"`
		Scope        string               `json:"scope"`
		Total        int                  `json:"total"`
		Available    int                  `json:"available"`
		CampusCounts library.CampusCounts `json:"campus_counts"`
		Copies       []library.Copy       `json:"copies"`
		Stale        bool                 `json:"stale"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if !payload.Success || payload.Scope != "jiangyin" || payload.Total != 2 || payload.Available != 2 || len(payload.Copies) != 2 {
		t.Fatalf("江阴过滤响应错误: %+v", payload)
	}
	for _, copy := range payload.Copies {
		if copy.Campus != "江阴" {
			t.Fatalf("过滤后明细混入其他校区: %+v", copy)
		}
	}
	if payload.CampusCounts.Nanjing != 2 || payload.CampusCounts.Jiangyin != 2 || payload.CampusCounts.Unknown != 1 {
		t.Fatalf("campus_counts 应为全量分布: %+v", payload.CampusCounts)
	}

	// 全部校区：统计与明细一致（5/5）。
	recorder = httptest.NewRecorder()
	server.libraryItem(recorder, libraryRequest(t, token, "/api/library/item?marc_no="+url.QueryEscape(marcNo)))
	if recorder.Code != http.StatusOK {
		t.Fatalf("全部校区 status = %d", recorder.Code)
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if payload.Scope != "all" || payload.Total != 5 || payload.Available != 5 {
		t.Fatalf("全部校区响应错误: %+v", payload)
	}

	// 非法校区/书目 ID 必须 400，不能透传为上游 URL。
	for _, target := range []string{
		"/api/library/item?marc_no=" + url.QueryEscape(marcNo) + "&campus=beijing",
		"/api/library/item?marc_no=abc",
		"/api/library/item?marc_no=" + url.QueryEscape("../../etc/passwd"),
	} {
		recorder = httptest.NewRecorder()
		server.libraryItem(recorder, libraryRequest(t, token, target))
		if recorder.Code != http.StatusBadRequest {
			t.Fatalf("%s status = %d, want 400", target, recorder.Code)
		}
	}
}

func TestLibraryItemUnknownStatusNotAvailable(t *testing.T) {
	upstream, _, _ := newLibraryUpstream(t, nil, libraryFixture(t, "item_unknown_status.html"))
	server, token := newLibraryTestServer(t, upstream.URL, "undergraduate")
	recorder := httptest.NewRecorder()
	server.libraryItem(recorder, libraryRequest(t, token,
		"/api/library/item?marc_no="+url.QueryEscape("QUJDREVGR0hJSktMTU5PUA==")))
	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	var payload struct {
		Total     int            `json:"total"`
		Available int            `json:"available"`
		Copies    []library.Copy `json:"copies"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if payload.Total != 5 || payload.Available != 1 {
		t.Fatalf("total/available = %d/%d, want 5/1（未知状态不得计可借）", payload.Total, payload.Available)
	}
}

func TestLibraryItemStaleFallback(t *testing.T) {
	upstream, _, failing := newLibraryUpstream(t, nil, libraryFixture(t, "item_handoff.html"))
	server, token := newLibraryTestServer(t, upstream.URL, "undergraduate")
	marcNo := "65743033384e4d567677433044795a4f5939463358413d3d"
	target := "/api/library/item?marc_no=" + url.QueryEscape(marcNo)

	recorder := httptest.NewRecorder()
	server.libraryItem(recorder, libraryRequest(t, token, target))
	if recorder.Code != http.StatusOK {
		t.Fatalf("首次馆藏失败: %d %s", recorder.Code, recorder.Body.String())
	}
	server.cacheMu.Lock()
	entry := server.cache["library:item:"+marcNo]
	entry.expiresAt = time.Now().Add(-time.Minute)
	server.cache["library:item:"+marcNo] = entry
	server.cacheMu.Unlock()
	failing.Store(true)

	recorder = httptest.NewRecorder()
	server.libraryItem(recorder, libraryRequest(t, token, target))
	if recorder.Code != http.StatusOK {
		t.Fatalf("旧馆藏回退失败: %d %s", recorder.Code, recorder.Body.String())
	}
	var payload struct {
		Stale  bool           `json:"stale"`
		Total  int            `json:"total"`
		Copies []library.Copy `json:"copies"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if !payload.Stale || payload.Total != 5 || len(payload.Copies) != 5 {
		t.Fatalf("旧馆藏回退响应错误: %+v", payload)
	}
}

func TestLibrarySearchSingleflight(t *testing.T) {
	slow := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(120 * time.Millisecond)
		w.Write(libraryFixture(t, "search_handoff.json"))
	}))
	t.Cleanup(slow.Close)
	server, token := newLibraryTestServer(t, slow.URL, "undergraduate")
	target := "/api/library/search?q=" + url.QueryEscape("高等数学")

	var wg sync.WaitGroup
	var okCount int32
	for i := 0; i < 4; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			recorder := httptest.NewRecorder()
			server.librarySearch(recorder, libraryRequest(t, token, target))
			if recorder.Code == http.StatusOK {
				atomic.AddInt32(&okCount, 1)
			}
		}()
	}
	wg.Wait()
	if got := atomic.LoadInt32(&okCount); got != 4 {
		t.Fatalf("并发请求成功数 = %d, want 4", got)
	}
	// 相同 key 只允许一次上游请求（单飞合并）；缓存/去重表均可能生效。
	server.cacheMu.Lock()
	_, cached := server.cache["library:search:title:1:20:高等数学"]
	server.cacheMu.Unlock()
	if !cached {
		t.Fatal("并发完成后应已写入共享缓存")
	}
}

func TestLibrarySearchRateLimit(t *testing.T) {
	upstream, _, _ := newLibraryUpstream(t, libraryFixture(t, "search_handoff.json"), nil)
	server, token := newLibraryTestServer(t, upstream.URL, "undergraduate")
	target := "/api/library/search?q=" + url.QueryEscape("高等数学")
	status := 0
	for i := 0; i < librarySearchPerMin+1; i++ {
		recorder := httptest.NewRecorder()
		server.librarySearch(recorder, libraryRequest(t, token, target))
		status = recorder.Code
	}
	if status != http.StatusTooManyRequests {
		t.Fatalf("超过限流阈值 status = %d, want 429", status)
	}
}

// TestLibraryUpstreamConcurrencyLimit 验证不同 key 的并发请求受 librarySlots 限制：
// 第一个请求占用唯一槽位并阻塞在上游时，第二个请求不得同时进入上游；释放后两者都成功。
func TestLibraryUpstreamConcurrencyLimit(t *testing.T) {
	firstStarted := make(chan struct{})
	release := make(chan struct{})
	var started int32
	fixture := libraryFixture(t, "search_handoff.json")
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n := atomic.AddInt32(&started, 1)
		if n == 1 {
			close(firstStarted)
		}
		<-release
		w.Header().Set("Content-Type", "application/json")
		w.Write(fixture)
	}))
	t.Cleanup(upstream.Close)

	server, token := newLibraryTestServer(t, upstream.URL, "undergraduate")
	server.librarySlots = make(chan struct{}, 1)

	var wg sync.WaitGroup
	do := func(keyword string) {
		defer wg.Done()
		recorder := httptest.NewRecorder()
		server.librarySearch(recorder, libraryRequest(t, token, "/api/library/search?q="+url.QueryEscape(keyword)))
		if recorder.Code != http.StatusOK {
			t.Errorf("%s status = %d, body=%s", keyword, recorder.Code, recorder.Body.String())
		}
	}
	wg.Add(1)
	go do("高等数学")
	select {
	case <-firstStarted:
	case <-time.After(3 * time.Second):
		t.Fatal("首个上游请求未开始")
	}
	wg.Add(1)
	go do("线性代数")
	time.Sleep(150 * time.Millisecond)
	if got := atomic.LoadInt32(&started); got != 1 {
		t.Fatalf("槽位=1 时上游并发 = %d, want 1（第二个请求应排队）", got)
	}
	close(release)
	wg.Wait()
	if got := atomic.LoadInt32(&started); got != 2 {
		t.Fatalf("释放后上游请求数 = %d, want 2", got)
	}
}
