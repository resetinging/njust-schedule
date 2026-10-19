package httpapi

import (
	"bytes"
	"context"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"testing"
	"time"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/resetinging/njust-schedule/internal/authn"
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
