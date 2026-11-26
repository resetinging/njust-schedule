package httpapi

import (
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/resetinging/njust-schedule/internal/config"
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
	if !strings.Contains(body, `"title":"公告"`) || !strings.Contains(body, `"qq":"123456789"`) || !strings.Contains(body, `"competitions":[]`) {
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

func validCompetition() contentCompetition {
	return contentCompetition{
		ID: "comp-1", Title: "高等数学竞赛", Summary: "报名通知",
		PublishedAt: "2026-10-20", Deadline: "2026-11-01",
		SourceURL: "https://xspace.njust.edu.cn/14263/list.htm", Enabled: true,
	}
}

func TestValidateContentBoardCompetitions(t *testing.T) {
	board := contentBoard{Announcements: []contentAnnouncement{}, Competitions: []contentCompetition{validCompetition()}}
	normalizeContentBoard(&board, "2026-10-19 12:00:00")
	if err := validateContentBoard(board); err != nil {
		t.Fatal(err)
	}

	cases := []struct {
		name string
		edit func(*contentCompetition)
		want string
	}{
		{name: "缺少 ID", edit: func(c *contentCompetition) { c.ID = "" }, want: "竞赛 ID 无效或重复"},
		{name: "缺少标题", edit: func(c *contentCompetition) { c.Title = " " }, want: "标题不能为空"},
		{name: "摘要正文都空", edit: func(c *contentCompetition) { c.Summary = ""; c.Body = "" }, want: "摘要或正文不能为空"},
		{name: "缺少发布日期", edit: func(c *contentCompetition) { c.PublishedAt = "" }, want: "发布日期格式无效"},
		{name: "发布日期非法", edit: func(c *contentCompetition) { c.PublishedAt = "2026-13-01" }, want: "发布日期格式无效"},
		{name: "截止日期非法", edit: func(c *contentCompetition) { c.Deadline = "2026-02-30" }, want: "截止日期格式无效"},
		{name: "截止早于发布", edit: func(c *contentCompetition) { c.Deadline = "2026-10-01" }, want: "截止日期不能早于发布日期"},
		{name: "http 链接", edit: func(c *contentCompetition) { c.SourceURL = "http://xspace.njust.edu.cn/a" }, want: "官方 HTTPS"},
		{name: "非官方域名", edit: func(c *contentCompetition) { c.SourceURL = "https://evil.example.com/a" }, want: "njust.edu.cn"},
		{name: "仿冒子域", edit: func(c *contentCompetition) { c.SourceURL = "https://njust.edu.cn.evil.com/a" }, want: "njust.edu.cn"},
		{name: "缺少链接", edit: func(c *contentCompetition) { c.SourceURL = "" }, want: "原文链接不能为空"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			item := validCompetition()
			tc.edit(&item)
			invalid := contentBoard{Announcements: []contentAnnouncement{}, Competitions: []contentCompetition{item}}
			if err := validateContentBoard(invalid); err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("error=%v, want contains %q", err, tc.want)
			}
		})
	}

	for _, source := range []string{
		"https://xspace.njust.edu.cn/14263/list.htm",
		"https://jwc.njust.edu.cn/7f/f9/c1217a294905/page.htm",
		"https://njust.edu.cn/a",
	} {
		item := validCompetition()
		item.SourceURL = source
		valid := contentBoard{Announcements: []contentAnnouncement{}, Competitions: []contentCompetition{item}}
		if err := validateContentBoard(valid); err != nil {
			t.Fatalf("合法官方 HTTPS 被拒绝 %s: %v", source, err)
		}
	}
}

func TestPublicContentBoardCompetitionsFiltersAndSorts(t *testing.T) {
	board := contentBoard{
		Announcements: []contentAnnouncement{},
		Competitions: []contentCompetition{
			{ID: "old", Title: "旧竞赛", Summary: "旧", PublishedAt: "2026-10-01", Enabled: true},
			{ID: "new", Title: "新竞赛", Body: "新正文", PublishedAt: "2026-10-20", Deadline: "", SourceURL: "https://xspace.njust.edu.cn/new", Enabled: true},
			{ID: "disabled", Title: "隐藏竞赛", Summary: "隐藏", PublishedAt: "2026-10-30", Enabled: false},
		},
	}
	public := publicContentBoard(board)
	if len(public.Competitions) != 2 || public.Competitions[0].ID != "new" || public.Competitions[1].ID != "old" {
		t.Fatalf("competitions = %+v", public.Competitions)
	}
	if public.Competitions[0].Deadline != "" {
		t.Fatalf("deadline should stay empty: %+v", public.Competitions[0])
	}
}

func TestAdminSaveContentBoardRejectsInvalidCompetitionSource(t *testing.T) {
	server := &Server{cfg: config.Config{SessionKey: make([]byte, 32), AdminPassword: "secret"}}
	body := `{"board":{"announcements":[],"competitions":[{"id":"c1","title":"竞赛","summary":"摘要","published_at":"2026-10-20","source_url":"http://evil.example.com/a","enabled":true}],"community":{}}}`
	request := httptest.NewRequest(http.MethodPost, "/api/admin/content-board", strings.NewReader(body))
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("X-Admin-Token", server.issueAdminToken())
	recorder := httptest.NewRecorder()
	server.adminSaveContentBoard(recorder, request)
	if recorder.Code != http.StatusBadRequest {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
	if !strings.Contains(recorder.Body.String(), "原文链接") {
		t.Fatalf("unexpected body: %s", recorder.Body.String())
	}
}
