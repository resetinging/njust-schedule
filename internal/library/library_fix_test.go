package library

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func searchBody(total, count int) []byte {
	if count <= 0 {
		return []byte(fmt.Sprintf(`{"total":%d,"content":[]}`, total))
	}
	items := make([]string, 0, count)
	for index := 0; index < count; index++ {
		items = append(items, fmt.Sprintf(
			`{"marcRecNo":"QUJDREVGR0hJSktMTU5PUA%02d","title":"T%d"}`,
			index, index+1,
		))
	}
	return []byte(fmt.Sprintf(`{"total":%d,"content":[%s]}`, total, strings.Join(items, ",")))
}

func newPagedSearchServer(t *testing.T, total int) (*httptest.Server, *[]int) {
	t.Helper()
	pageCounts := make([]int, 0, 4)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		var request struct {
			PageCount int `json:"pageCount"`
			PageSize  int `json:"pageSize"`
		}
		_ = json.Unmarshal(raw, &request)
		pageCounts = append(pageCounts, request.PageCount)
		offset := (request.PageCount - 1) * request.PageSize
		count := 0
		if offset < total {
			count = total - offset
			if count > request.PageSize {
				count = request.PageSize
			}
			// 交接 fixture 允许部分采样；测试也返回部分页以验证 offset+len<=total，而不是每页都塞满。
			if count > 2 {
				count = 2
			}
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(searchBody(total, count))
	}))
	t.Cleanup(server.Close)
	return server, &pageCounts
}

// HTTP 200 但结构/类型不合法时，绝不能被当作合法空结果缓存。
func TestSearchRejectsMalformedSuccessBodies(t *testing.T) {
	validMarc := "65743033384e4d567677433044795a4f5939463358413d3d"
	cases := map[string]string{
		"空对象":          `{}`,
		"JSON null":    `null`,
		"纯 message":    `{"message":"upstream unavailable"}`,
		"缺 content":    `{"total":12}`,
		"content null": `{"total":12,"content":null}`,
		"total 字符串":    `{"total":"12","content":[]}`,
		"total 负数":     `{"total":-1,"content":[]}`,
		"total 非零但首页空": `{"total":12,"content":[]}`,
		"total 零但非空":   `{"total":0,"content":[{"marcRecNo":"QUJDREVGR0hJSktMTU5PUA==","title":"x"}]}`,
		"content 对象":   `{"total":0,"content":{}}`,
		"记录缺标题":        `{"total":0,"content":[{"marcRecNo":"` + validMarc + `"}]}`,
		"记录缺 marc":     `{"total":0,"content":[{"title":"x"}]}`,
		"记录 num 负数":    `{"total":0,"content":[{"marcRecNo":"` + validMarc + `","title":"x","num":-1}]}`,
	}
	for name, body := range cases {
		t.Run(name, func(t *testing.T) {
			upstream, _ := newUpstream(t, []byte(body), nil, 0)
			result, err := testClient(upstream).Search(context.Background(), Query{
				Field: Fields[0], Keyword: "高等数学", Page: 1, PageSize: 20,
			})
			if err == nil {
				t.Fatalf("非法响应被接受: total=%d records=%d body=%s", result.Total, len(result.Records), body)
			}
		})
	}
}

func TestSearchAcceptsCanonicalEmptyAndNonEmpty(t *testing.T) {
	empty := []byte(`{"total":0,"content":[]}`)
	upstream, _ := newUpstream(t, empty, nil, 0)
	result, err := testClient(upstream).Search(context.Background(), Query{
		Field: Fields[0], Keyword: "没有结果", Page: 1, PageSize: 20,
	})
	if err != nil || result.Total != 0 || len(result.Records) != 0 {
		t.Fatalf("合法空结果被拒绝: result=%+v err=%v", result, err)
	}

	nonEmpty := []byte(`{"total":2582,"content":[{"author":"主编杨海涛","callNo":"O13/797/V.1","docTypeName":"中文图书","isbn":"978-7-5608-5255-3","marcRecNo":"65743033384e4d567677433044795a4f5939463358413d3d","num":1,"pubYear":"2013","publisher":"同济大学出版社","title":"高等数学:理工类.上册.第3版"}]}`)
	upstream2, _ := newUpstream(t, nonEmpty, nil, 0)
	result, err = testClient(upstream2).Search(context.Background(), Query{
		Field: Fields[0], Keyword: "高等数学", Page: 1, PageSize: 20,
	})
	if err != nil || result.Total != 2582 || len(result.Records) != 1 {
		t.Fatalf("合法非空结果被拒绝: result=%+v err=%v", result, err)
	}
}

