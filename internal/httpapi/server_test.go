package httpapi

import (
	"bytes"
	"compress/gzip"
	"database/sql"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/naughtygopher/webgo/v7"
	"github.com/resetinging/njust-schedule/internal/config"
	"github.com/resetinging/njust-schedule/internal/jwc"
	"github.com/resetinging/njust-schedule/internal/session"
	"github.com/resetinging/njust-schedule/internal/store"
)

func testHandler(t *testing.T, server *Server) http.Handler {
	t.Helper()
	router := webgo.NewRouter(&webgo.Config{}, server.routes()...)
	return middleware(server.logger, server, router)
}

func TestClientIPUsesTrustedProxyHops(t *testing.T) {
	server := &Server{cfg: config.Config{TrustedProxyHops: 2}}
	request := httptest.NewRequest(http.MethodGet, "/", nil)
	request.RemoteAddr = "10.0.0.9:1234"
	request.Header.Set("X-Forwarded-For", "203.0.113.8, 10.0.0.7, 10.0.0.8")
	if got := server.clientIP(request); got != "10.0.0.7" {
		t.Fatalf("client IP = %q", got)
	}

	request.Header.Set("X-Forwarded-For", "forged, unknown")
	request.Header.Set("X-Real-IP", "198.51.100.9")
	if got := server.clientIP(request); got != "198.51.100.9" {
		t.Fatalf("fallback client IP = %q", got)
	}
}

func TestHealthContract(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	server := &Server{db: &sql.DB{}, logger: logger}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/healthz", nil)

	testHandler(t, server).ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	var payload map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if payload["ok"] != true || payload["service"] != "njust-schedule" {
		t.Fatalf("unexpected payload: %#v", payload)
	}
	if recorder.Header().Get("X-Request-ID") == "" {
		t.Fatal("missing X-Request-ID")
	}
	if recorder.Header().Get("X-Content-Type-Options") != "nosniff" {
		t.Fatalf("security headers = %#v", recorder.Header())
	}
}

