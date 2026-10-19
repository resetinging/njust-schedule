package httpapi

import (
	"context"
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
	"github.com/resetinging/njust-schedule/internal/jwc"
	"github.com/resetinging/njust-schedule/internal/session"
	"github.com/resetinging/njust-schedule/internal/store"
)

type studentDataRoundTripFunc func(*http.Request) (*http.Response, error)

func (fn studentDataRoundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return fn(request)
}

func TestRunRefreshAllKeepsSuccessfulScheduleWhenExamsFail(t *testing.T) {
	savedCourses, savedExams := false, false
	result := runRefreshAll(
		func() ([]store.Course, error) { return []store.Course{{Name: "高等数学"}}, nil },
		func([]store.Course) error { savedCourses = true; return nil },
		func() ([]store.Exam, error) { return nil, errors.New("考试系统暂不可用") },
		func([]store.Exam) error { savedExams = true; return nil },
	)

	if !savedCourses || savedExams {
		t.Fatalf("save calls: courses=%v exams=%v", savedCourses, savedExams)
	}
	if result.schedule["ok"] != true || result.schedule["count"] != 1 {
		t.Fatalf("schedule=%#v", result.schedule)
	}
	if result.exams["ok"] != false || result.exams["status_code"] != 502 {
		t.Fatalf("exams=%#v", result.exams)
	}
}

func TestRunRefreshAllContinuesAfterNonAuthScheduleFailure(t *testing.T) {
	examsFetched := false
	result := runRefreshAll(
		func() ([]store.Course, error) { return nil, errors.New("课表系统暂不可用") },
		func([]store.Course) error { t.Fatal("failed courses must not be saved"); return nil },
		func() ([]store.Exam, error) {
			examsFetched = true
			return []store.Exam{{CourseName: "高等数学"}}, nil
		},
		func([]store.Exam) error { return nil },
	)

	if !examsFetched || result.schedule["ok"] != false || result.exams["ok"] != true {
		t.Fatalf("result=%#v examsFetched=%v", result, examsFetched)
	}
}

func TestRunRefreshAllStopsAfterSessionExpiry(t *testing.T) {
	examsFetched := false
	result := runRefreshAll(
		func() ([]store.Course, error) { return nil, jwc.ErrSessionExpired },
		func([]store.Course) error { t.Fatal("expired result must not be saved"); return nil },
		func() ([]store.Exam, error) { examsFetched = true; return nil, nil },
		func([]store.Exam) error { t.Fatal("exams must not be saved after expiry"); return nil },
	)

	if examsFetched {
		t.Fatal("exam fetch continued after session expiry")
	}
	if result.schedule["status_code"] != 401 || result.exams["status_code"] != 401 {
		t.Fatalf("result=%#v", result)
	}
}

