package authn

import (
	"bytes"
	"context"
	"regexp"
	"testing"
	"time"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/resetinging/njust-schedule/internal/security"
	"github.com/resetinging/njust-schedule/internal/store"
)

func TestPersistentSessionRejectsFutureTimestamp(t *testing.T) {
	testPersistentSessionValidity(t, time.Now().Add(time.Hour), false)
}

func TestPersistentSessionAcceptsCurrentTimestamp(t *testing.T) {
	testPersistentSessionValidity(t, time.Now().Add(-time.Minute), true)
}

func TestPersistentSessionRejectsExpiredTimestamp(t *testing.T) {
	testPersistentSessionValidity(t, time.Now().Add(-31*24*time.Hour), false)
}

func testPersistentSessionValidity(t *testing.T, timestamp time.Time, want bool) {
	t.Helper()
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	crypto, err := security.New(bytes.Repeat([]byte{2}, 32))
	if err != nil {
		t.Fatal(err)
	}
	const sid = "924101960000"
	value := store.PersistentSession{
		Timestamp: timestamp.Unix(),
		Cookies:   []store.Cookie{{Name: "JSESSIONID", Value: "value", Domain: "bkjw.njust.edu.cn", Path: "/"}},
	}
	blob, err := crypto.Encrypt(sid, value)
	if err != nil {
		t.Fatal(err)
	}
	mock.ExpectQuery(regexp.QuoteMeta("SELECT v FROM user_settings WHERE student_id=? AND k=?")).
		WithArgs(sid, persistentSessionKey).
		WillReturnRows(sqlmock.NewRows([]string{"v"}).AddRow(blob))

	service := New(store.New(db), crypto, 30*24*time.Hour, 24*time.Hour)
	if _, ok := service.PersistentSession(context.Background(), sid); ok != want {
		t.Fatalf("PersistentSession() valid = %v, want %v", ok, want)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}