func TestAdminTrailingSlashRedirects(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	server := &Server{logger: logger}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/admin/?tab=feedback", nil)

	testHandler(t, server).ServeHTTP(recorder, request)

	if recorder.Code != http.StatusPermanentRedirect {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	if location := recorder.Header().Get("Location"); location != "/admin?tab=feedback" {
		t.Fatalf("location = %q", location)
	}
}

func TestStartupGateAllowsOnlyProbesBeforeReady(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	server := &Server{
		db: &sql.DB{}, logger: logger, bootPending: true,
	}
	handler := testHandler(t, server)

	health := httptest.NewRecorder()
	handler.ServeHTTP(health, httptest.NewRequest(http.MethodGet, "/healthz", nil))
	if health.Code != http.StatusOK {
		t.Fatalf("health status = %d, body = %s", health.Code, health.Body.String())
	}

	ready := httptest.NewRecorder()
	handler.ServeHTTP(ready, httptest.NewRequest(http.MethodGet, "/readyz", nil))
	if ready.Code != http.StatusServiceUnavailable || !bytes.Contains(ready.Body.Bytes(), []byte(`"migration":false`)) {
		t.Fatalf("ready status = %d, body = %s", ready.Code, ready.Body.String())
	}

	blocked := httptest.NewRecorder()
	handler.ServeHTTP(blocked, httptest.NewRequest(http.MethodPost, "/api/login", nil))
	if blocked.Code != http.StatusServiceUnavailable || blocked.Header().Get("Retry-After") != "5" {
		t.Fatalf("blocked status = %d, retry = %q, body = %s",
			blocked.Code, blocked.Header().Get("Retry-After"), blocked.Body.String())
	}

	server.MarkReady()
	allowed := httptest.NewRecorder()
	handler.ServeHTTP(allowed, httptest.NewRequest(http.MethodPost, "/api/login", nil))
	if allowed.Code == http.StatusServiceUnavailable {
		t.Fatalf("ready server still blocked: status=%d body=%s", allowed.Code, allowed.Body.String())
	}
}

func TestAPIDisablesResponseCaching(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	server := &Server{db: &sql.DB{}, logger: logger}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/api/get-captcha", nil)

	testHandler(t, server).ServeHTTP(recorder, request)

	if recorder.Header().Get("Cache-Control") != "no-store" {
		t.Fatalf("Cache-Control = %q", recorder.Header().Get("Cache-Control"))
	}
}

func TestLegacyLoginContracts(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	server := &Server{db: &sql.DB{}, logger: logger}
	handler := testHandler(t, server)
	for _, item := range []struct {
		method string
		path   string
		text   string
	}{
		{http.MethodGet, "/api/get-captcha", "教务直连已下线"},
		{http.MethodPost, "/api/login", "教务直连已下线"},
		{http.MethodPost, "/api/login-manual", "教务直连已下线"},
		{http.MethodPost, "/api/login-webvpn-manual", "智慧理工直连已无需第二步教务登录"},
	} {
		recorder := httptest.NewRecorder()
		handler.ServeHTTP(recorder, httptest.NewRequest(item.method, item.path, nil))
		if recorder.Code != http.StatusBadRequest || !bytes.Contains(recorder.Body.Bytes(), []byte(item.text)) {
			t.Fatalf("%s %s: status=%d body=%s", item.method, item.path, recorder.Code, recorder.Body.String())
		}
	}
}

func TestGraduateSemestersUsesActualCourseSemesters(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	manager, err := session.NewManager(time.Hour, 10, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	defer manager.Close()
	studentID := "124101960001"
	token, err := manager.Add(t.Context(), &session.Session{
		StudentID: studentID, AccountType: "graduate", JWC: jwc.New(nil),
	})
	if err != nil {
		t.Fatal(err)
	}
	semesters := []string{"2026-2027第一学期", "2025-2026第二学期"}
	server := &Server{
		store: store.New(db), sessions: manager,
		cache: map[string]cacheEntry{
			studentID + ":yjs:courses": {value: map[string]any{"semesters": semesters}, expiresAt: time.Now().Add(time.Hour)},
		},
	}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/api/semesters", nil)
	request.Header.Set(tokenHeader, token)
	server.semesters(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
	var payload struct {
		Success   bool     `json:"success"`
		Semesters []string `json:"semesters"`
		Current   string   `json:"current"`
	}
	if err = json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if !payload.Success || !slices.Equal(payload.Semesters, semesters) || payload.Current != semesters[0] {
		t.Fatalf("unexpected payload: %#v", payload)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestDecodeJSONStrictness(t *testing.T) {
	var body map[string]any
	request := httptest.NewRequest(http.MethodPost, "/", bytes.NewBufferString(`{"value":1}`))
	if err := decodeJSON(request, &body); err != nil || body["value"] != float64(1) {
		t.Fatalf("valid JSON rejected: body=%#v err=%v", body, err)
	}
	request = httptest.NewRequest(http.MethodPost, "/", bytes.NewBufferString(`{"value":1} {"extra":2}`))
	if err := decodeJSON(request, &body); err == nil {
		t.Fatal("trailing JSON should be rejected")
	}
	request = httptest.NewRequest(http.MethodPost, "/", bytes.NewReader(bytes.Repeat([]byte("x"), (2<<20)+1)))
	if err := decodeJSON(request, &body); err == nil {
		t.Fatal("oversized body should be rejected")
	}
}

func TestDecodeWechatResponseHasSizeLimit(t *testing.T) {
	var payload map[string]any
	if err := decodeWechatResponse(strings.NewReader(`{"errcode":0}`), &payload); err != nil {
		t.Fatal(err)
	}
	if payload["errcode"] != float64(0) {
		t.Fatalf("unexpected payload: %#v", payload)
	}
	if err := decodeWechatResponse(bytes.NewReader(bytes.Repeat([]byte("x"), wechatResponseLimit+1)), &payload); err == nil {
		t.Fatal("oversized WeChat response should be rejected")
	}
}

func TestRequestLogPathDropsSensitiveQuery(t *testing.T) {
	request := httptest.NewRequest(http.MethodGet, "/api/sso-qr/status?qr_id=secret-value&other=1", nil)
	if got := requestLogPath(request); got != "/api/sso-qr/status" {
		t.Fatalf("request log path = %q", got)
	}
}

func TestSemesterListIsNewestFirstWithoutFutureTerms(t *testing.T) {
	firstTerm := semesterListAt(time.Date(2026, time.October, 1, 0, 0, 0, 0, beijing))
	wantFirst := []string{"2026-2027-1", "2025-2026-2", "2025-2026-1"}
	if len(firstTerm) != 13 || !slices.Equal(firstTerm[:3], wantFirst) {
		t.Fatalf("first-term semesters = %#v", firstTerm)
	}
	secondTerm := semesterListAt(time.Date(2027, time.March, 1, 0, 0, 0, 0, beijing))
	wantSecond := []string{"2026-2027-2", "2026-2027-1", "2025-2026-2"}
	if len(secondTerm) != 14 || !slices.Equal(secondTerm[:3], wantSecond) {
		t.Fatalf("second-term semesters = %#v", secondTerm)
	}
}

func TestLoginCredentialsPreservePasswordWhitespace(t *testing.T) {
	sid, password, err := loginCredentials(loginRequest{StudentID: " 924101960000 ", Password: " secret with spaces "})
	if err != nil {
		t.Fatal(err)
	}
	if sid != "924101960000" || password != " secret with spaces " {
		t.Fatalf("credentials = %q, %q", sid, password)
	}
}

func TestLoginCredentialsRejectInvalidOrOversizedInput(t *testing.T) {
	for _, input := range []loginRequest{
		{StudentID: "../../etc/passwd", Password: "secret"},
		{StudentID: "924101960000", Password: strings.Repeat("x", 1025)},
	} {
		if _, _, err := loginCredentials(input); err == nil {
			t.Fatalf("invalid credentials accepted: student_id=%q password_len=%d", input.StudentID, len(input.Password))
		}
	}
}

func TestSemesterValidationSupportsUndergraduateAndGraduateFormats(t *testing.T) {
	for _, value := range []string{"2026-2027-1", "2026/2027-2", "2026-2027第一学期", "2026-2027学年第二学期"} {
		if !validSemester(value, false) {
			t.Fatalf("valid semester rejected: %q", value)
		}
	}
	for _, value := range []string{"", "2026-2028-1", "2026-2027-3", strings.Repeat("2", 100), "2026-\n2027-1"} {
		if validSemester(value, false) {
			t.Fatalf("invalid semester accepted: %q", value)
		}
	}
	if !validSemester("__all__", true) || validSemester("__all__", false) {
		t.Fatal("__all__ semester scope validation is incorrect")
	}
}

func TestMiddlewareScopesAllSemesterToGrades(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	server := &Server{logger: logger}
	handler := middleware(logger, server, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"success": true})
	}))

	grades := httptest.NewRecorder()
	handler.ServeHTTP(grades, httptest.NewRequest(http.MethodGet, "/api/grades?semester=__all__", nil))
	if grades.Code != http.StatusOK {
		t.Fatalf("grades status = %d, body=%s", grades.Code, grades.Body.String())
	}

	courses := httptest.NewRecorder()
	handler.ServeHTTP(courses, httptest.NewRequest(http.MethodGet, "/api/courses?semester=__all__", nil))
	if courses.Code != http.StatusBadRequest || !strings.Contains(courses.Body.String(), "学期格式无效") {
		t.Fatalf("courses status = %d, body=%s", courses.Code, courses.Body.String())
	}
}

func TestAuditFavoriteValidation(t *testing.T) {
	group := store.AuditGroup{
		Name: " 高等数学 ", ClassInfo: " 924101 ", Teacher: " 教师 ", Classroom: " Ⅰ-101 ",
		Schedules: []store.AuditSchedule{{Day: 1, Start: 1, End: 2, Weeks: " 1-16 ", Teacher: " 教师 ", Classroom: " Ⅰ-101 "}},
	}
	if err := normalizeAuditFavorite(&group); err != nil {
		t.Fatal(err)
	}
	if group.Name != "高等数学" || group.Schedules[0].Weeks != "1-16" {
		t.Fatalf("favorite was not normalized: %#v", group)
	}
	group.Schedules[0].End = 14
	if err := normalizeAuditFavorite(&group); err == nil {
		t.Fatal("invalid schedule was accepted")
	}
	group.Schedules[0].End = 2
	group.Name = strings.Repeat("课", 201)
	if err := normalizeAuditFavorite(&group); err == nil {
		t.Fatal("oversized course name was accepted")
	}
}

func TestCallerOpenIDRejectsUntrustedShape(t *testing.T) {
	request := httptest.NewRequest(http.MethodGet, "/", nil)
	request.Header.Set("X-WX-OPENID", "valid_OpenID-123")
	if got := callerOpenID(request); got != "valid_OpenID-123" {
		t.Fatalf("valid openid = %q", got)
	}
	request.Header.Set("X-WX-OPENID", "invalid openid\nvalue")
	if got := callerOpenID(request); got != "" {
		t.Fatalf("invalid openid accepted: %q", got)
	}
}

func TestRefreshPartKeepsLegacyOKContract(t *testing.T) {
	payload := refreshPart(3)
	if payload["ok"] != true || payload["success"] != true || payload["count"] != 3 {
		t.Fatalf("unexpected refresh part: %#v", payload)
	}
}

func TestServerWriteTimeoutAllowsSequentialJWCRequests(t *testing.T) {
	if got := serverWriteTimeout(30 * time.Second); got != 90*time.Second {
		t.Fatalf("serverWriteTimeout(30s) = %s, want 90s", got)
	}
	if got := serverWriteTimeout(5 * time.Second); got != 60*time.Second {
		t.Fatalf("serverWriteTimeout(5s) = %s, want 60s", got)
	}
}

func TestConnectTestRateLimitStopsBeforeNetworkProbe(t *testing.T) {
	server := &Server{rates: map[string][]time.Time{}}
	now := time.Now()
	key := "connect-test:192.0.2.1"
	for range 6 {
		server.rates[key] = append(server.rates[key], now)
	}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/api/connect-test", nil)
	request.RemoteAddr = "192.0.2.1:1234"
	server.connectTest(recorder, request)
	if recorder.Code != http.StatusTooManyRequests || !strings.Contains(recorder.Body.String(), "测试连接过于频繁") {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
}

func TestNetworkStatusWithoutCacheDoesNotProbeSynchronously(t *testing.T) {
	server := &Server{cache: map[string]cacheEntry{}}
	started := time.Now()
	status := server.networkStatus(t.Context(), false)
	if elapsed := time.Since(started); elapsed > 100*time.Millisecond {
		t.Fatalf("uncached status blocked for %s", elapsed)
	}
	if status["method"] != "checking" || status["label"] != "检测中" {
		t.Fatalf("unexpected initial network status: %#v", status)
	}
}

func TestMiddlewareCompressesLargeJSON(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	server := &Server{logger: logger}
	handler := middleware(logger, server, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"value": strings.Repeat("compressible-", 100)})
	}))
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/large", nil)
	request.Header.Set("Accept-Encoding", "br, gzip")
	handler.ServeHTTP(recorder, request)

	if recorder.Header().Get("Content-Encoding") != "gzip" || !strings.Contains(recorder.Header().Get("Vary"), "Accept-Encoding") {
		t.Fatalf("compression headers = %#v", recorder.Header())
	}
	reader, err := gzip.NewReader(recorder.Body)
	if err != nil {
		t.Fatal(err)
	}
	raw, err := io.ReadAll(reader)
	if err != nil {
		t.Fatal(err)
	}
	if err = reader.Close(); err != nil {
		t.Fatal(err)
	}
	var payload map[string]string
	if err = json.Unmarshal(raw, &payload); err != nil || len(payload["value"]) < gzipMinSize {
		t.Fatalf("payload invalid: len=%d err=%v", len(payload["value"]), err)
	}
}

