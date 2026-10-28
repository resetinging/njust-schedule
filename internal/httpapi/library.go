package httpapi

import (
	"context"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/resetinging/njust-schedule/internal/library"
)

// 图书馆公共馆藏：匿名只读上游，全体登录用户共享同一份按 key 的缓存。
// 上游书目是公开数据，不含用户凭据；仍要求本服务登录后才可访问，避免被当作公开代理滥用。
const (
	librarySearchTTL    = 30 * time.Minute // 书目检索：新鲜 30 分钟
	libraryItemTTL      = 5 * time.Minute  // 单本馆藏：新鲜 5 分钟
	libraryStaleTTL     = 24 * time.Hour   // 上游失败时可回退的旧缓存宽限期（不等于新鲜期）
	librarySearchPerMin = 40
	libraryItemPerMin   = 80
)

type librarySearchResponse struct {
	Success   bool             `json:"success"`
	Field     string           `json:"field"`
	Query     string           `json:"query"`
	Page      int              `json:"page"`
	PageSize  int              `json:"page_size"`
	Total     int              `json:"total"`
	HasMore   bool             `json:"has_more"`
	Records   []library.Record `json:"records"`
	Stale     bool             `json:"stale"`
	UpdatedAt int64            `json:"updated_at"`
}

type libraryItemResponse struct {
	Success      bool                 `json:"success"`
	MarcNo       string               `json:"marc_no"`
	Scope        string               `json:"scope"`
	Total        int                  `json:"total"`
	Available    int                  `json:"available"`
	CampusCounts library.CampusCounts `json:"campus_counts"`
	Copies       []library.Copy       `json:"copies"`
	Stale        bool                 `json:"stale"`
	UpdatedAt    int64                `json:"updated_at"`
}

// librarySearch 处理 GET /api/library/search?field=title&q=高等数学&page=1
func (s *Server) librarySearch(w http.ResponseWriter, r *http.Request) {
	if _, ok := s.requireSession(w, r); !ok {
		return
	}
	client := s.libraryClient()
	if client == nil {
		writeError(w, http.StatusServiceUnavailable, "图书馆服务未配置")
		return
	}
	if s.rateLimited("library:search:"+s.clientIP(r), librarySearchPerMin, time.Minute) {
		writeError(w, http.StatusTooManyRequests, "查询过于频繁，请稍后再试")
		return
	}

	query := r.URL.Query()
	fieldKey := strings.TrimSpace(query.Get("field"))
	if fieldKey == "" {
		fieldKey = "title"
	}
	field, ok := library.FieldByKey(fieldKey)
	if !ok {
		writeError(w, http.StatusBadRequest, "不支持的检索字段")
		return
	}
	keyword, err := library.ValidateKeyword(query.Get("q"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "请输入 1-80 个字符的检索关键词")
		return
	}
	page, pageErr := parseLibraryPageParam(query.Get("page"), 1, library.MaxPage)
	pageSize, sizeErr := parseLibraryPageParam(query.Get("page_size"), library.DefaultPageSize, library.MaxPageSize)
	if pageErr != nil || sizeErr != nil {
		writeError(w, http.StatusBadRequest, "分页参数不合法")
		return
	}
	if err := library.ValidatePage(page, pageSize); err != nil {
		writeError(w, http.StatusBadRequest, "分页参数不合法")
		return
	}

	cacheKey := fmt.Sprintf("library:search:%s:%d:%d:%s", field.Key, page, pageSize, keyword)
	if value, fresh, storedAt, ok := s.cacheLookup(cacheKey, libraryStaleTTL); ok && fresh {
		if result, ok := value.(library.SearchResult); ok {
			writeJSON(w, http.StatusOK, buildLibrarySearchResponse(result, field.Key, keyword, false, storedAt))
			return
		}
	}

	result, err := doOnceValue(r.Context(), s, cacheKey, func(ctx context.Context) (library.SearchResult, error) {
		release, err := s.acquireLibrarySlot(ctx)
		if err != nil {
			return library.SearchResult{}, err
		}
		defer release()
		res, err := client.Search(ctx, library.Query{Field: field, Keyword: keyword, Page: page, PageSize: pageSize})
		if err != nil {
			return library.SearchResult{}, err
		}
		s.cacheSet(cacheKey, res, librarySearchTTL)
		return res, nil
	})
	if err != nil {
		// 上游失败：有旧缓存则回退并标记 stale；无缓存明确报错，绝不返回空结果冒充成功。
		if value, _, storedAt, ok := s.cacheLookup(cacheKey, libraryStaleTTL); ok {
			if staleResult, ok := value.(library.SearchResult); ok {
				s.logger.Warn("图书馆检索失败，返回旧缓存", "field", field.Key, "page", page)
				writeJSON(w, http.StatusOK, buildLibrarySearchResponse(staleResult, field.Key, keyword, true, storedAt))
				return
			}
		}
		s.logger.Warn("图书馆检索失败", "field", field.Key, "page", page, "error", err)
		writeError(w, http.StatusBadGateway, "图书馆检索服务暂时不可用，请稍后再试")
		return
	}
	storedAt := time.Now()
	if _, _, cachedStoredAt, ok := s.cacheLookup(cacheKey, libraryStaleTTL); ok {
		storedAt = cachedStoredAt
	}
	writeJSON(w, http.StatusOK, buildLibrarySearchResponse(result, field.Key, keyword, false, storedAt))
}

