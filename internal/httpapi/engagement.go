package httpapi

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/resetinging/njust-schedule/internal/store"
)

var subscriptionKinds = map[string]bool{"exam": true, "grade": true}

const wechatResponseLimit = 1 << 20

var wechatHTTPClient = &http.Client{Timeout: 10 * time.Second}

func decodeWechatResponse(reader io.Reader, target any) error {
	raw, err := io.ReadAll(io.LimitReader(reader, wechatResponseLimit+1))
	if err != nil {
		return err
	}
	if len(raw) > wechatResponseLimit {
		return fmt.Errorf("微信响应超过 %d 字节", wechatResponseLimit)
	}
	if err = json.Unmarshal(raw, target); err != nil {
		return err
	}
	return nil
}

func callerOpenID(r *http.Request) string {
	value := strings.TrimSpace(r.Header.Get("X-WX-OPENID"))
	if value == "" || len(value) > 64 {
		return ""
	}
	for _, char := range value {
		if !(char >= 'A' && char <= 'Z' || char >= 'a' && char <= 'z' || char >= '0' && char <= '9' || char == '_' || char == '-') {
			return ""
		}
	}
	return value
}

func (s *Server) subscribeStatus(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	if openid := callerOpenID(r); openid != "" {
		if err := s.store.SetUserSetting(r.Context(), sess.StudentID, "openid", openid); err != nil {
			writeError(w, http.StatusInternalServerError, "保存微信身份失败")
			return
		}
	}
	values, err := s.store.SubscriptionStatus(r.Context(), sess.StudentID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取订阅状态失败")
		return
	}
	openid, err := s.store.UserSetting(r.Context(), sess.StudentID, "openid")
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取微信身份失败")
		return
	}
	kinds := map[string]any{}
	for _, kind := range []string{"exam", "grade"} {
		tpl := s.cfg.SubscribeExam
		if kind == "grade" {
			tpl = s.cfg.SubscribeGrade
		}
		kinds[kind] = map[string]any{"template_id": tpl, "enabled": tpl != "", "quota": values[kind].Count}
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "kinds": kinds, "openid_bound": openid != "", "send_enabled": s.cfg.MPAppID != "" && s.cfg.MPSecret != ""})
}

