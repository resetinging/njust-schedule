package httpapi

import (
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/resetinging/njust-schedule/internal/config"
	"github.com/resetinging/njust-schedule/internal/store"
)

func TestAuditStatusContractIncludesDatabaseErrors(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	semester := "2026-2027-1"
	mock.ExpectQuery("SELECT COUNT").WithArgs(semester).
		WillReturnRows(sqlmock.NewRows([]string{"count"}).AddRow(12))
	mock.ExpectQuery("SELECT v FROM settings").WithArgs("audit_catalog_at:" + semester).
		WillReturnError(errors.New("settings unavailable"))
	server := &Server{store: store.New(db)}
	payload := server.auditStatus(t.Context(), semester)
	for _, key := range []string{"semester", "course_count", "updated_at", "empty", "needs_refresh", "db_error", "running", "running_semester", "last_started_at", "last_finished_at", "last_success", "last_count", "last_error"} {
		if _, ok := payload[key]; !ok {
			t.Fatalf("missing audit status field %q", key)
		}
	}
	if payload["db_error"] == "" || payload["needs_refresh"] != true {
		t.Fatalf("database error was hidden: %#v", payload)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestAdminLogoutRevokesOnlyCurrentToken(t *testing.T) {
	server := &Server{cfg: config.Config{SessionKey: make([]byte, 32), AdminPassword: "secret"}}
	first := server.issueAdminToken()
	second := server.issueAdminToken()
	if first == second || !server.validAdminToken(first) || !server.validAdminToken(second) {
		t.Fatal("admin tokens must be unique and initially valid")
	}
	request := httptest.NewRequest(http.MethodPost, "/api/admin/logout", nil)
	request.Header.Set("X-Admin-Token", first)
	recorder := httptest.NewRecorder()
	server.adminLogout(recorder, request)
	if recorder.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
	if server.validAdminToken(first) || !server.validAdminToken(second) {
		t.Fatal("logout did not revoke exactly one admin token")
	}
}

func TestPublicMetricsDoNotExposeActiveSessions(t *testing.T) {
	server := &Server{adminTotal: 42}
	recorder := httptest.NewRecorder()
	server.metrics(recorder, httptest.NewRequest(http.MethodGet, "/metrics", nil))
	if recorder.Code != http.StatusOK || !strings.Contains(recorder.Body.String(), "njust_http_requests_total 42") {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
	if strings.Contains(recorder.Body.String(), "sessions") {
		t.Fatalf("public metrics leaked session data: %s", recorder.Body.String())
	}
}

func TestAdminFeedbackContract(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	now := time.Now()
	mock.ExpectQuery("SELECT id,COALESCE\\(student_id").WithArgs(500).WillReturnRows(
		sqlmock.NewRows([]string{"id", "student_id", "student_name", "fb_type", "content", "status", "reply", "replied_at", "reply_read", "created_at"}).
			AddRow(1, "924101960001", "测试用户", "bug", "测试反馈", "pending", "", nil, false, now),
	)
	server := &Server{
		cfg:   config.Config{SessionKey: make([]byte, 32), AdminPassword: "secret"},
		store: store.New(db), logger: slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
	request := httptest.NewRequest(http.MethodGet, "/api/admin/feedback", nil)
	request.Header.Set("X-Admin-Token", server.issueAdminToken())
	recorder := httptest.NewRecorder()
	server.adminFeedback(recorder, request)
	if recorder.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
	var payload map[string]any
	if err = json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	items, ok := payload["feedback"].([]any)
	if !ok || len(items) != 1 {
		t.Fatalf("unexpected feedback payload: %#v", payload)
	}
	item := items[0].(map[string]any)
	for _, key := range []string{"id", "student_id", "student_name", "type", "content", "status", "reply", "replied_at", "reply_read", "created_at"} {
		if _, ok = item[key]; !ok {
			t.Fatalf("missing feedback field %q", key)
		}
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestAnalyticsReportContract(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	mock.ExpectQuery("SELECT COUNT.*SUM\\(open_count\\)").WillReturnRows(sqlmock.NewRows([]string{"dau", "opens", "sessions", "seconds", "pages"}).AddRow(2, 3, 4, 120, 5))
	mock.ExpectQuery("SELECT COUNT.*INTERVAL 1 DAY").WillReturnRows(sqlmock.NewRows([]string{"count"}).AddRow(1))
	mock.ExpectQuery("SELECT COUNT.*INTERVAL 6 DAY").WillReturnRows(sqlmock.NewRows([]string{"count"}).AddRow(2))
	mock.ExpectQuery("SELECT COUNT.*INTERVAL 29 DAY").WillReturnRows(sqlmock.NewRows([]string{"count"}).AddRow(2))
	mock.ExpectQuery("SELECT COUNT.*first_date=CURDATE").WillReturnRows(sqlmock.NewRows([]string{"count"}).AddRow(1))
	mock.ExpectQuery("SELECT COUNT.*FROM usage_user_daily$").WillReturnRows(sqlmock.NewRows([]string{"count"}).AddRow(2))
	mock.ExpectQuery("SELECT DATE_FORMAT").WithArgs(0).WillReturnRows(sqlmock.NewRows([]string{"date", "dau", "opens", "sessions", "seconds"}))
	mock.ExpectQuery("SELECT page").WithArgs(0).WillReturnRows(sqlmock.NewRows([]string{"page", "events", "users"}))
	mock.ExpectQuery("SELECT feature").WithArgs(0).WillReturnRows(sqlmock.NewRows([]string{"feature", "events", "users"}))
	mock.ExpectQuery("SELECT HOUR").WillReturnRows(sqlmock.NewRows([]string{"hour", "count"}))
	mock.ExpectQuery("SELECT COALESCE\\(slot_id").WithArgs(0).WillReturnRows(sqlmock.NewRows([]string{"slot", "ad_type", "page", "views", "visible", "visible_ms", "requests", "impressions", "clicks", "closes", "users"}).AddRow("slot-test", "native", "schedule", 3, 4, 8000, 10, 6, 2, 1, 2))
	for _, days := range []int{1, 7, 30} {
		mock.ExpectQuery("SELECT COUNT.*later.analytics_id").WithArgs(days, days).
			WillReturnRows(sqlmock.NewRows([]string{"eligible", "retained"}).AddRow(0, 0))
	}
	server := &Server{db: db}
	payload, err := server.analyticsReport(t.Context(), 1)
	if err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"days", "overview", "trend", "retention", "pages", "features", "slots", "hourly"} {
		if _, ok := payload[key]; !ok {
			t.Fatalf("missing analytics field %q", key)
		}
	}
	overview := payload["overview"].(map[string]any)
	for _, key := range []string{"dau", "dau_yesterday", "wau", "mau", "new_users_today", "total_users", "opens_today", "sessions_today", "active_seconds_today", "avg_seconds_today", "page_views_today"} {
		if _, ok := overview[key]; !ok {
			t.Fatalf("missing analytics overview field %q", key)
		}
	}
	retention := payload["retention"].(map[string]any)
	for _, key := range []string{"d1", "d7", "d30"} {
		if _, ok := retention[key]; !ok {
			t.Fatalf("missing retention field %q", key)
		}
	}
	if len(payload["hourly"].(map[string]int)) != 24 {
		t.Fatalf("hourly buckets = %#v", payload["hourly"])
	}
	slots := payload["slots"].([]map[string]any)
	if len(slots) != 1 {
		t.Fatalf("slots = %#v", slots)
	}
	for _, key := range []string{"visible_per_user", "avg_visible_seconds", "fill_rate", "ctr", "close_rate"} {
		if _, ok := slots[0][key]; !ok {
			t.Fatalf("missing slot field %q", key)
		}
	}
	if slots[0]["visible_per_user"] != 2.0 ||
		slots[0]["avg_visible_seconds"] != 2.0 ||
		slots[0]["fill_rate"] != 60.0 ||
		slots[0]["ctr"] != 33.3 ||
		slots[0]["close_rate"] != 16.7 {
		t.Fatalf("unexpected slot metrics: %#v", slots[0])
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}
