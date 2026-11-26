package httpapi

import (
	"bytes"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"github.com/resetinging/njust-schedule/internal/jwc"
	"github.com/resetinging/njust-schedule/internal/session"
)

const tokenHeader = "X-Auth-Token"

var beijing = time.FixedZone("Asia/Shanghai", 8*60*60)

var semesterInputPattern = regexp.MustCompile(`^([0-9]{4})[-/]([0-9]{4})\s*(?:-([12])|(?:学年)?\s*(?:第([一二])|([秋春])季?)学期)$`)

func decodeJSON(r *http.Request, target any) error {
	const maxBody = 2 << 20
	raw, err := io.ReadAll(io.LimitReader(r.Body, maxBody+1))
	if err != nil {
		return fmt.Errorf("读取请求数据失败: %w", err)
	}
	if len(raw) > maxBody {
		return errors.New("请求数据超过 2MB")
	}
	if len(bytes.TrimSpace(raw)) == 0 {
		return nil
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	if err := decoder.Decode(target); err != nil {
		return fmt.Errorf("请求数据格式错误: %w", err)
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		return errors.New("请求数据包含多余内容")
	}
	return nil
}

func (s *Server) session(r *http.Request) (*session.Session, bool) {
	return s.sessions.Get(r.Context(), strings.TrimSpace(r.Header.Get(tokenHeader)))
}

func (s *Server) requireSession(w http.ResponseWriter, r *http.Request) (*session.Session, bool) {
	value, ok := s.session(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "尚未登录，请先登录")
		return nil, false
	}
	return value, true
}

func currentSemesterAt(now time.Time) string {
	now = now.In(beijing)
	year, month, day := now.Date()
	if month >= time.September || (month == time.August && day >= 20) {
		return fmt.Sprintf("%d-%d-1", year, year+1)
	}
	if month >= time.February {
		return fmt.Sprintf("%d-%d-2", year-1, year)
	}
	return fmt.Sprintf("%d-%d-1", year-1, year)
}

func currentSemester() string { return currentSemesterAt(time.Now()) }

func semesterList() []string {
	return semesterListAt(time.Now())
}

func semesterListAt(now time.Time) []string {
	current := currentSemesterAt(now)
	parts := strings.Split(current, "-")
	year, _ := strconv.Atoi(parts[0])
	currentTerm, _ := strconv.Atoi(parts[2])
	out := make([]string, 0, 14)
	for value := year; value >= year-6; value-- {
		for _, term := range []int{2, 1} {
			if value == year && term > currentTerm {
				continue
			}
			out = append(out, fmt.Sprintf("%d-%d-%d", value, value+1, term))
		}
	}
	return out
}

func randomToken(bytes int) string {
	value := make([]byte, bytes)
	if _, err := rand.Read(value); err != nil {
		return randomID()
	}
	return base64.RawURLEncoding.EncodeToString(value)
}

func parseInt(raw string, fallback, minValue, maxValue int) int {
	value, err := strconv.Atoi(strings.TrimSpace(raw))
	if err != nil {
		value = fallback
	}
	if value < minValue {
		value = minValue
	}
	if value > maxValue {
		value = maxValue
	}
	return value
}

func parseStringList(raw string, limit, itemLimit int) ([]string, error) {
	if strings.TrimSpace(raw) == "" {
		return nil, nil
	}
	if len(raw) > 32*1024 {
		return nil, errors.New("查询条件过长")
	}
	var values []string
	if err := json.Unmarshal([]byte(raw), &values); err != nil {
		values = []string{raw}
	}
	seen := map[string]bool{}
	out := make([]string, 0, len(values))
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value == "" {
			continue
		}
		if !validText(value, itemLimit) {
			return nil, errors.New("查询条件格式无效或过长")
		}
		if seen[value] {
			continue
		}
		seen[value] = true
		out = append(out, value)
		if len(out) >= limit {
			break
		}
	}
	return out, nil
}

func validText(value string, maxRunes int) bool {
	if !utf8.ValidString(value) || utf8.RuneCountInString(value) > maxRunes {
		return false
	}
	for _, r := range value {
		if unicode.IsControl(r) {
			return false
		}
	}
	return true
}

