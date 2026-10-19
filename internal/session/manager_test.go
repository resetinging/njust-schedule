package session

import (
	"bytes"
	"context"
	"net/http"
	"net/url"
	"reflect"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/resetinging/njust-schedule/internal/jwc"
	"github.com/resetinging/njust-schedule/internal/security"
	"github.com/resetinging/njust-schedule/internal/store"
)

func newTestManager(t *testing.T) (*Manager, *miniredis.Miniredis) {
	t.Helper()
	redisServer := miniredis.RunT(t)
	crypto, err := security.New(bytes.Repeat([]byte{1}, 32))
	if err != nil {
		t.Fatal(err)
	}
	manager, err := NewManager(time.Hour, 10, "redis://"+redisServer.Addr()+"/0", crypto)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = manager.Close() })
	return manager, redisServer
}

func TestAddSupersedesStudentSession(t *testing.T) {
	ctx := context.Background()
	manager, redisServer := newTestManager(t)
	first, err := manager.Add(ctx, &Session{StudentID: "924101960000", StudentName: "甲"})
	if err != nil {
		t.Fatal(err)
	}
	second, err := manager.Add(ctx, &Session{StudentID: "924101960000", StudentName: "乙"})
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := manager.Get(ctx, first); ok {
		t.Fatal("superseded token is still accepted")
	}
	if got, ok := manager.Get(ctx, second); !ok || got.StudentName != "乙" {
		t.Fatalf("new token unavailable: %#v, %v", got, ok)
	}
	if redisServer.Exists("wx:session:token:" + first) {
		t.Fatal("superseded remote token was not deleted")
	}
	if got, err := redisServer.Get("wx:session:sid:924101960000"); err != nil || got != second {
		t.Fatalf("student mapping = %q, err=%v", got, err)
	}
}

func TestReadyReportsRedisState(t *testing.T) {
	ctx := context.Background()
	manager, redisServer := newTestManager(t)
	if enabled, err := manager.Ready(ctx); !enabled || err != nil {
		t.Fatalf("Ready() = %v, %v", enabled, err)
	}
	redisServer.Close()
	if enabled, err := manager.Ready(ctx); !enabled || err == nil {
		t.Fatalf("Ready() after shutdown = %v, %v", enabled, err)
	}
}

func TestDeleteStudentRemovesRemoteMapping(t *testing.T) {
	ctx := context.Background()
	manager, redisServer := newTestManager(t)
	token, err := manager.Add(ctx, &Session{StudentID: "924101960001"})
	if err != nil {
		t.Fatal(err)
	}
	removed, err := manager.DeleteStudent(ctx, "924101960001")
	if err != nil {
		t.Fatal(err)
	}
	if !removed {
		t.Fatal("DeleteStudent reported no session")
	}
	if redisServer.Exists("wx:session:token:"+token) || redisServer.Exists("wx:session:sid:924101960001") {
		t.Fatal("remote session keys were not deleted")
	}
}

type closeTrackingTransport struct{ closed int }

func (*closeTrackingTransport) RoundTrip(*http.Request) (*http.Response, error) {
	return nil, nil
}

func (t *closeTrackingTransport) CloseIdleConnections() { t.closed++ }

func TestDeleteClosesSessionConnections(t *testing.T) {
	manager, _ := newTestManager(t)
	transport := &closeTrackingTransport{}
	client := jwc.New(nil)
	client.HTTP.Transport = transport
	value := &Session{StudentID: "924101960008", JWC: client}
	token, err := manager.Add(t.Context(), value)
	if err != nil {
		t.Fatal(err)
	}
	if err = manager.Delete(t.Context(), token); err != nil {
		t.Fatal(err)
	}
	if transport.closed != 1 {
		t.Fatalf("CloseIdleConnections calls = %d", transport.closed)
	}
	select {
	case <-value.Context().Done():
	default:
		t.Fatal("deleted session lifecycle was not cancelled")
	}
}

func TestDeleteStudentPreservesConcurrentReplacementMapping(t *testing.T) {
	ctx := context.Background()
	manager, redisServer := newTestManager(t)
	oldToken, err := manager.Add(ctx, &Session{StudentID: "924101960006"})
	if err != nil {
		t.Fatal(err)
	}
	const replacement = "replacement-token"
	redisServer.Set("wx:session:sid:924101960006", replacement)
	redisServer.Set("wx:session:token:"+replacement, "replacement-payload")

	removed, err := manager.DeleteStudent(ctx, "924101960006")
	if err != nil || !removed {
		t.Fatalf("DeleteStudent() = %v, %v", removed, err)
	}
	if redisServer.Exists("wx:session:token:" + oldToken) {
		t.Fatal("old token was not deleted")
	}
	if got, getErr := redisServer.Get("wx:session:sid:924101960006"); getErr != nil || got != replacement {
		t.Fatalf("replacement mapping = %q, err=%v", got, getErr)
	}
	if !redisServer.Exists("wx:session:token:" + replacement) {
		t.Fatal("replacement token was deleted")
	}
}

