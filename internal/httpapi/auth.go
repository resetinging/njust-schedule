package httpapi

import (
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/resetinging/njust-schedule/internal/jwc"
	"github.com/resetinging/njust-schedule/internal/session"
)

type loginRequest struct {
	StudentID   string `json:"student_id"`
	Password    string `json:"password"`
	JWCPassword string `json:"jwc_password"`
	Remember    bool   `json:"remember"`
}

const (
	qrSessionTTL  = 3 * time.Minute
	maxQRSessions = 128
)

func loginCredentials(input loginRequest) (string, string, error) {
	sid := strings.TrimSpace(input.StudentID)
	if sid == "" || input.Password == "" {
		return "", "", &httpError{Status: http.StatusBadRequest, Message: "学号和密码不能为空"}
	}
	if !validStudentID(sid) {
		return "", "", &httpError{Status: http.StatusBadRequest, Message: "学号格式无效"}
	}
	if len(input.Password) > 1024 {
		return "", "", &httpError{Status: http.StatusBadRequest, Message: "密码长度无效"}
	}
	return sid, input.Password, nil
}

func (s *Server) legacyCaptcha(w http.ResponseWriter, _ *http.Request) {
	writeError(w, http.StatusBadRequest, "教务直连已下线")
}

func (s *Server) legacyLogin(w http.ResponseWriter, _ *http.Request) {
	writeError(w, http.StatusBadRequest, "教务直连已下线")
}

func (s *Server) legacyManualLogin(w http.ResponseWriter, _ *http.Request) {
	writeError(w, http.StatusBadRequest, "智慧理工直连已无需第二步教务登录，请使用 /api/login-webvpn")
}

func (s *Server) authenticate(ctx context.Context, input loginRequest) (map[string]any, error) {
	sid, password, err := loginCredentials(input)
	if err != nil {
		return nil, err
	}
	client := jwc.New(nil)
	client.SetCaptchaSolver(s.captcha)
	owned := true
	defer func() {
		if owned {
			client.CloseIdleConnections()
		}
	}()
	client.SetTimeout(s.cfg.JWCRequestTimeout)
	loginMethod := "sso"
	credentialSaved := false
	if s.auth.CanResume(ctx, sid, password) {
		if record, ok := s.auth.PersistentSession(ctx, sid); ok {
			client.CloseIdleConnections()
			client = jwc.New(record.Cookies)
			client.SetCaptchaSolver(s.captcha)
			client.SetTimeout(s.cfg.JWCRequestTimeout)
			if err := s.withJWC(ctx, func() error { return client.Resume(ctx, sid) }); err == nil {
				loginMethod = "sso-cached"
				if err := s.auth.MarkCredentialUsed(ctx, sid); err != nil {
					s.logger.Warn("更新登录凭据使用时间失败", "sid_prefix", maskedSID(sid), "error", err)
				}
				credentialSaved = true
			} else {
				client.CloseIdleConnections()
				client = jwc.New(nil)
				client.SetCaptchaSolver(s.captcha)
				client.SetTimeout(s.cfg.JWCRequestTimeout)
			}
		}
	}
	if loginMethod != "sso-cached" {
		if err := s.withJWC(ctx, func() error { return client.Login(ctx, sid, password) }); err != nil {
			return nil, err
		}
		if err := s.auth.SaveCredential(ctx, sid, password); err != nil {
			s.logger.Warn("保存登录凭据失败", "sid_prefix", maskedSID(sid), "error", err)
		} else {
			credentialSaved = true
		}
	}
	client.LoginMethod = loginMethod
	payload, err := s.issueSession(ctx, client, loginMethod != "sso-cached", credentialSaved)
	if err != nil {
		return nil, err
	}
	owned = false
	return payload, nil
}

