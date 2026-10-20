package httpapi

import (
	"bytes"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/resetinging/njust-schedule/internal/config"
	"github.com/resetinging/njust-schedule/internal/session"
	"github.com/resetinging/njust-schedule/internal/store"
)

func TestMissingToken401LogsAsUnauthenticatedRequest(t *testing.T) {
	manager, err := session.NewManager(time.Hour, 10, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = manager.Close() })
	var logs bytes.Buffer
	server := &Server{
		sessions: manager,
		logger: slog.New(slog.NewTextHandler(&logs, &slog.HandlerOptions{
			Level: slog.LevelDebug,
		})),
	}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/api/audit-favorites", nil)
	testHandler(t, server).ServeHTTP(recorder, request)
	if recorder.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	if !strings.Contains(logs.String(), "未认证请求") || strings.Contains(logs.String(), "请求异常") {
		t.Fatalf("unexpected log: %s", logs.String())
	}
}

func TestGeneralEducationCoursesRequiresSession(t *testing.T) {
	manager, err := session.NewManager(time.Hour, 10, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = manager.Close() })
	server := &Server{
		sessions: manager,
		logger:   slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/api/general-education-courses", nil)
	testHandler(t, server).ServeHTTP(recorder, request)
	if recorder.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
}

func TestGeneralEducationCoursesReturnsPagedCatalog(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	manager, err := session.NewManager(time.Hour, 10, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = manager.Close() })
	token, err := manager.Add(t.Context(), &session.Session{StudentID: "924101960123", AccountType: "undergraduate"})
	if err != nil {
		t.Fatal(err)
	}
	server := &Server{
		cfg:      config.Config{DataCacheTTL: time.Hour},
		store:    store.New(db),
		sessions: manager,
		logger:   slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
	mock.ExpectQuery(regexp.QuoteMeta("SELECT COUNT(*) FROM general_education_syllabi WHERE semester=? AND (course_code LIKE ? OR course_name LIKE ? OR department LIKE ? OR attribute LIKE ?)")).
		WithArgs("2026-2027-1", "%绿色%", "%绿色%", "%绿色%", "%绿色%").
		WillReturnRows(sqlmock.NewRows([]string{"count"}).AddRow(1))
	mock.ExpectQuery("SELECT id,semester,course_code").
		WithArgs("2026-2027-1", "%绿色%", "%绿色%", "%绿色%", "%绿色%", 20, 0).
		WillReturnRows(sqlmock.NewRows([]string{
			"id", "semester", "course_code", "course_name", "department", "credit",
			"hours", "assessment", "attribute", "syllabus_id", "has_syllabus", "detail_fetched_at",
		}).AddRow(1, "2026-2027-1", "00010192", "绿色生活与绿色技术", "环境与生物工程学院",
			"1", "32", "考查", "任选", "ABC123", 1, 0))
	mock.ExpectQuery(regexp.QuoteMeta("SELECT COUNT(*) FROM general_education_syllabi WHERE semester=?")).
		WithArgs("2026-2027-1").
		WillReturnRows(sqlmock.NewRows([]string{"count"}).AddRow(1))
	mock.ExpectQuery("SELECT v FROM settings").
		WithArgs("general_education_catalog_at:2026-2027-1").
		WillReturnRows(sqlmock.NewRows([]string{"v"}).AddRow("1700000000"))

	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/api/general-education-courses?semester=2026-2027-1&q=%E7%BB%BF%E8%89%B2", nil)
	request.Header.Set(tokenHeader, token)
	testHandler(t, server).ServeHTTP(recorder, request)
	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	var payload struct {
		Success bool                           `json:"success"`
		Total   int                            `json:"total"`
		Courses []store.GeneralEducationCourse `json:"courses"`
	}
	if err = json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if !payload.Success || payload.Total != 1 || len(payload.Courses) != 1 ||
		payload.Courses[0].CourseCode != "00010192" {
		t.Fatalf("unexpected payload: %#v", payload)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}