func TestSearchTotalContentRange(t *testing.T) {
	cases := []struct {
		name    string
		page    int
		total   int
		count   int
		wantErr bool
	}{
		{name: "total=0 首页非空", page: 1, total: 0, count: 1, wantErr: true},
		{name: "content 长度超过 total", page: 1, total: 1, count: 2, wantErr: true},
		{name: "最后页溢出", page: 130, total: 2582, count: 3, wantErr: true},
		{name: "超出末页仍非空", page: 131, total: 2582, count: 1, wantErr: true},
		{name: "合法最后页", page: 130, total: 2582, count: 2, wantErr: false},
		{name: "合法空页", page: 131, total: 2582, count: 0, wantErr: false},
		{name: "fixture 部分采样合法", page: 1, total: 2582, count: 1, wantErr: false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			upstream, _ := newUpstream(t, searchBody(tc.total, tc.count), nil, 0)
			result, err := testClient(upstream).Search(context.Background(), Query{
				Field: Fields[0], Keyword: "高等数学", Page: tc.page, PageSize: DefaultPageSize,
			})
			if tc.wantErr {
				if err == nil {
					t.Fatalf("页码=%d total=%d count=%d 应拒绝，实际 result=%+v", tc.page, tc.total, tc.count, result)
				}
				return
			}
			if err != nil {
				t.Fatalf("合法响应被拒绝: %v", err)
			}
			if result.Total != tc.total || len(result.Records) != tc.count {
				t.Fatalf("结果不一致: %+v", result)
			}
		})
	}
}

func TestSearchRejectsContentLargerThanPageSize(t *testing.T) {
	upstream, _ := newUpstream(t, searchBody(2, 2), nil, 0)
	_, err := testClient(upstream).Search(context.Background(), Query{
		Field: Fields[0], Keyword: "数学", Page: 1, PageSize: 1,
	})
	if err == nil {
		t.Fatal("超过 pageSize 的 content 应被拒绝")
	}
}

func TestSearchMaxPageBoundary(t *testing.T) {
	if err := ValidatePage(MaxPage, DefaultPageSize); err != nil {
		t.Fatalf("MaxPage 应是合法页: %v", err)
	}
	if MaxPage <= 50 {
		t.Fatalf("MaxPage=%d 不足以覆盖真实总数 2582（默认 20 条/页需至少 130 页）", MaxPage)
	}
	if MaxPage*DefaultPageSize < 2582 {
		t.Fatalf("MaxPage*DefaultPageSize=%d 小于真实总数 2582", MaxPage*DefaultPageSize)
	}
	if err := ValidatePage(MaxPage+1, DefaultPageSize); err == nil {
		t.Fatal("MaxPage+1 必须被拒绝")
	}

	// 按请求 pageCount 生成真实末页：offset=3980 已超过 total=2582，合法响应是空页。
	upstream, pageCounts := newPagedSearchServer(t, 2582)
	result, err := testClient(upstream).Search(context.Background(), Query{
		Field: Fields[0], Keyword: "高等数学", Page: MaxPage, PageSize: DefaultPageSize,
	})
	if err != nil {
		t.Fatal(err)
	}
	if result.Page != MaxPage || result.Total != 2582 || len(result.Records) != 0 {
		t.Fatalf("末页结果错误: %+v", result)
	}
	if len(*pageCounts) != 1 || (*pageCounts)[0] != MaxPage {
		t.Fatalf("pageCounts=%v, want [%d]", *pageCounts, MaxPage)
	}
}
