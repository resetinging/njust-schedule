package httpapi

import (
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/resetinging/njust-schedule/internal/config"
	"github.com/resetinging/njust-schedule/internal/session"
)

func newPartnerTestServer(t *testing.T) (*Server, *session.Manager) {
	t.Helper()
	manager, err := session.NewManager(time.Hour, 10, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = manager.Close() })
	server := &Server{
		cfg: config.Config{
			PartnerPreviewEnabled:  true,
			PartnerPreviewUser:     "partner-preview",
			PartnerPreviewPassword: "strong-preview-password",
			PartnerPreviewName:     "合作商甲",
		},
		sessions: manager,
		logger:   slog.New(slog.NewTextHandler(io.Discard, nil)),
		rates:    map[string][]time.Time{},
	}
	return server, manager
}

func partnerLoginPayload() string {
	return `{"student_id":"partner-preview","password":"strong-preview-password"}`
}

func TestPartnerPreviewUsesSharedLoginEndpoint(t *testing.T) {
	server, _ := newPartnerTestServer(t)
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/api/login-webvpn", strings.NewReader(partnerLoginPayload()))
	request.RemoteAddr = "127.0.0.1:1234"
	server.login(recorder, request)
	if recorder.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
	var payload map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if payload["role"] != "partner" || payload["partner_mode"] != true || payload["token"] == "" {
		t.Fatalf("unexpected payload: %#v", payload)
	}
	value, ok := server.sessions.Get(t.Context(), payload["token"].(string))
	if !ok || !value.IsPartner() || value.StudentID != partnerPreviewSubjectID {
		t.Fatalf("unexpected partner session: %+v", value)
	}
}

func TestPartnerPreviewReturnsEmptyStudentData(t *testing.T) {
	server, _ := newPartnerTestServer(t)
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(
		http.MethodPost, "/api/login-webvpn",
		strings.NewReader(`{"student_id":"partner-preview","password":"wrong-password"}`),
	)
	server.login(recorder, request)
	if recorder.Code != http.StatusUnauthorized {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}

	token, err := server.sessions.Add(t.Context(), &session.Session{
		StudentID: partnerPreviewSubjectID, StudentName: "合作商甲",
		AccountType: "partner", LoginMethod: "partner-preview", Role: "partner",
	})
	if err != nil {
		t.Fatal(err)
	}
	for name, handler := range map[string]http.HandlerFunc{
		"courses": server.courses,
		"exams":   server.exams,
		"grades":  server.grades,
	} {
		t.Run(name, func(t *testing.T) {
			recorder := httptest.NewRecorder()
			request := httptest.NewRequest(http.MethodGet, "/api/"+name, nil)
			request.Header.Set(tokenHeader, token)
			handler(recorder, request)
			if recorder.Code != http.StatusOK || !strings.Contains(recorder.Body.String(), `"partner_mode":true`) {
				t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
			}
		})
	}
}
