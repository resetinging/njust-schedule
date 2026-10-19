package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"sort"
	"strings"
	"time"
)

const contentBoardKey = "content_board_v1"

const (
	maxContentAnnouncements = 20
	maxAnnouncementBody     = 3000
	maxAnnouncementAudience = 40
	maxAnnouncementAction   = 200
	// settings.v is MySQL TEXT (65535 bytes); leave headroom for SQL/schema limits.
	maxContentBoardBytes = 60000
)

type contentAnnouncement struct {
	ID          string `json:"id"`
	Title       string `json:"title"`
	Body        string `json:"body"`
	Type        string `json:"type"`
	Priority    string `json:"priority"`
	Audience    string `json:"audience"`
	Action      string `json:"action"`
	PublishedAt string `json:"published_at"`
	EffectiveAt string `json:"effective_at"`
	ExpiresAt   string `json:"expires_at"`
	Pinned      bool   `json:"pinned"`
	Enabled     bool   `json:"enabled"`
}

type contentCommunity struct {
	Name string `json:"name"`
	QQ   string `json:"qq"`
	Note string `json:"note"`
}

type contentBoard struct {
	Updated       string                `json:"updated"`
	Announcements []contentAnnouncement `json:"announcements"`
	Community     contentCommunity      `json:"community"`
}

var contentAnnouncementTypes = map[string]bool{
	"notice":      true,
	"maintenance": true,
	"feature":     true,
	"deadline":    true,
	"issue":       true,
}

var contentAnnouncementPriorities = map[string]bool{
	"normal":    true,
	"important": true,
	"urgent":    true,
}

func (s *Server) loadContentBoard(ctx context.Context) (contentBoard, error) {
	settings, err := s.store.Settings(
		ctx,
		contentBoardKey,
		"announcement_text",
		"announcement_enabled",
		"announcement_updated",
	)
	if err != nil {
		return contentBoard{}, err
	}
	if raw := strings.TrimSpace(settings[contentBoardKey]); raw != "" {
		var board contentBoard
		if err = json.Unmarshal([]byte(raw), &board); err != nil {
			return contentBoard{}, fmt.Errorf("解析信息中心数据失败: %w", err)
		}
		normalizeContentBoard(&board, board.Updated)
		return board, nil
	}
	return legacyContentBoard(settings), nil
}

func legacyContentBoard(settings map[string]string) contentBoard {
	updated := strings.TrimSpace(settings["announcement_updated"])
	text := strings.TrimSpace(settings["announcement_text"])
	board := contentBoard{
		Updated:       updated,
		Announcements: []contentAnnouncement{},
		Community:     contentCommunity{},
	}
	if text != "" && settings["announcement_enabled"] != "0" {
		board.Announcements = append(board.Announcements, contentAnnouncement{
			ID:          "legacy-announcement",
			Title:       "公告",
			Body:        text,
			Type:        "notice",
			Priority:    "important",
			PublishedAt: contentDate(updated),
			Pinned:      true,
			Enabled:     true,
		})
	}
	normalizeContentBoard(&board, updated)
	return board
}

func normalizeContentBoard(board *contentBoard, fallbackUpdated string) {
	board.Updated = strings.TrimSpace(board.Updated)
	if board.Updated == "" {
		board.Updated = strings.TrimSpace(fallbackUpdated)
	}
	if board.Announcements == nil {
		board.Announcements = []contentAnnouncement{}
	}
	for index := range board.Announcements {
		item := &board.Announcements[index]
		item.ID = strings.TrimSpace(item.ID)
		if item.ID == "" {
			item.ID = "ann-" + randomID()
		}
		item.Title = strings.TrimSpace(item.Title)
		item.Body = strings.TrimSpace(item.Body)
		item.Type = normalizeAnnouncementType(item.Type)
		item.Priority = normalizeAnnouncementPriority(item.Priority)
		item.Audience = strings.TrimSpace(item.Audience)
		item.Action = strings.TrimSpace(item.Action)
		item.PublishedAt = strings.TrimSpace(item.PublishedAt)
		if item.PublishedAt == "" {
			item.PublishedAt = contentDate(board.Updated)
		}
		item.EffectiveAt = strings.TrimSpace(item.EffectiveAt)
		item.ExpiresAt = strings.TrimSpace(item.ExpiresAt)
	}
	board.Community.Name = strings.TrimSpace(board.Community.Name)
	board.Community.QQ = strings.TrimSpace(board.Community.QQ)
	board.Community.Note = strings.TrimSpace(board.Community.Note)
}