func (s *Server) issueSession(ctx context.Context, client *jwc.Client, newRemoteSession, credentialSaved bool) (map[string]any, error) {
	sid := strings.TrimSpace(client.StudentID)
	if !validStudentID(sid) {
		return nil, errors.New("登录成功但未识别学号")
	}
	if client.StudentName == "" {
		client.StudentName = sid
	}
	client.StudentName = clipRunes(strings.TrimSpace(client.StudentName), 50)
	cookies := client.Cookies()
	if err := s.auth.SavePersistentSession(ctx, sid, client.AccountType, cookies); err != nil {
		s.logger.Warn("保存教务 Cookie 失败", "sid_prefix", maskedSID(sid), "error", err)
	}
	semester := currentSemester()
	if err := s.store.SetUserSettings(ctx, sid, map[string]string{"semester": semester, "name": client.StudentName}); err != nil {
		return nil, fmt.Errorf("保存登录用户信息: %w", err)
	}
	value := &session.Session{
		StudentID: sid, StudentName: client.StudentName, AccountType: client.AccountType,
		LoginMethod: client.LoginMethod, Cookies: cookies, JWC: client,
		RefreshState: map[string]any{"state": "pending", "started_at": time.Now().Unix(), "updated_at": time.Now().Unix()},
	}
	token, err := s.sessions.Add(ctx, value)
	if err != nil {
		return nil, err
	}
	mode := "full"
	if !newRemoteSession {
		mode = "if_stale"
	}
	s.startPrefetch(value, semester, mode)
	return map[string]any{
		"success": true, "message": "登录成功！欢迎 " + client.StudentName,
		"student_id": sid, "student_name": client.StudentName, "semester": semester,
		"login_method": client.LoginMethod, "account_type": client.AccountType,
		"token": token, "credential_delete_token": s.auth.DeleteToken(sid),
		"credential_saved": credentialSaved,
	}, nil
}

func (s *Server) login(w http.ResponseWriter, r *http.Request) {
	var input loginRequest
	if err := decodeJSON(r, &input); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	sid, _, credentialErr := loginCredentials(input)
	if credentialErr != nil {
		writeError(w, http.StatusBadRequest, credentialErr.Error())
		return
	}
	key := "login:" + sid + ":" + s.clientIP(r)
	sidKey := "login-sid:" + sid
	if s.attemptsExceeded(key, 3, time.Minute) || s.attemptsExceeded(sidKey, 6, 5*time.Minute) {
		writeError(w, http.StatusTooManyRequests, "登录过于频繁，请稍后再试")
		return
	}
	payload, err := s.authenticate(r.Context(), input)
	if err != nil {
		if typed, ok := err.(*httpError); ok {
			s.recordFailedAttempt(key, sidKey)
			writeError(w, typed.Status, typed.Message)
			return
		}
		if errors.Is(err, jwc.ErrCaptchaRequired) {
			// 需要验证码不代表账号或密码错误，不消耗失败额度。
			s.logger.Warn("智慧理工验证码登录回退", "sid_prefix", maskedSID(sid), "error", err)
			writeError(w, http.StatusUnauthorized, jwc.ErrCaptchaRequired.Error())
			return
		}
		s.recordFailedAttempt(key, sidKey)
		s.logger.Info("智慧理工登录失败", "sid_prefix", maskedSID(sid), "error", err)
		writeError(w, http.StatusUnauthorized, "智慧理工登录失败")
		return
	}
	s.clearAttempts(key, sidKey)
	writeJSON(w, http.StatusOK, payload)
}

func (s *Server) loginCompat(w http.ResponseWriter, r *http.Request) {
	var input loginRequest
	if err := decodeJSON(r, &input); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	sid, _, credentialErr := loginCredentials(input)
	if credentialErr != nil {
		writeError(w, http.StatusBadRequest, credentialErr.Error())
		return
	}
	key := "login:" + sid + ":" + s.clientIP(r)
	sidKey := "login-sid:" + sid
	if s.attemptsExceeded(key, 3, time.Minute) || s.attemptsExceeded(sidKey, 6, 5*time.Minute) {
		writeError(w, http.StatusTooManyRequests, "登录过于频繁，请稍后再试")
		return
	}
	payload, err := s.authenticate(r.Context(), input)
	if err != nil {
		if errors.Is(err, jwc.ErrCaptchaRequired) {
			s.logger.Warn("智慧理工兼容登录验证码回退", "sid_prefix", maskedSID(sid), "error", err)
			writeError(w, http.StatusBadRequest, jwc.ErrCaptchaRequired.Error())
			return
		}
		s.recordFailedAttempt(key, sidKey)
		writeError(w, http.StatusBadRequest, "智慧理工登录失败")
		return
	}
	s.clearAttempts(key, sidKey)
	payload["already_logged_in"] = true
	writeJSON(w, http.StatusOK, payload)
}