func normalizeSemester(value string, allowAll bool) (string, bool) {
	value = strings.TrimSpace(value)
	if allowAll && value == "__all__" {
		return value, true
	}
	if !validText(value, 32) {
		return "", false
	}
	parts := semesterInputPattern.FindStringSubmatch(value)
	if parts == nil {
		return "", false
	}
	first, firstErr := strconv.Atoi(parts[1])
	second, secondErr := strconv.Atoi(parts[2])
	if firstErr != nil || secondErr != nil || first < 2000 || first > 2100 || second != first+1 {
		return "", false
	}
	term := parts[3]
	if term == "" {
		switch {
		case parts[4] == "一":
			term = "1"
		case parts[4] == "二":
			term = "2"
		case parts[5] == "秋":
			term = "1"
		case parts[5] == "春":
			term = "2"
		default:
			return "", false
		}
	}
	return strconv.Itoa(first) + "-" + strconv.Itoa(second) + "-" + term, true
}

func validSemester(value string, allowAll bool) bool {
	_, ok := normalizeSemester(value, allowAll)
	return ok
}

func normalizeSemesterList(values []string) []string {
	out := make([]string, 0, len(values))
	seen := map[string]bool{}
	for _, value := range values {
		normalized, ok := normalizeSemester(value, false)
		if !ok || seen[normalized] {
			continue
		}
		seen[normalized] = true
		out = append(out, normalized)
	}
	return out
}

func validStudentID(value string) bool {
	value = strings.TrimSpace(value)
	if len(value) < 4 || len(value) > 32 {
		return false
	}
	for _, r := range value {
		if !(r >= '0' && r <= '9' || r >= 'A' && r <= 'Z' || r >= 'a' && r <= 'z' || r == '-' || r == '_') {
			return false
		}
	}
	return true
}

func validISODate(value string) bool {
	if len(value) != len("2006-01-02") {
		return false
	}
	parsed, err := time.Parse("2006-01-02", value)
	return err == nil && parsed.Year() >= 2000 && parsed.Year() <= 2100
}

// cacheGet 只返回新鲜值。普通缓存（retention==expiresAt）过期即删除；
// 带 stale retention 的条目在新鲜期结束后只返回 miss，但保留给 cacheLookup/cleanup，
// 不能因为一次 fresh-only 读取就把仍可回退的旧缓存删掉。
func (s *Server) cacheGet(key string) (any, bool) {
	s.cacheMu.Lock()
	defer s.cacheMu.Unlock()
	item, ok := s.cache[key]
	if !ok {
		return nil, false
	}
	now := time.Now()
	if now.Before(item.expiresAt) {
		return item.value, true
	}
	if now.Before(cacheDeadline(item)) {
		return nil, false
	}
	delete(s.cache, key)
	return nil, false
}

func (s *Server) cacheSet(key string, value any, ttl time.Duration) {
	s.cacheStore(key, value, ttl, 0)
}

// cacheSetRetained 用于“上游失败可回退旧缓存”的功能：
// retainTTL 从新鲜期结束时刻开始计算（例如 fresh=30m, retain=24h → 总保留 24h30m）。
func (s *Server) cacheSetRetained(key string, value any, freshTTL, retainTTL time.Duration) {
	s.cacheStore(key, value, freshTTL, retainTTL)
}

func (s *Server) cacheStore(key string, value any, freshTTL, retainTTL time.Duration) {
	s.cacheMu.Lock()
	defer s.cacheMu.Unlock()
	if s.cache == nil {
		s.cache = map[string]cacheEntry{}
	}
	now := time.Now()
	expiresAt := now.Add(freshTTL)
	retainUntil := expiresAt
	if retainTTL > 0 {
		retainUntil = expiresAt.Add(retainTTL)
	}
	// 覆盖同 key 时整体替换，不保留旧值的 stale 期限。
	s.cache[key] = cacheEntry{value: value, expiresAt: expiresAt, retainUntil: retainUntil, storedAt: now}
	s.evictCacheLocked(now)
}

func cacheDeadline(item cacheEntry) time.Time {
	if !item.retainUntil.IsZero() {
		return item.retainUntil
	}
	return item.expiresAt
}

// evictCacheLocked 保证真正有界：插入超过上限时做一次线性扫描，优先淘汰 retention
// 已结束的条目；若都未结束，再淘汰最旧 storedAt 的 1 项（FIFO，O(n)，无需分配/排序）。
// 替换同 key 不增加容量。
// 注意：容量压力下可淘汰仍在 stale retention 内的最旧条目；这与“cleanup/读取不会仅因
// 过 fresh 期而删除 retained 项”是两条独立不变量。
func (s *Server) evictCacheLocked(now time.Time) {
	for len(s.cache) > cacheMaxEntries {
		oldestKey := ""
		var oldestStored time.Time
		expiredKey := ""
		for key, item := range s.cache {
			if now.After(cacheDeadline(item)) {
				if expiredKey == "" {
					expiredKey = key
				}
				continue
			}
			if oldestKey == "" || item.storedAt.Before(oldestStored) {
				oldestKey = key
				oldestStored = item.storedAt
			}
		}
		if expiredKey != "" {
			delete(s.cache, expiredKey)
			continue
		}
		if oldestKey == "" {
			return
		}
		delete(s.cache, oldestKey)
	}
}

