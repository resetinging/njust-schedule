package httpapi

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/naughtygopher/webgo/v7"
	"github.com/resetinging/njust-schedule/internal/config"
	"github.com/resetinging/njust-schedule/internal/session"
	"github.com/resetinging/njust-schedule/internal/store"
)

func TestStaticFileServesUnicodeNameAndRejectsTraversal(t *testing.T) {
	root := t.TempDir()
	gallery := filepath.Join(root, "gallery")
	if err := os.MkdirAll(gallery, 0o755); err != nil {
		t.Fatal(err)
	}
	content := []byte("image-content")
	if err := os.WriteFile(filepath.Join(gallery, "校历.png"), content, 0o644); err != nil {
		t.Fatal(err)
	}
	server := &Server{cfg: config.Config{StaticDir: root}}
	router := webgo.NewRouter(&webgo.Config{}, server.routes()...)
	httpServer := httptest.NewServer(router)
	defer httpServer.Close()

	response, err := http.Get(httpServer.URL + "/static/gallery/" + url.PathEscape("校历.png"))
	if err != nil {
		t.Fatal(err)
	}
	body, err := io.ReadAll(response.Body)
	response.Body.Close()
	if err != nil {
		t.Fatal(err)
	}
	if response.StatusCode != http.StatusOK || string(body) != string(content) {
		t.Fatalf("unicode static status=%d body=%q", response.StatusCode, body)
	}

	response, err = http.Get(httpServer.URL + "/static/%2e%2e/%2e%2e/etc/passwd")
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != http.StatusNotFound {
		t.Fatalf("traversal status=%d, want 404", response.StatusCode)
	}
}

func TestGalleryImagesReportsDirectoryFailure(t *testing.T) {
	server := &Server{cfg: config.Config{StaticDir: t.TempDir()}}
	recorder := httptest.NewRecorder()
	server.galleryImages(recorder, httptest.NewRequest(http.MethodGet, "/api/gallery-images", nil))
	if recorder.Code != http.StatusInternalServerError {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
}

func TestGalleryImagePartReturnsExactChunk(t *testing.T) {
	root := t.TempDir()
	directory := filepath.Join(root, "gallery")
	if err := os.Mkdir(directory, 0o755); err != nil {
		t.Fatal(err)
	}
	raw := append(bytes.Repeat([]byte{'a'}, galleryChunkBytes), []byte("tail")...)
	if err := os.WriteFile(filepath.Join(directory, "large.png"), raw, 0o600); err != nil {
		t.Fatal(err)
	}
	server := &Server{cfg: config.Config{StaticDir: root}}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/api/gallery-image-part?name=large.png&part=1", nil)
	server.galleryImagePart(recorder, request)
	if recorder.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
	var payload struct {
		Part int    `json:"part"`
		Data string `json:"data_b64"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	decoded, err := base64.StdEncoding.DecodeString(payload.Data)
	if err != nil {
		t.Fatal(err)
	}
	if payload.Part != 1 || string(decoded) != "tail" {
		t.Fatalf("part=%d data=%q", payload.Part, decoded)
	}
}

func TestGalleryRejectsTraversal(t *testing.T) {
	server := &Server{cfg: config.Config{StaticDir: t.TempDir()}}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/api/gallery-image?name=../secret.png", nil)
	server.galleryImage(recorder, request)
	if recorder.Code != http.StatusNotFound {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
}

func TestJWBrowserProxyRejectsOversizedForm(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	manager, err := session.NewManager(time.Hour, 10, "", nil, logger)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = manager.Close() })
	token, err := manager.Add(t.Context(), &session.Session{StudentID: "924101960000"})
	if err != nil {
		t.Fatal(err)
	}
	server := &Server{logger: logger, sessions: manager}
	body := "value=" + strings.Repeat("x", (2<<20)+1)
	request := httptest.NewRequest(http.MethodPost, "/proxy/jw/example", strings.NewReader(body))
	request.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	request.Header.Set(tokenHeader, token)
	recorder := httptest.NewRecorder()
	testHandler(t, server).ServeHTTP(recorder, request)
	if recorder.Code != http.StatusBadRequest {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
}

func TestSendSubscribeRejectsUnencodablePayload(t *testing.T) {
	server := &Server{
		cfg:   config.Config{MPAppID: "appid", MPSecret: "secret"},
		cache: map[string]cacheEntry{"wechat-access-token": {value: "token", expiresAt: time.Now().Add(time.Hour)}},
	}
	result := server.sendSubscribePage(t.Context(), "openid", "template", "pages/main/main", map[string]any{"bad": make(chan int)})
	if result["ok"] != false || !strings.Contains(result["errmsg"].(string), "编码失败") {
		t.Fatalf("unexpected result: %#v", result)
	}
}

func TestServiceAccountClientPropagatesSettingsFailure(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	mock.ExpectQuery("SELECT v FROM settings").WithArgs("free_classroom_sid").WillReturnError(errors.New("database unavailable"))
	server := &Server{store: store.New(db)}
	if _, _, err = server.serviceAccountClient(t.Context()); err == nil || !strings.Contains(err.Error(), "读取本科服务账号") {
		t.Fatalf("unexpected error: %v", err)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}
