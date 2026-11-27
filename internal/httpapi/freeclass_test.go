package httpapi

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/resetinging/njust-schedule/internal/authn"
	"github.com/resetinging/njust-schedule/internal/config"
	"github.com/resetinging/njust-schedule/internal/jwc"
	"github.com/resetinging/njust-schedule/internal/security"
	"github.com/resetinging/njust-schedule/internal/session"
	"github.com/resetinging/njust-schedule/internal/store"
)

type closeTrackingTransport struct{ closed int }

func (*closeTrackingTransport) RoundTrip(*http.Request) (*http.Response, error) {
	return nil, errors.New("not implemented")
}

func (t *closeTrackingTransport) CloseIdleConnections() { t.closed++ }

func TestCloseSharedJWCCandidatesOnlyClosesOwnedClients(t *testing.T) {
	ownedTransport := &closeTrackingTransport{}
	activeTransport := &closeTrackingTransport{}
	ownedClient := jwc.New(nil)
	ownedClient.HTTP.Transport = ownedTransport
	activeClient := jwc.New(nil)
	activeClient.HTTP.Transport = activeTransport

	closeSharedJWCCandidates([]sharedJWCCandidate{
		{client: ownedClient, owned: true},
		{client: activeClient, sess: &session.Session{}, owned: false},
	})

	if ownedTransport.closed != 1 || activeTransport.closed != 0 {
		t.Fatalf("close counts: owned=%d active=%d", ownedTransport.closed, activeTransport.closed)
	}
}

func TestRandomPersistentClientsKeepsActiveCandidatesWhenStoreFails(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	mock.ExpectQuery("SELECT COALESCE\\(student_id").
		WithArgs("jwc_session").
		WillReturnError(errors.New("database unavailable"))

	crypto, err := security.New(bytes.Repeat([]byte{1}, 32))
	if err != nil {
		t.Fatal(err)
	}
	manager, err := session.NewManager(time.Hour, 10, "", crypto)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = manager.Close() })
	client := jwc.New(nil)
	client.StudentID = "924101960000"
	if _, err = manager.Add(context.Background(), &session.Session{
		StudentID: "924101960000", AccountType: "undergraduate", JWC: client,
	}); err != nil {
		t.Fatal(err)
	}

	repository := store.New(db)
	server := &Server{
		auth:     authn.New(repository, crypto, 30*24*time.Hour, 24*time.Hour),
		sessions: manager,
		logger:   slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
	candidates := server.randomPersistentClients(context.Background())
	if len(candidates) != 1 || candidates[0].sid != "924101960000" || candidates[0].source != "active-session" {
		t.Fatalf("unexpected candidates: %#v", candidates)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestFreeClassroomQueryReturnsPendingWithoutLiveJWCFetch(t *testing.T) {
	manager, err := session.NewManager(time.Hour, 10, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = manager.Close() })
	token, err := manager.Add(t.Context(), &session.Session{
		StudentID: "924101960000", AccountType: "undergraduate",
	})
	if err != nil {
		t.Fatal(err)
	}
	server := &Server{
		cfg:      config.Config{JWCRequestTimeout: time.Second},
		sessions: manager,
		cache:    map[string]cacheEntry{},
		logger:   slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(
		http.MethodGet,
		"/api/free-classrooms?semester=2026-2027-1&week=3&weekday=3&jc1=6&jc2=7",
		nil,
	)
	request.Header.Set(tokenHeader, token)

	server.freeClassrooms(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
	var payload struct {
		Success bool     `json:"success"`
		Pending bool     `json:"pending"`
		Rooms   []string `json:"rooms"`
	}
	if err = json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if !payload.Success || !payload.Pending || len(payload.Rooms) != 0 {
		t.Fatalf("unexpected payload: %#v", payload)
	}
}

func TestFreeClassroomQueryReturnsCachedSnapshot(t *testing.T) {
	manager, err := session.NewManager(time.Hour, 10, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = manager.Close() })
	token, err := manager.Add(t.Context(), &session.Session{
		StudentID: "924101960000", AccountType: "undergraduate",
	})
	if err != nil {
		t.Fatal(err)
	}
	server := &Server{
		sessions: manager,
		cache:    map[string]cacheEntry{},
		logger:   slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
	cached := map[string]any{
		"success": true, "pending": false, "count": 1,
		"rooms": []string{"Ⅰ-A101"}, "buildings": []string{"Ⅰ教学楼"},
	}
	server.cacheSet(
		freeClassCacheKey("孝陵卫", 3, 6, 7, 3, "2026-2027-1", ""),
		cached,
		time.Hour,
	)
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(
		http.MethodGet,
		"/api/free-classrooms?semester=2026-2027-1&week=3&weekday=3&jc1=6&jc2=7",
		nil,
	)
	request.Header.Set(tokenHeader, token)

	server.freeClassrooms(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
	var payload struct {
		Success bool     `json:"success"`
		Pending bool     `json:"pending"`
		Rooms   []string `json:"rooms"`
	}
	if err = json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if !payload.Success || payload.Pending || len(payload.Rooms) != 1 || payload.Rooms[0] != "Ⅰ-A101" {
		t.Fatalf("unexpected payload: %#v", payload)
	}
}