func TestDeleteStudentRemovesRemoteOnlySession(t *testing.T) {
	ctx := context.Background()
	manager, redisServer := newTestManager(t)
	token, err := manager.Add(ctx, &Session{StudentID: "924101960007"})
	if err != nil {
		t.Fatal(err)
	}
	remoteManager, err := NewManager(time.Hour, 10, "redis://"+redisServer.Addr()+"/0", manager.crypto)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = remoteManager.Close() })

	removed, err := remoteManager.DeleteStudent(ctx, "924101960007")
	if err != nil || !removed {
		t.Fatalf("DeleteStudent() = %v, %v", removed, err)
	}
	if redisServer.Exists("wx:session:token:"+token) || redisServer.Exists("wx:session:sid:924101960007") {
		t.Fatal("remote-only session keys were not deleted")
	}
}

func TestDeleteStudentReportsRedisFailure(t *testing.T) {
	ctx := context.Background()
	manager, redisServer := newTestManager(t)
	if _, err := manager.Add(ctx, &Session{StudentID: "924101960003"}); err != nil {
		t.Fatal(err)
	}
	redisServer.Close()
	if removed, err := manager.DeleteStudent(ctx, "924101960003"); err == nil || removed {
		t.Fatalf("DeleteStudent() = %v, %v; want Redis error", removed, err)
	}
}

func TestAddDoesNotReplaceMemorySessionWhenRedisFails(t *testing.T) {
	ctx := context.Background()
	manager, redisServer := newTestManager(t)
	first, err := manager.Add(ctx, &Session{StudentID: "924101960002", StudentName: "原会话"})
	if err != nil {
		t.Fatal(err)
	}
	redisServer.Close()

	if token, addErr := manager.Add(ctx, &Session{StudentID: "924101960002", StudentName: "半成功会话"}); addErr == nil || token != "" {
		t.Fatalf("Add() = %q, %v; want empty token and Redis error", token, addErr)
	}
	if manager.Count() != 1 {
		t.Fatalf("session count = %d", manager.Count())
	}
	if got, ok := manager.Get(ctx, first); !ok || got.StudentName != "原会话" {
		t.Fatalf("original session was replaced: %#v, %v", got, ok)
	}
}

func TestReadsDoNotWaitForRemoteMutationSerialization(t *testing.T) {
	manager, _ := newTestManager(t)
	manager.mutationMu.Lock()
	defer manager.mutationMu.Unlock()

	done := make(chan int, 1)
	go func() { done <- manager.Count() }()
	select {
	case count := <-done:
		if count != 0 {
			t.Fatalf("session count = %d", count)
		}
	case <-time.After(time.Second):
		t.Fatal("内存会话读取被远端变更锁阻塞")
	}
}

func TestSaveRemoteUsesLatestJWCCookies(t *testing.T) {
	ctx := context.Background()
	manager, redisServer := newTestManager(t)
	initial := []store.Cookie{{Name: "JSESSIONID", Value: "old", Domain: "bkjw.njust.edu.cn", Path: "/"}}
	client := jwc.New(initial)
	value := &Session{StudentID: "924101960004", Cookies: initial, JWC: client}
	token, err := manager.Add(ctx, value)
	if err != nil {
		t.Fatal(err)
	}

	target, _ := url.Parse("https://bkjw.njust.edu.cn/njlgdx/framework/main.jsp")
	client.HTTP.Jar.SetCookies(target, []*http.Cookie{{Name: "JSESSIONID", Value: "new", Domain: "bkjw.njust.edu.cn", Path: "/"}})
	if err = manager.saveRemote(ctx, value); err != nil {
		t.Fatal(err)
	}

	blob, err := redisServer.Get("wx:session:token:" + token)
	if err != nil {
		t.Fatal(err)
	}
	var saved Session
	if err = manager.crypto.Decrypt(token, blob, &saved); err != nil {
		t.Fatal(err)
	}
	want := []store.Cookie{{Name: "JSESSIONID", Value: "new", Domain: "bkjw.njust.edu.cn", Path: "/"}}
	if !reflect.DeepEqual(saved.Cookies, want) {
		t.Fatalf("saved cookies = %#v, want %#v", saved.Cookies, want)
	}
}

func TestGetRejectsLocalSessionSupersededInRedis(t *testing.T) {
	ctx := context.Background()
	manager, redisServer := newTestManager(t)
	value := &Session{StudentID: "924101960005", StudentName: "旧会话"}
	token, err := manager.Add(ctx, value)
	if err != nil {
		t.Fatal(err)
	}
	value.remoteSaved = time.Now().Add(-2 * time.Minute)
	const replacement = "replacement-token"
	redisServer.Set("wx:session:sid:"+value.StudentID, replacement)

	if got, ok := manager.Get(ctx, token); ok || got != nil {
		t.Fatalf("superseded local session is still accepted: %#v, %v", got, ok)
	}
	if manager.Count() != 0 {
		t.Fatalf("superseded local session was not removed: count=%d", manager.Count())
	}
	if got, err := redisServer.Get("wx:session:sid:" + value.StudentID); err != nil || got != replacement {
		t.Fatalf("replacement mapping = %q, err=%v", got, err)
	}
}
