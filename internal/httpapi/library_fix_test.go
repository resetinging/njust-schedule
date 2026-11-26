package httpapi

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/resetinging/njust-schedule/internal/library"
)

type librarySearchFields struct {
	Success   bool  `json:"success"`
	Page      int   `json:"page"`
	PageSize  int   `json:"page_size"`
	Total     int   `json:"total"`
	HasMore   bool  `json:"has_more"`
	Truncated bool  `json:"truncated"`
	MaxPage   int   `json:"max_page"`
	Stale     bool  `json:"stale"`
	Records   []any `json:"records"`
}

func decodeLibrarySearch(t *testing.T, body []byte) librarySearchFields {
	t.Helper()
	var payload librarySearchFields
	if err := json.Unmarshal(body, &payload); err != nil {
		t.Fatal(err)
	}
	return payload
}

func libraryPagedBody(total, count int) []byte {
	if count <= 0 {
		return []byte(fmt.Sprintf(`{"total":%d,"content":[]}`, total))
	}
	items := make([]string, 0, count)
	for index := 0; index < count; index++ {
		items = append(items, fmt.Sprintf(`{"marcRecNo":"QUJDREVGR0hJSktMTU5PUA%02d","title":"paged-%d"}`, index, index+1))
	}
	return []byte(fmt.Sprintf(`{"total":%d,"content":[%s]}`, total, strings.Join(items, ",")))
}

// 按请求的真实 pageCount 生成响应，避免用首页 fixture 冒充第 130/200 页。
func newPagedLibraryUpstream(t *testing.T, total int) (*httptest.Server, *[]*http.Request) {
	t.Helper()
	requests := make([]*http.Request, 0, 4)
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		requests = append(requests, r)
		var request struct {
			PageCount int `json:"pageCount"`
			PageSize  int `json:"pageSize"`
		}
		_ = json.Unmarshal(raw, &request)
		offset := (request.PageCount - 1) * request.PageSize
		count := 0
		if offset < total {
			count = total - offset
			if count > request.PageSize {
				count = request.PageSize
			}
			if count > 2 {
				count = 2
			}
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(libraryPagedBody(total, count))
	}))
	t.Cleanup(upstream.Close)
	return upstream, &requests
}

func TestLibrarySearchPaginationContract(t *testing.T) {
	upstream, _ := newPagedLibraryUpstream(t, 2582)
	server, token := newLibraryTestServer(t, upstream.URL, "undergraduate")

	call := func(page int) librarySearchFields {
		recorder := httptest.NewRecorder()
		server.librarySearch(recorder, libraryRequest(t, token,
			"/api/library/search?q="+url.QueryEscape("高等数学")+"&page="+fmt.Sprint(page)))
		if recorder.Code != http.StatusOK {
			t.Fatalf("page=%d status=%d body=%s", page, recorder.Code, recorder.Body.String())
		}
		return decodeLibrarySearch(t, recorder.Body.Bytes())
	}

	first := call(1)
	if !first.HasMore || first.Truncated || first.MaxPage != library.MaxPage || first.Total != 2582 || len(first.Records) != 2 {
		t.Fatalf("首页分页契约错误: %+v", first)
	}
	// 真实「高等数学」2582 条：第 130 页已覆盖全部，不应再请求第 131 页。
	final := call(130)
	if final.HasMore || final.Truncated || final.Total != 2582 || len(final.Records) != 2 {
		t.Fatalf("真实最终页契约错误: %+v", final)
	}
	// 最大可请求页：has_more 必须 false（请求下一页会被 400），但 total 保持真实。
	lastBoundary := call(library.MaxPage)
	if lastBoundary.HasMore || lastBoundary.Truncated || lastBoundary.Total != 2582 || len(lastBoundary.Records) != 0 {
		t.Fatalf("最大页边界契约错误: %+v", lastBoundary)
	}

	recorder := httptest.NewRecorder()
	server.librarySearch(recorder, libraryRequest(t, token,
		"/api/library/search?q="+url.QueryEscape("高等数学")+"&page="+fmt.Sprint(library.MaxPage+1)))
	if recorder.Code != http.StatusBadRequest {
		t.Fatalf("超过最大页应 400，实际 %d", recorder.Code)
	}
}