func TestRefreshCETEmptyResultReturnsNotFoundWithoutReplacingSnapshot(t *testing.T) {
	manager, err := session.NewManager(time.Hour, 10, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	defer manager.Close()
	client := jwc.New(nil)
	client.HTTP.Transport = studentDataRoundTripFunc(func(request *http.Request) (*http.Response, error) {
		return &http.Response{
			StatusCode: http.StatusOK,
			Header:     make(http.Header),
			Body:       io.NopCloser(strings.NewReader(`<table id="dataList"><tr><th>考试</th></tr></table>`)),
			Request:    request,
		}, nil
	})
	token, err := manager.Add(context.Background(), &session.Session{StudentID: "924101960000", JWC: client})
	if err != nil {
		t.Fatal(err)
	}
	serverCtx, cancel := context.WithCancel(context.Background())
	defer cancel()
	server := &Server{
		sessions: manager,
		jwcSlots: make(chan struct{}, 1),
		dedupe:   map[string]*inflight{},
		ctx:      serverCtx,
	}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/api/refresh-cet", nil)
	request.Header.Set(tokenHeader, token)

	server.refreshCET(recorder, request)

	if recorder.Code != http.StatusNotFound {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
	var payload map[string]any
	if err = json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if payload["success"] != false || payload["message"] != errNoCETScores.Error() {
		t.Fatalf("payload=%#v", payload)
	}
}

func TestRunPrefetchStepsStopsAfterSessionExpiry(t *testing.T) {
	thirdRan := false
	ok, failed := runPrefetchSteps([]prefetchStep{
		{name: "courses", fn: func() error { return nil }},
		{name: "exams", fn: func() error { return jwc.ErrSessionExpired }},
		{name: "grades", fn: func() error { thirdRan = true; return nil }},
	})
	if thirdRan {
		t.Fatal("prefetch continued after session expiry")
	}
	if len(ok) != 1 || ok[0] != "courses" || len(failed) != 1 || failed[0] != "session_expired" {
		t.Fatalf("ok=%#v failed=%#v", ok, failed)
	}
}

func TestRunPrefetchStepsStopsAfterContextCancellation(t *testing.T) {
	thirdRan := false
	ok, failed := runPrefetchSteps([]prefetchStep{
		{name: "courses", fn: func() error { return nil }},
		{name: "exams", fn: func() error { return context.Canceled }},
		{name: "grades", fn: func() error { thirdRan = true; return nil }},
	})
	if thirdRan {
		t.Fatal("prefetch continued after context cancellation")
	}
	if len(ok) != 1 || ok[0] != "courses" || len(failed) != 1 || failed[0] != "exams" {
		t.Fatalf("ok=%#v failed=%#v", ok, failed)
	}
}

func TestSessionTimeoutContextCancelledWhenSessionDeleted(t *testing.T) {
	manager, err := session.NewManager(time.Hour, 10, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = manager.Close() })
	value := &session.Session{StudentID: "924101960012", JWC: jwc.New(nil)}
	token, err := manager.Add(t.Context(), value)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := contextWithSessionTimeout(context.Background(), value, time.Hour)
	defer cancel()
	if err = manager.Delete(t.Context(), token); err != nil {
		t.Fatal(err)
	}
	select {
	case <-ctx.Done():
		if !errors.Is(ctx.Err(), context.Canceled) {
			t.Fatalf("context error = %v", ctx.Err())
		}
	case <-time.After(time.Second):
		t.Fatal("prefetch context was not cancelled")
	}
}

func TestRefreshSchedulePersistsRequestedSemester(t *testing.T) {
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

	const studentID = "924101960010"
	const semester = "2026-2027-2"
	client := jwc.New(nil)
	client.StudentID = studentID
	client.HTTP.Transport = studentDataRoundTripFunc(func(request *http.Request) (*http.Response, error) {
		return &http.Response{
			StatusCode: http.StatusOK,
			Header:     make(http.Header),
			Body: io.NopCloser(strings.NewReader(
				`{"data":[{"kcmc":"高等数学","kcsj":"10102","jsxm":"教师","jsmc":"教室","kkzc":"1-16"}]}`,
			)),
			Request: request,
		}, nil
	})
	token, err := manager.Add(t.Context(), &session.Session{StudentID: studentID, JWC: client})
	if err != nil {
		t.Fatal(err)
	}

	mock.ExpectBegin()
	mock.ExpectExec("DELETE FROM courses").WithArgs(studentID, semester).WillReturnResult(sqlmock.NewResult(0, 0))
	prepared := mock.ExpectPrepare("INSERT INTO courses")
	prepared.ExpectExec().WithArgs(studentID, "高等数学", "教师", "教室", 1, 1, 2, "1-16", 0, semester, "", "", sqlmock.AnyArg()).WillReturnResult(sqlmock.NewResult(1, 1))
	mock.ExpectCommit()
	mock.ExpectExec("INSERT INTO user_settings").WithArgs(studentID, "semester", semester).WillReturnResult(sqlmock.NewResult(1, 1))
	mock.ExpectQuery("SELECT v FROM user_settings").WithArgs(studentID, "subscribe").WillReturnRows(sqlmock.NewRows([]string{"v"}))
	mock.ExpectExec("UPDATE reminder_tasks SET status='disabled'").WithArgs(studentID, semester, "exam").WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectExec("UPDATE reminder_tasks SET status='disabled'").WithArgs(studentID, semester, "grade").WillReturnResult(sqlmock.NewResult(0, 0))

	serverCtx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	server := &Server{
		store: store.New(db), sessions: manager,
		logger:   slog.New(slog.NewTextHandler(io.Discard, nil)),
		jwcSlots: make(chan struct{}, 1), dedupe: map[string]*inflight{}, cache: map[string]cacheEntry{}, ctx: serverCtx,
	}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/api/refresh-schedule?semester="+semester, nil)
	request.Header.Set(tokenHeader, token)
	server.refreshSchedule(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestRefreshAllPersistsRequestedSemesterWhenDomainsFail(t *testing.T) {
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

	const studentID = "924101960011"
	const semester = "2026-2027-2"
	client := jwc.New(nil)
	client.StudentID = studentID
	client.HTTP.Transport = studentDataRoundTripFunc(func(*http.Request) (*http.Response, error) {
		return nil, errors.New("教务暂不可用")
	})
	token, err := manager.Add(t.Context(), &session.Session{StudentID: studentID, JWC: client})
	if err != nil {
		t.Fatal(err)
	}
	mock.ExpectExec("INSERT INTO user_settings").WithArgs(studentID, "semester", semester).WillReturnResult(sqlmock.NewResult(1, 1))

	serverCtx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	server := &Server{
		store: store.New(db), sessions: manager,
		logger:   slog.New(slog.NewTextHandler(io.Discard, nil)),
		jwcSlots: make(chan struct{}, 1), dedupe: map[string]*inflight{}, cache: map[string]cacheEntry{}, ctx: serverCtx,
	}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/api/refresh-all?semester="+semester, nil)
	request.Header.Set(tokenHeader, token)
	server.refreshAll(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}
