package httpapi

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestReserveQRHasBoundedCapacityAndReclaimsExpiredEntries(t *testing.T) {
	server := &Server{qrs: map[string]*qrSession{}}
	for i := 0; i < maxQRSessions; i++ {
		if _, ok := server.reserveQR(nil); !ok {
			t.Fatalf("reserve %d failed before capacity", i)
		}
	}
	if _, ok := server.reserveQR(nil); ok {
		t.Fatal("reserve should fail at capacity")
	}

	server.qrMu.Lock()
	for _, item := range server.qrs {
		item.expiresAt = time.Now().Add(-time.Second)
		break
	}
	server.qrMu.Unlock()
	if _, ok := server.reserveQR(nil); !ok {
		t.Fatal("expired QR session was not reclaimed")
	}
	if len(server.qrs) != maxQRSessions {
		t.Fatalf("QR session count = %d", len(server.qrs))
	}
}

func TestQRStatusReplaysCompletedLoginPayload(t *testing.T) {
	payload := map[string]any{"success": true, "status": "ok", "token": "test-token"}
	server := &Server{qrs: map[string]*qrSession{
		"completed": {finished: true, payload: payload, expiresAt: time.Now().Add(time.Minute)},
	}}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/api/sso-qr/status?qr_id=completed", nil)

	server.qrStatus(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	var result map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if result["token"] != "test-token" || result["status"] != "ok" {
		t.Fatalf("unexpected payload: %#v", result)
	}
}