func (s *Server) subscribeGrant(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	var body struct {
		Kind string `json:"kind"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	kind := strings.TrimSpace(body.Kind)
	if !subscriptionKinds[kind] {
		writeError(w, http.StatusBadRequest, "未知的提醒类型")
		return
	}
	quota, err := s.store.GrantSubscription(r.Context(), sess.StudentID, kind, callerOpenID(r))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "保存订阅额度失败")
		return
	}
	semester := s.semesterFor(r, sess)
	if err := s.syncUserReminderTasks(r.Context(), sess.StudentID, semester); err != nil {
		s.logger.Warn("订阅后同步提醒任务失败", "sid_prefix", maskedSID(sess.StudentID), "kind", kind, "error", err)
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "kind": kind, "quota": quota})
}

func (s *Server) wechatAccessToken(ctx context.Context) (string, error) {
	if s.cfg.MPAppID == "" || s.cfg.MPSecret == "" {
		return "", fmt.Errorf("未配置 MP_APPID 或 MP_SECRET")
	}
	key := "wechat-access-token"
	if value, ok := s.cacheGet(key); ok {
		if token, valid := value.(string); valid && token != "" {
			return token, nil
		}
	}
	endpoint := "https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid=" + url.QueryEscape(s.cfg.MPAppID) + "&secret=" + url.QueryEscape(s.cfg.MPSecret)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return "", err
	}
	resp, err := wechatHTTPClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	var body struct {
		AccessToken string `json:"access_token"`
		ExpiresIn   int    `json:"expires_in"`
		ErrCode     int    `json:"errcode"`
		ErrMsg      string `json:"errmsg"`
	}
	if err = decodeWechatResponse(resp.Body, &body); err != nil {
		return "", err
	}
	if body.AccessToken == "" {
		return "", fmt.Errorf("微信 access_token 获取失败: %d %s", body.ErrCode, body.ErrMsg)
	}
	ttl := time.Duration(max(300, body.ExpiresIn-300)) * time.Second
	s.cacheSet(key, body.AccessToken, ttl)
	return body.AccessToken, nil
}

func (s *Server) sendSubscribe(ctx context.Context, openid, templateID string, data map[string]any) map[string]any {
	return s.sendSubscribePage(ctx, openid, templateID, "pages/main/main", data)
}

func (s *Server) sendSubscribePage(ctx context.Context, openid, templateID, page string, data map[string]any) map[string]any {
	token, err := s.wechatAccessToken(ctx)
	if err != nil {
		return map[string]any{"ok": false, "errcode": -1, "errmsg": err.Error()}
	}
	raw, err := json.Marshal(map[string]any{"touser": openid, "template_id": templateID, "page": page, "miniprogram_state": "formal", "data": data})
	if err != nil {
		return map[string]any{"ok": false, "errcode": -1, "errmsg": "订阅消息编码失败: " + err.Error()}
	}
	endpoint := "https://api.weixin.qq.com/cgi-bin/message/subscribe/send?access_token=" + url.QueryEscape(token)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(raw))
	if err != nil {
		return map[string]any{"ok": false, "errcode": -1, "errmsg": err.Error()}
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := wechatHTTPClient.Do(req)
	if err != nil {
		return map[string]any{"ok": false, "errcode": -1, "errmsg": err.Error()}
	}
	defer resp.Body.Close()
	var result map[string]any
	if decodeWechatResponse(resp.Body, &result) != nil {
		return map[string]any{"ok": false, "errcode": -1, "errmsg": "微信返回格式错误"}
	}
	rawCode, exists := result["errcode"]
	code, valid := rawCode.(float64)
	result["ok"] = exists && valid && int(code) == 0
	return result
}

func (s *Server) subscribeTestSend(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	var body struct {
		Kind string `json:"kind"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	kind := strings.TrimSpace(body.Kind)
	if kind == "" {
		kind = strings.TrimSpace(r.URL.Query().Get("kind"))
	}
	if kind == "" {
		kind = "exam"
	}
	if !subscriptionKinds[kind] {
		writeError(w, http.StatusBadRequest, "未知的提醒类型")
		return
	}
	template := s.cfg.SubscribeExam
	if kind == "grade" {
		template = s.cfg.SubscribeGrade
	}
	if template == "" || s.cfg.MPSecret == "" {
		writeError(w, http.StatusBadRequest, "订阅消息未配置(缺模板 ID 或 MP_SECRET)")
		return
	}
	openid := callerOpenID(r)
	if openid == "" {
		var err error
		openid, err = s.store.UserSetting(r.Context(), sess.StudentID, "openid")
		if err != nil {
			writeError(w, http.StatusInternalServerError, "读取微信身份失败")
			return
		}
	}
	if openid == "" {
		writeError(w, http.StatusBadRequest, "未获取到 openid(需在小程序内触发)")
		return
	}
	now := time.Now().In(beijing).Format("2006-01-02 15:04")
	data := map[string]any{
		"thing1": map[string]string{"value": map[string]string{"exam": "考试提醒", "grade": "成绩发布"}[kind]},
		"thing2": map[string]string{"value": "样例课程"}, "time3": map[string]string{"value": now},
		"thing4": map[string]string{"value": "Ⅰ-301"}, "thing5": map[string]string{"value": "这是一条样例提醒"},
	}
	reserved, err := s.store.ReserveSubscription(r.Context(), sess.StudentID, kind)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "预留订阅额度失败")
		return
	}
	if !reserved {
		writeError(w, http.StatusBadRequest, "没有可用订阅额度，请先授权")
		return
	}
	result := s.sendSubscribe(r.Context(), openid, template, data)
	if result["ok"] != true {
		if err := s.store.RefundSubscription(r.Context(), sess.StudentID, kind); err != nil {
			s.logger.Error("测试消息发送失败且订阅额度退回失败", "sid_prefix", maskedSID(sess.StudentID), "kind", kind, "error", err)
			writeError(w, http.StatusInternalServerError, "测试消息发送失败，订阅额度退回异常")
			return
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": result["ok"] == true, "result": result})
}

var usageEventNames = setOf("app_open", "app_background", "session_start", "session_end", "page_view", "page_leave", "feature_open", "feature_action", "refresh_success", "refresh_fail", "login_success", "reminder_grant", "audit_favorite", "feedback_submit", "slot_view", "slot_visible", "slot_leave", "ad_request", "ad_loaded", "ad_failed", "ad_impression", "ad_click", "ad_close", "ad_reward_complete")
var usagePages = setOf("", "main", "schedule", "feature", "exams", "eval", "grades", "credit", "freeclass", "gallery", "audit", "notice", "profile", "login")
var usageFeatures = setOf("", "schedule", "exams", "eval", "grades", "credit", "freeclass", "gallery", "audit", "notice", "subscription", "feedback", "settings", "profile", "login")
var usageAdTypes = setOf("", "native", "banner", "interstitial", "rewarded")
var usagePlatforms = setOf("", "ios", "android", "devtools", "other")
var usagePropertyKeys = setOf("duration_s", "visible_ms", "result", "kind", "has_data", "items", "tab", "source")

func setOf(values ...string) map[string]bool {
	result := make(map[string]bool, len(values))
	for _, value := range values {
		result[value] = true
	}
	return result
}

func (s *Server) analyticsHash(prefix, value string) string {
	encodedKey := base64.StdEncoding.EncodeToString(s.cfg.SessionKey)
	secret := sha256.Sum256([]byte(encodedKey))
	mac := hmac.New(sha256.New, secret[:])
	_, _ = mac.Write([]byte(prefix + "|" + value))
	return hex.EncodeToString(mac.Sum(nil))
}

func safeAnalyticsID(value string) bool {
	if value == "" || len(value) > 64 {
		return false
	}
	for _, char := range value {
		if !(char >= 'A' && char <= 'Z' || char >= 'a' && char <= 'z' || char >= '0' && char <= '9' || strings.ContainsRune("_.:-", char)) {
			return false
		}
	}
	return true
}

func analyticsString(value any, limit int) string {
	if value == nil {
		return ""
	}
	return clipRunes(strings.TrimSpace(fmt.Sprint(value)), limit)
}

func normalizeAnalyticsProperties(value any) map[string]any {
	raw, ok := value.(map[string]any)
	if !ok {
		return map[string]any{}
	}
	out := map[string]any{}
	for key, value := range raw {
		if !usagePropertyKeys[key] || value == nil {
			continue
		}
		switch typed := value.(type) {
		case bool:
			out[key] = typed
		case float64:
			out[key] = max(-86400.0, min(86400.0, typed))
		case json.Number:
			if number, err := typed.Float64(); err == nil {
				out[key] = max(-86400.0, min(86400.0, number))
			}
		default:
			out[key] = analyticsString(typed, 120)
		}
	}
	return out
}

func parseAnalyticsTime(value any, now time.Time) *time.Time {
	if value == nil || strings.TrimSpace(fmt.Sprint(value)) == "" {
		return nil
	}
	var parsed time.Time
	switch typed := value.(type) {
	case float64:
		seconds := typed
		if seconds > 100_000_000_000 {
			seconds /= 1000
		}
		parsed = time.Unix(int64(seconds), int64((seconds-float64(int64(seconds)))*float64(time.Second))).In(beijing)
	case json.Number:
		number, err := typed.Float64()
		if err != nil {
			return nil
		}
		return parseAnalyticsTime(number, now)
	default:
		text := strings.TrimSpace(fmt.Sprint(value))
		var err error
		for _, layout := range []string{time.RFC3339Nano, "2006-01-02 15:04:05", "2006-01-02T15:04:05"} {
			if strings.Contains(layout, "Z07") {
				parsed, err = time.Parse(layout, text)
			} else {
				parsed, err = time.ParseInLocation(layout, text, beijing)
			}
			if err == nil {
				break
			}
		}
		if err != nil {
			return nil
		}
		parsed = parsed.In(beijing)
	}
	if parsed.After(now.Add(10*time.Minute)) || parsed.Before(now.AddDate(0, 0, -30)) {
		return nil
	}
	return &parsed
}

func (s *Server) analyticsEvents(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Consent   bool             `json:"consent"`
		VisitorID string           `json:"visitor_id"`
		Events    []map[string]any `json:"events"`
	}
	if err := decodeJSON(r, &body); err != nil || !body.Consent {
		writeError(w, http.StatusBadRequest, "consent required")
		return
	}
	if len(body.Events) > 20 {
		writeError(w, http.StatusBadRequest, "too many events")
		return
	}
	identity := ""
	if sess, ok := s.session(r); ok {
		identity = s.analyticsHash("sid", sess.StudentID)
	}
	visitorHash := ""
	if safeAnalyticsID(strings.TrimSpace(body.VisitorID)) {
		visitorHash = s.analyticsHash("visitor", strings.TrimSpace(body.VisitorID))
	}
	if identity == "" {
		identity = visitorHash
	}
	if identity == "" {
		writeError(w, http.StatusBadRequest, "missing identity")
		return
	}
	rateKey := identity
	if s.rateLimited("usage:"+rateKey, 300, time.Minute) {
		writeError(w, http.StatusTooManyRequests, "上报过于频繁")
		return
	}
	values := make([]store.UsageEvent, 0, len(body.Events))
	rejected := 0
	now := time.Now().In(beijing)
	for _, raw := range body.Events {
		id := analyticsString(raw["id"], 64)
		name := analyticsString(raw["name"], 64)
		sessionID := analyticsString(raw["session_id"], 64)
		page := analyticsString(raw["page"], 64)
		feature := analyticsString(raw["feature"], 64)
		slotID := analyticsString(raw["slot_id"], 64)
		adType := analyticsString(raw["ad_type"], 64)
		platform := analyticsString(raw["platform"], 64)
		if !safeAnalyticsID(id) || !safeAnalyticsID(sessionID) || !usageEventNames[name] || !usagePages[page] || !usageFeatures[feature] || !usageAdTypes[adType] || !usagePlatforms[platform] || (slotID != "" && !safeAnalyticsID(slotID)) {
			rejected++
			continue
		}
		propertiesValue := normalizeAnalyticsProperties(raw["properties"])
		properties, err := json.Marshal(propertiesValue)
		if err != nil {
			rejected++
			continue
		}
		visible := 0
		visibleValue := raw["visible_ms"]
		if value, ok := propertiesValue["visible_ms"]; ok {
			visibleValue = value
		}
		visible = max(0, min(3_600_000, number(visibleValue)))
		keyMaterial := strings.Join([]string{identity, sessionID, id, name}, "|")
		sum := sha256.Sum256([]byte(keyMaterial))
		values = append(values, store.UsageEvent{EventKey: hex.EncodeToString(sum[:]), AnalyticsID: identity, VisitorHash: visitorHash, SessionID: sessionID, Name: name, Page: page, Feature: feature, SlotID: slotID, AdType: adType, VisibleMS: visible, Properties: string(properties), AppVersion: analyticsString(raw["app_version"], 40), Platform: platform, ClientTS: parseAnalyticsTime(raw["ts"], now)})
	}
	s.analyticsMu.Lock()
	accepted, duplicates, err := s.store.RecordUsageEvents(r.Context(), now.Format("2006-01-02"), values)
	s.analyticsMu.Unlock()
	if err != nil {
		s.logger.Error("写入使用统计失败", "error", err)
		writeError(w, http.StatusInternalServerError, "统计写入失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "accepted": accepted, "duplicates": duplicates, "rejected": rejected})
}

func number(value any) int {
	switch raw := value.(type) {
	case float64:
		return int(raw)
	case string:
		value, _ := strconv.Atoi(raw)
		return value
	default:
		return 0
	}
}
