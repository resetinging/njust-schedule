package httpapi

import (
	"context"
	"crypto/hmac"
	"errors"
	"net/http"
	"strings"
	"time"

	"github.com/resetinging/njust-schedule/internal/session"
)

const partnerPreviewSubjectID = "partner-preview"

func (s *Server) isPartnerUsername(username string) bool {
	return s.cfg.PartnerPreviewEnabled &&
		strings.TrimSpace(username) != "" &&
		strings.TrimSpace(username) == s.cfg.PartnerPreviewUser
}

func (s *Server) loginPartnerPreview(
	ctx context.Context,
	input loginRequest,
	clientIP string,
) (map[string]any, bool, error) {
	username := strings.TrimSpace(input.StudentID)
	if !s.isPartnerUsername(username) {
		return nil, false, nil
	}
	key := "partner-login:" + clientIP
	if s.attemptsExceeded(key, 5, time.Minute) {
		return nil, true, &httpError{Status: http.StatusTooManyRequests, Message: "验收账号登录过于频繁，请稍后再试"}
	}
	if !hmac.Equal([]byte(input.Password), []byte(s.cfg.PartnerPreviewPassword)) {
		s.recordFailedAttempt(key)
		return nil, true, &httpError{Status: http.StatusUnauthorized, Message: "验收账号或密码错误"}
	}
	s.clearAttempts(key)
	value := &session.Session{
		StudentID:   partnerPreviewSubjectID,
		StudentName: clipRunes(strings.TrimSpace(s.cfg.PartnerPreviewName), 50),
		AccountType: "partner",
		LoginMethod: "partner-preview",
		Role:        "partner",
	}
	token, err := s.sessions.Add(ctx, value)
	if err != nil {
		return nil, true, err
	}
	if value.StudentName == "" {
		value.StudentName = "合作商验收"
	}
	s.logger.Info("合作商验收账号登录成功", "account", username)
	return map[string]any{
		"success": true, "message": "验收账号登录成功",
		"student_id": value.StudentID, "student_name": value.StudentName,
		"semester": currentSemester(), "login_method": value.LoginMethod,
		"account_type": "partner", "role": "partner", "partner_mode": true,
		"capabilities": map[string]bool{
			"courses": true, "exams": true, "evaluation": true, "grades": true,
			"credit": true, "freeclass": true, "gallery": true, "audit": true,
			"library": true, "services": true, "notice": true, "feedback": true,
		},
		"token": token, "credential_saved": false,
	}, true, nil
}

// loginPartnerPreviewRequest is shared by the normal and compatibility login
// handlers. The user-facing page stays identical; only the backend principal differs.
func (s *Server) loginPartnerPreviewRequest(
	ctx context.Context,
	input loginRequest,
	clientIP string,
) (map[string]any, bool, error) {
	if !s.cfg.PartnerPreviewEnabled {
		return nil, false, nil
	}
	payload, handled, err := s.loginPartnerPreview(ctx, input, clientIP)
	if err != nil {
		var typed *httpError
		if errors.As(err, &typed) {
			return nil, true, typed
		}
		s.logger.Warn("合作商验收账号登录失败", "error", err)
		return nil, true, &httpError{Status: http.StatusInternalServerError, Message: "验收账号登录失败"}
	}
	return payload, handled, nil
}