func TestMiddlewareSkipsSmallOrDisabledGzip(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	server := &Server{logger: logger}
	handler := middleware(logger, server, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"value": "small"})
	}))
	for _, encoding := range []string{"gzip", "gzip;q=0", "gzip;q=0.00"} {
		recorder := httptest.NewRecorder()
		request := httptest.NewRequest(http.MethodGet, "/small", nil)
		request.Header.Set("Accept-Encoding", encoding)
		handler.ServeHTTP(recorder, request)
		if got := recorder.Header().Get("Content-Encoding"); got != "" {
			t.Fatalf("encoding %q unexpectedly produced %q", encoding, got)
		}
		if !strings.Contains(recorder.Header().Get("Vary"), "Accept-Encoding") {
			t.Fatalf("encoding %q missing Vary header", encoding)
		}
	}
}

func TestAcceptsGzipHonorsExplicitAndWildcardQuality(t *testing.T) {
	for _, item := range []struct {
		header string
		want   bool
	}{
		{"br, *;q=0.5", true},
		{"*;q=1, gzip;q=0", false},
		{"gzip;q=0.001", true},
		{"gzip;q=invalid", false},
	} {
		if got := acceptsGzip(item.header); got != item.want {
			t.Fatalf("acceptsGzip(%q)=%v, want %v", item.header, got, item.want)
		}
	}
}
