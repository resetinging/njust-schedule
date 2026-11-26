package httpapi

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/resetinging/njust-schedule/internal/config"
	"github.com/resetinging/njust-schedule/internal/security"
	"github.com/resetinging/njust-schedule/internal/session"
	"github.com/resetinging/njust-schedule/internal/store"
)

func TestPublicCampusServicesContract(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	mock.ExpectQuery("SELECT COUNT\\(\\*\\) FROM campus_services").
		WillReturnRows(sqlmock.NewRows([]string{"count"}).AddRow(1))
	mock.ExpectQuery("SELECT id,COALESCE").
		WillReturnRows(sqlmock.NewRows([]string{
			"id", "category", "provider_name", "title", "summary", "details", "audience",
			"price_label", "campus_scope", "qualification_note", "sponsored", "verified",
			"enabled", "priority", "start_at", "end_at",
		}).AddRow(
			"campus-1", "exam", "培训机构", "考研咨询", "公开摘要", "详情只在详情接口返回",
			"在校生", "价格面议", "all", "已核验", true, true, true,
			20, "2026-11-01", "",
		))
	server := &Server{
		store: store.New(db), logger: slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/api/campus-services?category=exam", nil)
	testHandler(t, server).ServeHTTP(recorder, request)
	if recorder.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
	body := recorder.Body.String()
	for _, expected := range []string{`"success":true`, `"id":"campus-1"`, `"sponsored":true`, `"total":1`} {
		if !strings.Contains(body, expected) {
			t.Fatalf("missing %s in %s", expected, body)
		}
	}
	if strings.Contains(body, `"verified"`) || strings.Contains(body, `"enabled"`) {
		t.Fatalf("public payload leaked admin fields: %s", body)
	}
	if strings.Contains(body, "详情只在详情接口返回") {
		t.Fatalf("public list should omit full details: %s", body)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestPublicCampusServicesRejectsUnknownCategory(t *testing.T) {
	server := &Server{logger: slog.New(slog.NewTextHandler(io.Discard, nil))}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/api/campus-services?category=unknown", nil)
	testHandler(t, server).ServeHTTP(recorder, request)
	if recorder.Code != http.StatusBadRequest {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
}

func TestAdminSaveCampusServicesValidatesBeforeWriting(t *testing.T) {
	server := &Server{
		cfg: config.Config{
			SessionKey:    make([]byte, 32),
			AdminPassword: "secret",
		},
		logger: slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
	payload := `{"services":[{"id":"campus-1","category":"exam","provider_name":"机构","title":"咨询","summary":"摘要","price_label":"面议","campus_scope":"all","enabled":true,"verified":false,"start_date":"2026-11-24"}]}`
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/api/admin/campus-services", strings.NewReader(payload))
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("X-Admin-Token", server.issueAdminToken())
	testHandler(t, server).ServeHTTP(recorder, request)
	if recorder.Code != http.StatusBadRequest || !strings.Contains(recorder.Body.String(), "完成审核") {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
}

func TestCampusServiceLeadRequiresExplicitConsent(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	crypto, err := security.New(make([]byte, 32))
	if err != nil {
		t.Fatal(err)
	}
	sessions, err := session.NewManager(time.Hour, 10, "", crypto, logger)
	if err != nil {
		t.Fatal(err)
	}
	defer sessions.Close()
	token, err := sessions.Add(context.Background(), &session.Session{
		StudentID: "924101960123", StudentName: "测试用户",
	})
	if err != nil {
		t.Fatal(err)
	}
	server := &Server{
		sessions: sessions, crypto: crypto, logger: logger,
	}
	payload := `{"contact_type":"phone","contact":"13800138000","consent":false}`
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(
		http.MethodPost, "/api/campus-services/campus-1/leads", strings.NewReader(payload),
	)
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set(tokenHeader, token)
	testHandler(t, server).ServeHTTP(recorder, request)
	if recorder.Code != http.StatusBadRequest || !strings.Contains(recorder.Body.String(), "同意") {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
}

func TestCampusServiceLeadEncryptsAndPersistsConsent(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	key := make([]byte, 32)
	for index := range key {
		key[index] = byte(index + 1)
	}
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	crypto, err := security.New(key)
	if err != nil {
		t.Fatal(err)
	}
	sessions, err := session.NewManager(time.Hour, 10, "", crypto, logger)
	if err != nil {
		t.Fatal(err)
	}
	defer sessions.Close()
	token, err := sessions.Add(context.Background(), &session.Session{
		StudentID: "924101960123", StudentName: "测试用户",
	})
	if err != nil {
		t.Fatal(err)
	}
	mock.ExpectQuery("SELECT id,COALESCE").
		WithArgs("campus-1", sqlmock.AnyArg(), sqlmock.AnyArg()).
		WillReturnRows(sqlmock.NewRows([]string{
			"id", "category", "provider_name", "title", "summary", "details", "audience",
			"price_label", "campus_scope", "qualification_note", "sponsored", "verified",
			"enabled", "priority", "start_at", "end_at",
		}).AddRow(
			"campus-1", "exam", "机构", "咨询", "摘要", "",
			"在校生", "面议", "all", "已核验", true, true, true,
			0, "2026-11-24", "",
		))
	mock.ExpectExec("INSERT INTO campus_service_leads").
		WithArgs(
			"campus-1", sqlmock.AnyArg(), "phone", sqlmock.AnyArg(),
			"138****8000", sqlmock.AnyArg(), "希望了解课程", "campus-service-2026-11-24", 30,
		).
		WillReturnResult(sqlmock.NewResult(42, 1))
	server := &Server{
		cfg: config.Config{SessionKey: key}, store: store.New(db),
		crypto: crypto, sessions: sessions,
		logger: logger, rates: map[string][]time.Time{},
	}
	payload := `{"contact_type":"phone","contact":"13800138000","note":"希望了解课程","consent":true}`
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(
		http.MethodPost, "/api/campus-services/campus-1/leads", strings.NewReader(payload),
	)
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set(tokenHeader, token)
	testHandler(t, server).ServeHTTP(recorder, request)
	if recorder.Code != http.StatusOK || !strings.Contains(recorder.Body.String(), `"lead_id":42`) {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}