func TestLibrarySearchTruncatedAtMaxPage(t *testing.T) {
	upstream, _ := newPagedLibraryUpstream(t, 5000)
	server, token := newLibraryTestServer(t, upstream.URL, "undergraduate")
	call := func(page int) librarySearchFields {
		recorder := httptest.NewRecorder()
		server.librarySearch(recorder, libraryRequest(t, token,
			"/api/library/search?q=large&page="+fmt.Sprint(page)))
		if recorder.Code != http.StatusOK {
			t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
		}
		return decodeLibrarySearch(t, recorder.Body.Bytes())
	}
	mid := call(50)
	if !mid.HasMore || !mid.Truncated {
		t.Fatalf("总数为 5000 时应保留 truncated 并继续 has_more: %+v", mid)
	}
	last := call(library.MaxPage)
	if last.HasMore {
		t.Fatalf("最大页不可再声明 has_more: %+v", last)
	}
	if !last.Truncated {
		t.Fatalf("总数为 5000 超过可达上限时必须标记 truncated: %+v", last)
	}
	if last.Total != 5000 {
		t.Fatalf("必须保留真实 total=5000，实际 %+v", last)
	}
}

// 真实 cleanup 任务不能删除仍在 24h stale 宽限期的图书馆缓存；上游失败应能回退。
func TestLibraryStaleSurvivesRealCleanupThenUpstreamFailure(t *testing.T) {
	upstream, _, failing := newLibraryUpstream(t, nil, libraryFixture(t, "item_handoff.html"))
	server, token := newLibraryTestServer(t, upstream.URL, "undergraduate")
	marcNo := "65743033384e4d567677433044795a4f5939463358413d3d"
	target := "/api/library/item?marc_no=" + url.QueryEscape(marcNo)

	recorder := httptest.NewRecorder()
	server.libraryItem(recorder, libraryRequest(t, token, target))
	if recorder.Code != http.StatusOK {
		t.Fatalf("首次请求失败: %d %s", recorder.Code, recorder.Body.String())
	}
	key := "library:item:" + marcNo
	server.cacheMu.Lock()
	entry := server.cache[key]
	entry.expiresAt = time.Now().Add(-time.Minute)     // 新鲜期已过
	entry.retainUntil = time.Now().Add(23 * time.Hour) // 仍在 24h stale 宽限期
	server.cache[key] = entry
	server.cacheMu.Unlock()

	server.cleanupRuntimeState(context.Background())
	failing.Store(true)

	recorder = httptest.NewRecorder()
	server.libraryItem(recorder, libraryRequest(t, token, target))
	if recorder.Code != http.StatusOK {
		t.Fatalf("cleanup 后旧缓存回退失败: %d %s", recorder.Code, recorder.Body.String())
	}
	var payload struct {
		Stale bool `json:"stale"`
		Total int  `json:"total"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if !payload.Stale || payload.Total != 5 {
		t.Fatalf("cleanup 后未回退 stale 数据: %+v", payload)
	}
}

// HTTP200 错误结构不得覆盖已有可用旧缓存。
func TestLibraryMalformedUpstreamKeepsStaleCache(t *testing.T) {
	var malformed atomic.Bool
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if malformed.Load() {
			w.Header().Set("Content-Type", "application/json")
			w.Write([]byte(`{}`))
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write(libraryFixture(t, "search_handoff.json"))
	}))
	t.Cleanup(upstream.Close)
	server, token := newLibraryTestServer(t, upstream.URL, "undergraduate")
	target := "/api/library/search?q=" + url.QueryEscape("高等数学")

	recorder := httptest.NewRecorder()
	server.librarySearch(recorder, libraryRequest(t, token, target))
	if recorder.Code != http.StatusOK {
		t.Fatalf("首次请求失败: %d", recorder.Code)
	}
	key := "library:search:title:1:20:高等数学"
	server.cacheMu.Lock()
	entry := server.cache[key]
	entry.expiresAt = time.Now().Add(-time.Minute)
	entry.retainUntil = time.Now().Add(23 * time.Hour)
	server.cache[key] = entry
	server.cacheMu.Unlock()
	malformed.Store(true)

	recorder = httptest.NewRecorder()
	server.librarySearch(recorder, libraryRequest(t, token, target))
	if recorder.Code != http.StatusOK {
		t.Fatalf("错误结构应回退旧缓存，实际 status=%d body=%s", recorder.Code, recorder.Body.String())
	}
	payload := decodeLibrarySearch(t, recorder.Body.Bytes())
	if !payload.Stale || payload.Total != 2582 || len(payload.Records) != 2 {
		t.Fatalf("错误结构覆盖/丢失旧缓存: %+v", payload)
	}
}

func TestCacheBoundedCapacityAndReplacement(t *testing.T) {
	server := &Server{cache: map[string]cacheEntry{}}
	for i := 0; i < cacheMaxEntries+200; i++ {
		server.cacheSet(fmt.Sprintf("k:%d", i), i, time.Hour)
	}
	if len(server.cache) > cacheMaxEntries {
		t.Fatalf("缓存条目 %d 超过上限 %d", len(server.cache), cacheMaxEntries)
	}
	evictedOld := false
	for index := 0; index < 200; index++ {
		if _, ok := server.cacheGet(fmt.Sprintf("k:%d", index)); !ok {
			evictedOld = true
			break
		}
	}
	if !evictedOld {
		t.Fatal("超容量时应淘汰早期条目")
	}
	if _, ok := server.cacheGet(fmt.Sprintf("k:%d", cacheMaxEntries+199)); !ok {
		t.Fatal("最新条目不应被淘汰")
	}

	server.cacheSet("same", "old", time.Hour)
	server.cacheSet("same", "new", time.Hour)
	if got, ok := server.cacheGet("same"); !ok || got != "new" {
		t.Fatalf("同 key 替换失败: %v %v", got, ok)
	}
	if len(server.cache) > cacheMaxEntries {
		t.Fatalf("替换不应增加容量: %d", len(server.cache))
	}
}

func TestCacheCleanupPreservesStaleButDeletesLegacyExpired(t *testing.T) {
	server := &Server{cache: map[string]cacheEntry{}}
	server.cacheSetRetained("retained", "v", time.Minute, 24*time.Hour)
	server.cacheMu.Lock()
	entry := server.cache["retained"]
	entry.expiresAt = time.Now().Add(-time.Minute)
	server.cache["retained"] = entry
	server.cacheMu.Unlock()
	server.cacheSet("legacy", "v", -time.Second)

	server.cleanupRuntimeState(context.Background())
	if _, fresh, _, ok := server.cacheLookup("retained"); !ok || fresh {
		t.Fatalf("stale 条目不应被 cleanup 删除: ok=%v fresh=%v", ok, fresh)
	}
	if _, ok := server.cacheGet("legacy"); ok {
		t.Fatal("普通缓存过期后仍应被 cleanup 删除")
	}
}

func TestCacheGetFreshOnlyKeepsRetainedForStaleLookup(t *testing.T) {
	server := &Server{cache: map[string]cacheEntry{}}
	server.cacheSetRetained("retained", "v", time.Minute, 24*time.Hour)
	server.cacheMu.Lock()
	entry := server.cache["retained"]
	entry.expiresAt = time.Now().Add(-time.Minute)
	server.cache["retained"] = entry
	server.cacheMu.Unlock()

	if _, ok := server.cacheGet("retained"); ok {
		t.Fatal("fresh-only 读取在过期后应 miss")
	}
	if _, fresh, _, ok := server.cacheLookup("retained"); !ok || fresh {
		t.Fatalf("fresh-only 读取不得删除 retained 项: ok=%v fresh=%v", ok, fresh)
	}

	server.cacheMu.Lock()
	entry = server.cache["retained"]
	entry.retainUntil = time.Now().Add(-time.Second)
	server.cache["retained"] = entry
	server.cacheMu.Unlock()
	if _, _, _, ok := server.cacheLookup("retained"); ok {
		t.Fatal("retention 结束后 lookup 应删除并 miss")
	}
	if _, exists := server.cache["retained"]; exists {
		t.Fatal("retention 结束后条目应被删除")
	}

	// 普通缓存（无 stale retention）仍按原规则：fresh 过期后 cacheGet 直接删除。
	server.cacheSet("ordinary", "v", -time.Second)
	if _, ok := server.cacheGet("ordinary"); ok {
		t.Fatal("普通缓存过期后不应返回 fresh 值")
	}
	if _, exists := server.cache["ordinary"]; exists {
		t.Fatal("普通缓存过期后 cacheGet 应删除条目")
	}
}

func TestCacheExpiredRetentionDeletedByCleanupAndCapacity(t *testing.T) {
	server := &Server{cache: map[string]cacheEntry{}}
	server.cacheSetRetained("expired", "v", time.Minute, time.Minute)
	server.cacheMu.Lock()
	entry := server.cache["expired"]
	entry.retainUntil = time.Now().Add(-time.Second)
	server.cache["expired"] = entry
	server.cacheMu.Unlock()
	server.cleanupRuntimeState(context.Background())
	if _, exists := server.cache["expired"]; exists {
		t.Fatal("cleanup 应删除 retention 已结束条目")
	}

	// 容量扫描：先填满 fresh 条目，再放一个 retention 已结束但 storedAt 很新的条目；
	// 插入新 key 时应优先删除 expired，而不是只按最旧淘汰。
	server = &Server{cache: map[string]cacheEntry{}}
	for index := 0; index < cacheMaxEntries; index++ {
		server.cacheSet(fmt.Sprintf("fresh:%d", index), index, time.Hour)
	}
	server.cacheSetRetained("expired-newest", "v", time.Hour, time.Hour)
	server.cacheMu.Lock()
	entry = server.cache["expired-newest"]
	entry.retainUntil = time.Now().Add(-time.Second)
	server.cache["expired-newest"] = entry
	server.cacheMu.Unlock()
	server.cacheSet("new-key", "v", time.Hour)
	if _, exists := server.cache["expired-newest"]; exists {
		t.Fatal("容量扫描应优先删除 retention 已结束条目")
	}
	if len(server.cache) > cacheMaxEntries {
		t.Fatalf("容量扫描后 %d 超过上限", len(server.cache))
	}
}

func TestCacheConcurrentAccessStaysBounded(t *testing.T) {
	server := &Server{cache: map[string]cacheEntry{}}
	for index := 0; index < cacheMaxEntries; index++ {
		server.cacheSet(fmt.Sprintf("old:%d", index), index, time.Hour)
	}

	cacheLen := func() int {
		server.cacheMu.Lock()
		defer server.cacheMu.Unlock()
		return len(server.cache)
	}
	maxSeen := atomic.Int64{}
	maxSeen.Store(int64(cacheMaxEntries))

	var wg sync.WaitGroup
	for g := 0; g < 8; g++ {
		wg.Add(1)
		go func(g int) {
			defer wg.Done()
			for i := 0; i < 100; i++ {
				// 并发新 key 插入会持续触发容量淘汰（预填已满）。
				server.cacheSet(fmt.Sprintf("new:%d:%d", g, i), i, time.Hour)
				// 并发替换旧 key（同 key 不增加容量）。
				oldKey := fmt.Sprintf("old:%d", g*100+i)
				server.cacheSet(oldKey, i, time.Hour)
				_, _ = server.cacheGet(fmt.Sprintf("old:%d", 1000+i%100))
				_, _, _, _ = server.cacheLookup(oldKey)
				n := int64(cacheLen())
				for {
					current := maxSeen.Load()
					if n <= current || maxSeen.CompareAndSwap(current, n) {
						break
					}
				}
			}
		}(g)
	}
	wg.Wait()
	if maxSeen.Load() > int64(cacheMaxEntries) {
		t.Fatalf("并发过程中缓存条目曾达到 %d，超过上限 %d", maxSeen.Load(), cacheMaxEntries)
	}
	if len(server.cache) > cacheMaxEntries {
		t.Fatalf("并发后缓存条目 %d 超过上限", len(server.cache))
	}
	evictedOld := false
	for index := 800; index < 1600; index++ {
		if _, ok := server.cacheGet(fmt.Sprintf("old:%d", index)); !ok {
			evictedOld = true
			break
		}
	}
	if !evictedOld {
		t.Fatal("并发插入后未被替换的早期 old 项应被淘汰")
	}
	if _, ok := server.cacheGet("new:7:99"); !ok {
		t.Fatal("并发阶段最新插入的 new 项应保留")
	}
}