// cacheLookup 读取缓存并区分「新鲜」与「过期但仍在 retention 宽限期内」。
// 宽限期由 cacheSetRetained 在写入时决定，避免 cleanup 与读取对 stale 的期限理解不一致。
func (s *Server) cacheLookup(key string) (any, bool, time.Time, bool) {
	s.cacheMu.Lock()
	defer s.cacheMu.Unlock()
	item, ok := s.cache[key]
	if !ok {
		return nil, false, time.Time{}, false
	}
	now := time.Now()
	if now.After(cacheDeadline(item)) {
		delete(s.cache, key)
		return nil, false, time.Time{}, false
	}
	return item.value, now.Before(item.expiresAt), item.storedAt, true
}

func (s *Server) cacheDeletePrefix(prefix string) {
	s.cacheMu.Lock()
	defer s.cacheMu.Unlock()
	for key := range s.cache {
		if strings.HasPrefix(key, prefix) {
			delete(s.cache, key)
		}
	}
}

func (s *Server) rateLimited(key string, limit int, window time.Duration) bool {
	now := time.Now()
	cutoff := now.Add(-window)
	s.rateMu.Lock()
	defer s.rateMu.Unlock()
	if s.rates == nil {
		s.rates = map[string][]time.Time{}
	}
	values := s.rates[key]
	first := 0
	for first < len(values) && values[first].Before(cutoff) {
		first++
	}
	values = append(values[first:], now)
	s.rates[key] = values
	return len(values) > limit
}

func (s *Server) attemptsExceeded(key string, limit int, window time.Duration) bool {
	now := time.Now()
	cutoff := now.Add(-window)
	s.rateMu.Lock()
	defer s.rateMu.Unlock()
	values := s.rates[key]
	first := 0
	for first < len(values) && values[first].Before(cutoff) {
		first++
	}
	values = values[first:]
	if len(values) == 0 {
		delete(s.rates, key)
	} else {
		s.rates[key] = values
	}
	return len(values) >= limit
}

func (s *Server) recordFailedAttempt(keys ...string) {
	now := time.Now()
	s.rateMu.Lock()
	for _, key := range keys {
		s.rates[key] = append(s.rates[key], now)
	}
	s.rateMu.Unlock()
}

func (s *Server) clearAttempts(keys ...string) {
	s.rateMu.Lock()
	for _, key := range keys {
		delete(s.rates, key)
	}
	s.rateMu.Unlock()
}

func (s *Server) clientIP(r *http.Request) string {
	parts := strings.Split(r.Header.Get("X-Forwarded-For"), ",")
	forwarded := make([]string, 0, len(parts))
	for _, part := range parts {
		value := strings.TrimSpace(part)
		if net.ParseIP(value) != nil {
			forwarded = append(forwarded, value)
		}
	}
	if len(forwarded) > 0 {
		index := max(0, len(forwarded)-s.cfg.TrustedProxyHops)
		return forwarded[index]
	}
	if value := strings.TrimSpace(r.Header.Get("X-Real-IP")); net.ParseIP(value) != nil {
		return value
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err == nil {
		return host
	}
	return r.RemoteAddr
}

func mapJWCError(w http.ResponseWriter, err error, fallback string) {
	switch {
	case errors.Is(err, jwc.ErrSessionExpired):
		writeError(w, http.StatusUnauthorized, "教务会话已失效，请重新登录")
	case errors.Is(err, jwc.ErrCaptchaRequired):
		writeError(w, http.StatusUnauthorized, "智慧理工要求验证码，请改用二维码登录")
	default:
		if fallback == "" {
			fallback = "教务请求失败，请稍后重试"
		}
		writeError(w, http.StatusBadGateway, fallback)
	}
}

func (s *Server) semesterFor(r *http.Request, sess *session.Session) string {
	if value := strings.TrimSpace(r.URL.Query().Get("semester")); value != "" {
		if normalized, ok := normalizeSemester(value, false); ok {
			return normalized
		}
		return currentSemester()
	}
	value, err := s.store.UserSetting(r.Context(), sess.StudentID, "semester")
	if err != nil && s.logger != nil {
		s.logger.Warn("读取当前学期失败，使用系统学期", "sid_prefix", maskedSID(sess.StudentID), "error", err)
	}
	if normalized, ok := normalizeSemester(value, false); ok {
		return normalized
	}
	return currentSemester()
}
