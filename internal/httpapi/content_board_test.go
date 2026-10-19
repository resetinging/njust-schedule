package httpapi

import (
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/resetinging/njust-schedule/internal/store"
)

func TestLegacyContentBoardBuildsPinnedAnnouncement(t *testing.T) {
	board := legacyContentBoard(map[string]string{
		"announcement_text":    "成绩查询已更新",
		"announcement_enabled": "1",
		"announcement_updated": "2026-10-19 10:00:00",
	})

	if len(board.Announcements) != 1 {
		t.Fatalf("announcements = %d", len(board.Announcements))
	}
	item := board.Announcements[0]
	if !item.Pinned || !item.Enabled || item.Body != "成绩查询已更新" || item.PublishedAt != "2026-10-19" {
		t.Fatalf("unexpected legacy announcement: %+v", item)
	}
}

func TestNormalizeAndValidateContentBoard(t *testing.T) {
	board := contentBoard{
		Announcements: []contentAnnouncement{{
			Title:   " 新公告 ",
			Body:    " 正文 ",
			Enabled: true,
		}},
		Community: contentCommunity{Name: " 交流群 ", QQ: "123456789"},
	}
	normalizeContentBoard(&board, "2026-10-19 12:00:00")
	if err := validateContentBoard(board); err != nil {
		t.Fatal(err)
	}
	if board.Announcements[0].ID == "" || board.Announcements[0].PublishedAt != "2026-10-19" {
		t.Fatalf("announcement was not normalized: %+v", board.Announcements[0])
	}
	if board.Announcements[0].Type != "notice" || board.Announcements[0].Priority != "normal" {
		t.Fatalf("announcement defaults missing: %+v", board.Announcements[0])
	}
}

func TestValidateContentBoardRejectsInvalidQQGroup(t *testing.T) {
	board := contentBoard{
		Announcements: []contentAnnouncement{},
		Community:     contentCommunity{QQ: "qq-123"},
	}
	if err := validateContentBoard(board); err == nil || !strings.Contains(err.Error(), "QQ 群号") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestValidateContentBoardRejectsPayloadLargerThanSettingsText(t *testing.T) {
	board := contentBoard{
		Announcements: []contentAnnouncement{},
	}
	for index := 0; index < 20; index++ {
		board.Announcements = append(board.Announcements, contentAnnouncement{
			ID:          "announcement-" + strings.Repeat("x", index+1),
			Title:       "公告",
			Body:        strings.Repeat("测", maxAnnouncementBody),
			Type:        "notice",
			Priority:    "normal",
			PublishedAt: "2026-10-19",
			Enabled:     true,
		})
	}
	if err := validateContentBoard(board); err == nil || !strings.Contains(err.Error(), "内容过长") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestPublicContentBoardFiltersAndSorts(t *testing.T) {
	board := contentBoard{
		Announcements: []contentAnnouncement{
			{ID: "old", Title: "旧公告", Priority: "normal", PublishedAt: "2026-10-10", Enabled: true},
			{ID: "pinned", Title: "置顶公告", Priority: "important", PublishedAt: "2026-10-01", Enabled: true, Pinned: true},
			{ID: "urgent", Title: "紧急公告", Priority: "urgent", PublishedAt: "2026-09-01", Enabled: true},
			{ID: "expired", Title: "过期公告", Priority: "urgent", PublishedAt: "2026-09-01", ExpiresAt: "2000-01-01", Enabled: true},
			{ID: "disabled", Title: "隐藏公告", Priority: "urgent", PublishedAt: "2026-10-20", Enabled: false},
		},
	}
	public := publicContentBoard(board)
	if len(public.Announcements) != 3 || public.Announcements[0].ID != "urgent" || public.Announcements[1].ID != "pinned" {
		t.Fatalf("announcements = %+v", public.Announcements)
	}
}

func TestValidateContentBoardRejectsInvalidAnnouncementMetadata(t *testing.T) {
	board := contentBoard{
		Announcements: []contentAnnouncement{{
			ID:          "a1",
			Title:       "公告",
			Body:        "正文",
			Type:        "unknown",
			Priority:    "important",
			PublishedAt: "2026-10-19",
			Enabled:     true,
		}},
	}
	if err := validateContentBoard(board); err == nil || !strings.Contains(err.Error(), "公告类型无效") {
		t.Fatalf("unexpected error: %v", err)
	}

	board.Announcements[0].Type = "notice"
	board.Announcements[0].EffectiveAt = "2026-10-21"
	board.Announcements[0].ExpiresAt = "2026-10-20"
	if err := validateContentBoard(board); err == nil || !strings.Contains(err.Error(), "失效日期不能早于生效日期") {
		t.Fatalf("unexpected date error: %v", err)
	}
}

func TestContentBoardEndpointReturnsPublicPayload(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	mock.ExpectQuery("SELECT k,COALESCE").
		WithArgs(contentBoardKey, "announcement_text", "announcement_enabled", "announcement_updated").
		WillReturnRows(sqlmock.NewRows([]string{"k", "v"}).
			AddRow(contentBoardKey, `{"updated":"2026-10-19 12:00:00","announcements":[{"id":"a1","title":"公告","body":"正文","published_at":"2026-10-19","enabled":true}],"community":{"qq":"123456789"}}`))
	server := &Server{
		store:  store.New(db),
		logger: slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/api/content-board", nil)
	testHandler(t, server).ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	body := recorder.Body.String()
	if !strings.Contains(body, `"title":"公告"`) || !strings.Contains(body, `"qq":"123456789"`) {
		t.Fatalf("unexpected body: %s", body)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestLegacyAnnouncementEndpointUsesLatestBoardItem(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	mock.ExpectQuery("SELECT k,COALESCE").
		WithArgs(contentBoardKey, "announcement_text", "announcement_enabled", "announcement_updated").
		WillReturnRows(sqlmock.NewRows([]string{"k", "v"}).
			AddRow(contentBoardKey, `{"updated":"2026-10-19 12:00:00","announcements":[{"id":"a1","title":"公告","body":"最新公告正文","published_at":"2026-10-19","enabled":true,"pinned":true}],"community":{}}`))
	server := &Server{
		store:  store.New(db),
		logger: slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/api/announcement", nil)
	testHandler(t, server).ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	body := recorder.Body.String()
	if !strings.Contains(body, `"text":"最新公告正文"`) || !strings.Contains(body, `"enabled":true`) {
		t.Fatalf("unexpected body: %s", body)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}