func (s *Server) qrStart(w http.ResponseWriter, r *http.Request) {
	if s.rateLimited("qr-start:"+s.clientIP(r), 5, time.Minute) {
		writeError(w, http.StatusTooManyRequests, "二维码申请过于频繁，请稍后再试")
		return
	}
	client := jwc.New(nil)
	client.SetTimeout(s.cfg.JWCRequestTimeout)
	qid, ok := s.reserveQR(client)
	if !ok {
		client.CloseIdleConnections()
		writeError(w, http.StatusServiceUnavailable, "二维码登录繁忙，请稍后再试")
		return
	}
	var image []byte
	err := s.withJWC(r.Context(), func() error {
		var err error
		image, err = client.StartQR(r.Context())
		return err
	})
	if err != nil {
		s.removeQR(qid, true)
		mapJWCError(w, err, "申请二维码失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"success": true, "qr_id": qid, "qr_b64": base64.StdEncoding.EncodeToString(image),
		"expires_in": int(qrSessionTTL.Seconds()), "message": "长按二维码 → 识别图中二维码 → 确认登录",
	})
}

func (s *Server) reserveQR(client *jwc.Client) (string, bool) {
	s.qrMu.Lock()
	expired := s.pruneExpiredQRLocked(time.Now())
	if len(s.qrs) >= maxQRSessions {
		s.qrMu.Unlock()
		closeQRSessions(expired)
		return "", false
	}
	qid := randomToken(24)
	s.qrs[qid] = &qrSession{client: client, expiresAt: time.Now().Add(qrSessionTTL)}
	s.qrMu.Unlock()
	closeQRSessions(expired)
	return qid, true
}

func (s *Server) pruneExpiredQRLocked(now time.Time) []*qrSession {
	var expired []*qrSession
	for key, item := range s.qrs {
		if now.After(item.expiresAt) {
			delete(s.qrs, key)
			expired = append(expired, item)
		}
	}
	return expired
}

func closeQRSessions(items []*qrSession) {
	for _, item := range items {
		if item == nil {
			continue
		}
		item.mu.Lock()
		client := item.client
		item.client = nil
		item.mu.Unlock()
		if client != nil {
			client.CloseIdleConnections()
		}
	}
}

func (s *Server) cleanupExpiredQR(now time.Time) {
	s.qrMu.Lock()
	expired := s.pruneExpiredQRLocked(now)
	s.qrMu.Unlock()
	closeQRSessions(expired)
}

func (s *Server) removeQR(qid string, closeClient bool) {
	s.qrMu.Lock()
	item := s.qrs[qid]
	delete(s.qrs, qid)
	s.qrMu.Unlock()
	if item == nil {
		return
	}
	item.mu.Lock()
	client := item.client
	item.client = nil
	item.mu.Unlock()
	if closeClient && client != nil {
		client.CloseIdleConnections()
	}
}

func (s *Server) deleteQR(qid string) {
	s.qrMu.Lock()
	delete(s.qrs, qid)
	s.qrMu.Unlock()
}

func (s *Server) getQR(qid string) (*qrSession, bool) {
	s.qrMu.Lock()
	item := s.qrs[qid]
	if item == nil || time.Now().After(item.expiresAt) {
		delete(s.qrs, qid)
		s.qrMu.Unlock()
		closeQRSessions([]*qrSession{item})
		return nil, false
	}
	s.qrMu.Unlock()
	return item, true
}

func (s *Server) qrImage(w http.ResponseWriter, r *http.Request) {
	item, ok := s.getQR(strings.TrimSpace(r.URL.Query().Get("qr_id")))
	if !ok {
		writeError(w, http.StatusNotFound, "二维码不存在或已过期")
		return
	}
	item.mu.Lock()
	defer item.mu.Unlock()
	if item.client == nil || len(item.client.QRImage()) == 0 {
		writeError(w, http.StatusNotFound, "二维码不存在或已过期")
		return
	}
	w.Header().Set("Content-Type", "image/png")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(item.client.QRImage())
}

