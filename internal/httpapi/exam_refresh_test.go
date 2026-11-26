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
	"github.com/resetinging/njust-schedule/internal/jwc"
	"github.com/resetinging/njust-schedule/internal/session"
	"github.com/resetinging/njust-schedule/internal/store"
)

func TestRefreshExamsIgnoresGlobalManualRefreshGate(t *testing.T) {
	t.Setenv("ALLOW_LIVE_REFRESH", "0")
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

	const studentID = "924101960099"
	const semester = "2026-2027-1"
	client := jwc.New(nil)
	client.StudentID = studentID
	client.HTTP.Transport = studentDataRoundTripFunc(func(request *http.Request) (*http.Response, error) {
		return &http.Response{
			StatusCode: http.StatusOK,
			Header:     make(http.Header),
			Body: io.NopCloser(strings.NewReader(
				`{"data":[{"kcmc":"高等数学","ksrq":"2026-12-20","kssj":"09:00~11:00","ksdd":"Ⅳ-A303","zwh":"12","kslx":"期末考试"}]}`,
			)),
			Request: request,
		}, nil
	})
	token, err := manager.Add(t.Context(), &session.Session{StudentID: studentID, JWC: client})
	if err != nil {
		t.Fatal(err)
	}

	mock.ExpectBegin()
	mock.ExpectExec("DELETE FROM exams").WithArgs(studentID, semester).
		WillReturnResult(sqlmock.NewResult(0, 0))
	prepared := mock.ExpectPrepare("INSERT INTO exams")
	prepared.ExpectExec().WithArgs(
		studentID, "高等数学", "2026-12-20", "09:00~11:00", "Ⅳ-A303", "12", "期末考试", semester,
	).WillReturnResult(sqlmock.NewResult(1, 1))
	mock.ExpectCommit()
	mock.ExpectQuery("SELECT v FROM user_settings").WithArgs(studentID, "subscribe").
		WillReturnRows(sqlmock.NewRows([]string{"v"}))
	mock.ExpectExec("UPDATE reminder_tasks SET status='disabled'").WithArgs(studentID, semester, "exam").
		WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectExec("UPDATE reminder_tasks SET status='disabled'").WithArgs(studentID, semester, "grade").
		WillReturnResult(sqlmock.NewResult(0, 0))

	serverCtx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	server := &Server{
		store: store.New(db), sessions: manager,
		logger:   slog.New(slog.NewTextHandler(io.Discard, nil)),
		jwcSlots: make(chan struct{}, 1), dedupe: map[string]*inflight{},
		cache: map[string]cacheEntry{}, rates: map[string][]time.Time{}, ctx: serverCtx,
	}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(
		http.MethodPost, "/api/refresh-exams?semester="+semester, nil,
	)
	request.Header.Set(tokenHeader, token)
	server.refreshExams(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
	if !strings.Contains(recorder.Body.String(), `"refreshed":true`) ||
		!strings.Contains(recorder.Body.String(), `"count":1`) {
		t.Fatalf("unexpected body: %s", recorder.Body.String())
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestRefreshExamsRateLimit(t *testing.T) {
	manager, err := session.NewManager(time.Hour, 10, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = manager.Close() })

	const studentID = "924101960098"
	token, err := manager.Add(t.Context(), &session.Session{StudentID: studentID})
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	server := &Server{
		sessions: manager,
		rates: map[string][]time.Time{
			"exam-refresh:" + studentID: {now, now, now},
		},
	}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/api/refresh-exams", nil)
	request.Header.Set(tokenHeader, token)
	server.refreshExams(recorder, request)
	if recorder.Code != http.StatusTooManyRequests {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
}