func validateContentBoard(board contentBoard) error {
	if len(board.Announcements) > maxContentAnnouncements {
		return fmt.Errorf("公告最多 %d 条", maxContentAnnouncements)
	}
	seenIDs := map[string]bool{}
	for _, item := range board.Announcements {
		if item.ID == "" || len(item.ID) > 100 || seenIDs[item.ID] {
			return errors.New("公告 ID 无效或重复")
		}
		seenIDs[item.ID] = true
		if item.Title == "" {
			return errors.New("公告标题不能为空")
		}
		if len([]rune(item.Title)) > 80 {
			return errors.New("公告标题不能超过 80 字")
		}
		if item.Body == "" {
			return errors.New("公告正文不能为空")
		}
		if len([]rune(item.Body)) > maxAnnouncementBody {
			return fmt.Errorf("公告正文不能超过 %d 字", maxAnnouncementBody)
		}
		if _, ok := contentAnnouncementTypes[item.Type]; !ok {
			return errors.New("公告类型无效")
		}
		if _, ok := contentAnnouncementPriorities[item.Priority]; !ok {
			return errors.New("公告优先级无效")
		}
		if len([]rune(item.Audience)) > maxAnnouncementAudience {
			return fmt.Errorf("公告影响范围不能超过 %d 字", maxAnnouncementAudience)
		}
		if len([]rune(item.Action)) > maxAnnouncementAction {
			return fmt.Errorf("公告操作提示不能超过 %d 字", maxAnnouncementAction)
		}
		if !validContentDate(item.PublishedAt) {
			return errors.New("公告发布日期格式无效")
		}
		if item.EffectiveAt != "" && !validContentDate(item.EffectiveAt) {
			return errors.New("公告生效日期格式无效")
		}
		if item.ExpiresAt != "" && !validContentDate(item.ExpiresAt) {
			return errors.New("公告失效日期格式无效")
		}
		if item.EffectiveAt != "" && item.ExpiresAt != "" && item.ExpiresAt < item.EffectiveAt {
			return errors.New("公告失效日期不能早于生效日期")
		}
	}
	if len([]rune(board.Community.Name)) > 50 || len([]rune(board.Community.Note)) > 200 {
		return errors.New("QQ 群名称或说明过长")
	}
	if board.Community.QQ != "" && !isQQGroupNumber(board.Community.QQ) {
		return errors.New("QQ 群号应为 5 到 15 位数字")
	}
	encoded, err := json.Marshal(board)
	if err != nil {
		return errors.New("信息中心内容编码失败")
	}
	if len(encoded) > maxContentBoardBytes {
		return errors.New("信息中心内容过长，请精简后再保存")
	}
	return nil
}

func publicContentBoard(board contentBoard) contentBoard {
	public := board
	public.Announcements = make([]contentAnnouncement, 0, len(board.Announcements))
	today := time.Now().In(beijing).Format("2006-01-02")
	for _, item := range board.Announcements {
		if item.Enabled && (item.ExpiresAt == "" || item.ExpiresAt >= today) {
			public.Announcements = append(public.Announcements, item)
		}
	}
	sort.SliceStable(public.Announcements, func(i, j int) bool {
		leftPriority := contentAnnouncementPriorityRank(public.Announcements[i].Priority)
		rightPriority := contentAnnouncementPriorityRank(public.Announcements[j].Priority)
		if leftPriority != rightPriority {
			return leftPriority > rightPriority
		}
		if public.Announcements[i].Pinned != public.Announcements[j].Pinned {
			return public.Announcements[i].Pinned
		}
		return public.Announcements[i].PublishedAt > public.Announcements[j].PublishedAt
	})
	if public.Announcements == nil {
		public.Announcements = []contentAnnouncement{}
	}
	return public
}

func (s *Server) contentBoard(w http.ResponseWriter, r *http.Request) {
	board, err := s.loadContentBoard(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取信息中心失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"success": true,
		"board":   publicContentBoard(board),
	})
}

func (s *Server) adminContentBoard(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	board, err := s.loadContentBoard(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "信息中心读取失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "board": board})
}

func (s *Server) adminSaveContentBoard(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	var body struct {
		Board contentBoard `json:"board"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	now := time.Now().In(beijing).Format("2006-01-02 15:04:05")
	body.Board.Updated = now
	normalizeContentBoard(&body.Board, now)
	if err := validateContentBoard(body.Board); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	encoded, err := json.Marshal(body.Board)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "信息中心编码失败")
		return
	}
	legacyText, legacyEnabled := latestLegacyAnnouncement(body.Board)
	if err = s.store.SetSettings(r.Context(), map[string]string{
		contentBoardKey:        string(encoded),
		"announcement_text":    legacyText,
		"announcement_enabled": legacyEnabled,
		"announcement_updated": now,
	}); err != nil {
		writeError(w, http.StatusInternalServerError, "信息中心保存失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"success": true,
		"board":   body.Board,
	})
}

func latestLegacyAnnouncement(board contentBoard) (string, string) {
	public := publicContentBoard(board)
	if len(public.Announcements) == 0 {
		return "", "0"
	}
	return public.Announcements[0].Body, "1"
}

func contentDate(value string) string {
	value = strings.TrimSpace(value)
	prefixLength := min(10, len(value))
	if validContentDate(value[:prefixLength]) {
		return value[:prefixLength]
	}
	return time.Now().In(beijing).Format("2006-01-02")
}

func validContentDate(value string) bool {
	if len(value) != 10 {
		return false
	}
	_, err := time.Parse("2006-01-02", value)
	return err == nil
}

func normalizeAnnouncementType(value string) string {
	value = strings.ToLower(strings.TrimSpace(value))
	if value == "" {
		return "notice"
	}
	return value
}

func normalizeAnnouncementPriority(value string) string {
	value = strings.ToLower(strings.TrimSpace(value))
	if value == "" {
		return "normal"
	}
	return value
}

func contentAnnouncementPriorityRank(value string) int {
	switch value {
	case "urgent":
		return 3
	case "important":
		return 2
	default:
		return 1
	}
}

func isQQGroupNumber(value string) bool {
	if len(value) < 5 || len(value) > 15 {
		return false
	}
	for _, char := range value {
		if char < '0' || char > '9' {
			return false
		}
	}
	return true
}