func (s *Server) qrStatus(w http.ResponseWriter, r *http.Request) {
	qid := strings.TrimSpace(r.URL.Query().Get("qr_id"))
	item, ok := s.getQR(qid)
	if !ok {
		writeJSON(w, http.StatusBadRequest, map[string]any{"success": false, "status": "expired", "message": "二维码已过期，请刷新"})
		return
	}
	item.mu.Lock()
	defer item.mu.Unlock()
	if item.finished && item.payload != nil {
		writeJSON(w, http.StatusOK, item.payload)
		return
	}
	if item.client == nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"success": false, "status": "expired", "message": "二维码已过期，请刷新"})
		return
	}
	var status string
	err := s.withJWC(r.Context(), func() error {
		var err error
		status, err = item.client.PollQR(r.Context())
		return err
	})
	if err != nil {
		mapJWCError(w, err, "二维码状态查询失败")
		return
	}
	if status == "1" {
		err = s.withJWC(r.Context(), func() error { return item.client.FinishQR(r.Context()) })
		if err != nil {
			s.deleteQR(qid)
			item.client.CloseIdleConnections()
			item.client = nil
			writeJSON(w, http.StatusBadRequest, map[string]any{"success": false, "status": "error", "message": "扫码登录失败"})
			return
		}
		_, credentialSaved := s.auth.Credential(r.Context(), item.client.StudentID)
		payload, err := s.issueSession(r.Context(), item.client, true, credentialSaved)
		if err != nil {
			s.deleteQR(qid)
			item.client.CloseIdleConnections()
			item.client = nil
			writeError(w, http.StatusInternalServerError, "创建登录会话失败")
			return
		}
		payload["status"] = "ok"
		item.finished = true
		item.payload = payload
		item.client = nil
		writeJSON(w, http.StatusOK, payload)
		return
	}
	if status == "3" {
		s.deleteQR(qid)
		item.client.CloseIdleConnections()
		item.client = nil
		writeJSON(w, http.StatusBadRequest, map[string]any{"success": false, "status": "expired", "message": "二维码已失效，请刷新"})
		return
	}
	state := "pending"
	if status == "2" {
		state = "scanned"
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "status": state})
}

func (s *Server) qrCancel(w http.ResponseWriter, r *http.Request) {
	var body struct {
		QRID string `json:"qr_id"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	s.removeQR(strings.TrimSpace(body.QRID), true)
	writeJSON(w, http.StatusOK, map[string]any{"success": true})
}

func (s *Server) logout(w http.ResponseWriter, r *http.Request) {
	token := strings.TrimSpace(r.Header.Get(tokenHeader))
	sess, ok := s.sessions.Get(r.Context(), token)
	if err := s.sessions.Delete(r.Context(), token); err != nil {
		s.logger.Error("退出登录时删除会话失败", "error", err)
		writeError(w, http.StatusServiceUnavailable, "退出登录失败，请稍后重试")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"success": true, "message": "已退出登录", "credential_deleted": false,
		"credential_retained": ok && sess.StudentID != "",
	})
}

func (s *Server) deleteCredential(w http.ResponseWriter, r *http.Request) {
	sid := s.auth.VerifyDeleteToken(strings.TrimSpace(r.Header.Get("X-Credential-Delete-Token")))
	if sid == "" {
		if sess, ok := s.session(r); ok {
			sid = sess.StudentID
		}
	}
	if sid == "" {
		writeError(w, http.StatusUnauthorized, "登录凭证已失效，请重新登录后再关闭")
		return
	}
	if err := s.auth.DropCredential(r.Context(), sid); err != nil {
		writeError(w, http.StatusInternalServerError, "删除保存的密码失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "message": "已删除服务端保存的密码"})
}

type httpError struct {
	Status  int
	Message string
}

func (e *httpError) Error() string { return e.Message }