// libraryItem 处理 GET /api/library/item?marc_no=...&campus=all|nanjing|jiangyin
func (s *Server) libraryItem(w http.ResponseWriter, r *http.Request) {
	if _, ok := s.requireSession(w, r); !ok {
		return
	}
	client := s.libraryClient()
	if client == nil {
		writeError(w, http.StatusServiceUnavailable, "图书馆服务未配置")
		return
	}
	if s.rateLimited("library:item:"+s.clientIP(r), libraryItemPerMin, time.Minute) {
		writeError(w, http.StatusTooManyRequests, "查询过于频繁，请稍后再试")
		return
	}

	query := r.URL.Query()
	marcNo, err := library.ValidateMarcNo(query.Get("marc_no"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "书目编号不合法")
		return
	}
	scope := strings.TrimSpace(query.Get("campus"))
	if scope == "" {
		scope = "all"
	}
	if scope != "all" && scope != "nanjing" && scope != "jiangyin" {
		writeError(w, http.StatusBadRequest, "校区筛选不合法")
		return
	}

	cacheKey := "library:item:" + marcNo
	load := func(ctx context.Context) (library.Inventory, error) {
		if value, fresh, _, ok := s.cacheLookup(cacheKey, libraryStaleTTL); ok && fresh {
			if inventory, ok := value.(library.Inventory); ok {
				return inventory, nil
			}
		}
		return doOnceValue(ctx, s, cacheKey, func(fetchCtx context.Context) (library.Inventory, error) {
			release, err := s.acquireLibrarySlot(fetchCtx)
			if err != nil {
				return library.Inventory{}, err
			}
			defer release()
			inventory, err := client.Item(fetchCtx, marcNo)
			if err != nil {
				return library.Inventory{}, err
			}
			s.cacheSet(cacheKey, inventory, libraryItemTTL)
			return inventory, nil
		})
	}

	inventory, err := load(r.Context())
	if err != nil {
		if value, _, storedAt, ok := s.cacheLookup(cacheKey, libraryStaleTTL); ok {
			if staleInventory, ok := value.(library.Inventory); ok {
				s.logger.Warn("图书馆馆藏请求失败，返回旧缓存", "marc_no", marcNo)
				s.writeLibraryItem(w, staleInventory, scope, true, storedAt)
				return
			}
		}
		s.logger.Warn("图书馆馆藏请求失败", "marc_no", marcNo, "error", err)
		writeError(w, http.StatusBadGateway, "图书馆馆藏服务暂时不可用，请稍后再试")
		return
	}
	// 成功返回（缓存命中或刚刚抓取成功）都视为新鲜数据；仅在缓存被并发淘汰时用当前时间兜底。
	storedAt := time.Now()
	if _, _, cachedStoredAt, ok := s.cacheLookup(cacheKey, libraryStaleTTL); ok {
		storedAt = cachedStoredAt
	}
	s.writeLibraryItem(w, inventory, scope, false, storedAt)
}

func (s *Server) writeLibraryItem(w http.ResponseWriter, inventory library.Inventory, scope string, stale bool, storedAt time.Time) {
	filtered, err := inventory.FilterCampus(scope)
	if err != nil {
		writeError(w, http.StatusBadRequest, "校区筛选不合法")
		return
	}
	if storedAt.IsZero() {
		storedAt = time.Now()
	}
	writeJSON(w, http.StatusOK, libraryItemResponse{
		Success: true, MarcNo: inventory.MarcNo, Scope: scope,
		Total: filtered.Total, Available: filtered.Available,
		CampusCounts: inventory.CampusCounts(), Copies: filtered.Copies,
		Stale: stale, UpdatedAt: storedAt.Unix(),
	})
}

func buildLibrarySearchResponse(result library.SearchResult, field, keyword string, stale bool, storedAt time.Time) librarySearchResponse {
	if storedAt.IsZero() {
		storedAt = time.Now()
	}
	if result.Records == nil {
		result.Records = []library.Record{}
	}
	return librarySearchResponse{
		Success: true, Field: field, Query: keyword,
		Page: result.Page, PageSize: result.PageSize, Total: result.Total,
		HasMore: result.Page*result.PageSize < result.Total,
		Records: result.Records, Stale: stale, UpdatedAt: storedAt.Unix(),
	}
}

func (s *Server) libraryClient() *library.Client {
	if s.library == nil {
		return nil
	}
	return s.library
}

// acquireLibrarySlot 限制对上游的并发；测试/未初始化时退化为不限制。
func (s *Server) acquireLibrarySlot(ctx context.Context) (func(), error) {
	if s.librarySlots == nil {
		return func() {}, nil
	}
	select {
	case s.librarySlots <- struct{}{}:
		return func() { <-s.librarySlots }, nil
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

// parseLibraryPageParam 严格解析分页参数：缺失用默认值；显式非法一律报错，不静默回退。
func parseLibraryPageParam(raw string, fallback, maxValue int) (int, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return fallback, nil
	}
	value, err := strconv.Atoi(raw)
	if err != nil || value < 1 || value > maxValue {
		return 0, fmt.Errorf("invalid page param")
	}
	return value, nil
}
