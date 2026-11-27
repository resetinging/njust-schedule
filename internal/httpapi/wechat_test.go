package httpapi

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"

	"github.com/resetinging/njust-schedule/internal/config"
)

func TestSendSubscribeDefaultsToCloudRun(t *testing.T) {
	oldBase, oldClient := wechatCloudBaseURL, wechatCloudClient
	t.Cleanup(func() {
		wechatCloudBaseURL = oldBase
		wechatCloudClient = oldClient
	})

	var gotPath, gotQuery string
	var gotBody map[string]any
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		gotQuery = r.URL.RawQuery
		raw, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(raw, &gotBody)
		w.Header().Set("x-openapi-seqid", "seq-cloud-1")
		_, _ = w.Write([]byte(`{"errcode":0,"errmsg":"ok"}`))
	}))
	defer upstream.Close()
	wechatCloudBaseURL = upstream.URL
	wechatCloudClient = upstream.Client()

	server := &Server{cfg: config.Config{}}
	result := server.sendSubscribePage(t.Context(), "openid", "template", "pages/main/main?feature=exams", map[string]any{
		"thing1": map[string]string{"value": "考试提醒"},
	})

	if result["ok"] != true {
		t.Fatalf("unexpected result: %#v", result)
	}
	if gotPath != wechatSubscribeSendPath || gotQuery != "" {
		t.Fatalf("path=%q query=%q", gotPath, gotQuery)
	}
	if gotBody["lang"] != "zh_CN" || gotBody["miniprogram_state"] != "formal" {
		t.Fatalf("unexpected body: %#v", gotBody)
	}
	if _, exists := gotBody["access_token"]; exists {
		t.Fatalf("cloudrun body must not contain access_token: %#v", gotBody)
	}
}

func TestSendSubscribeCloudRunRequiresOpenAPISequenceHeader(t *testing.T) {
	oldBase, oldClient := wechatCloudBaseURL, wechatCloudClient
	t.Cleanup(func() {
		wechatCloudBaseURL = oldBase
		wechatCloudClient = oldClient
	})

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"errcode":0,"errmsg":"ok"}`))
	}))
	defer upstream.Close()
	wechatCloudBaseURL = upstream.URL
	wechatCloudClient = upstream.Client()

	server := &Server{cfg: config.Config{}}
	result := server.sendSubscribePage(t.Context(), "openid", "template", "pages/main/main", map[string]any{})
	if result["ok"] != false || !strings.Contains(result["errmsg"].(string), "x-openapi-seqid") {
		t.Fatalf("unexpected result: %#v", result)
	}
}

func TestSendSubscribePublicModeUsesCachedAccessToken(t *testing.T) {
	oldBase, oldClient := wechatPublicBaseURL, wechatHTTPClient
	t.Cleanup(func() {
		wechatPublicBaseURL = oldBase
		wechatHTTPClient = oldClient
	})

	var gotToken string
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotToken = r.URL.Query().Get("access_token")
		_, _ = w.Write([]byte(`{"errcode":0,"errmsg":"ok"}`))
	}))
	defer upstream.Close()
	wechatPublicBaseURL = upstream.URL
	wechatHTTPClient = upstream.Client()

	server := &Server{
		cfg: config.Config{
			WechatOpenAPIMode: "public",
			MPAppID:           "appid",
			MPSecret:          "secret",
		},
		cache: map[string]cacheEntry{
			"wechat-access-token": {value: "cached-token", expiresAt: time.Now().Add(time.Hour)},
		},
	}
	result := server.sendSubscribePage(t.Context(), "openid", "template", "pages/main/main", map[string]any{})
	if result["ok"] != true || gotToken != "cached-token" {
		t.Fatalf("result=%#v token=%q", result, gotToken)
	}
}

func TestSanitizeWechatErrorRemovesRequestURL(t *testing.T) {
	err := &url.Error{
		Op:  "Get",
		URL: "https://api.weixin.qq.com/cgi-bin/token?secret=should-not-leak",
		Err: io.ErrUnexpectedEOF,
	}
	got := sanitizeWechatError(err).Error()
	if strings.Contains(got, "secret") || strings.Contains(got, "https://") {
		t.Fatalf("sanitized error leaked URL: %s", got)
	}
}

func TestWechatSendEnabledInCloudRunWithoutSecret(t *testing.T) {
	server := &Server{cfg: config.Config{}}
	if !server.wechatSendEnabled() {
		t.Fatal("cloudrun mode should not require MP_SECRET")
	}
	server.cfg.WechatOpenAPIMode = "public"
	if server.wechatSendEnabled() {
		t.Fatal("public mode must require MP_SECRET")
	}
}

func TestReminderLoopEnabledInCloudRunWithoutSecret(t *testing.T) {
	t.Setenv("EXAM_REMINDER", "1")
	server := &Server{cfg: config.Config{}}
	if !server.remindersEnabled() {
		t.Fatal("reminder loop should start in cloudrun mode without MP_SECRET")
	}
	server.cfg.WechatOpenAPIMode = "public"
	if server.remindersEnabled() {
		t.Fatal("reminder loop must require credentials in public mode")
	}
}

func TestTemplateFieldsIncludeDynamicThing8(t *testing.T) {
	oldBase, oldClient := wechatCloudBaseURL, wechatCloudClient
	t.Cleanup(func() {
		wechatCloudBaseURL = oldBase
		wechatCloudClient = oldClient
	})

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != wechatTemplateListPath {
			t.Fatalf("path = %q", r.URL.Path)
		}
		w.Header().Set("x-openapi-seqid", "seq-template-1")
		_, _ = w.Write([]byte(`{"errcode":0,"errmsg":"ok","data":[{"priTmplId":"tpl-1","content":[{"key":"thing1","name":"日程主题"},{"key":"thing8","name":"课程名称"},{"key":"time3","name":"时间"}]}]}`))
	}))
	defer upstream.Close()
	wechatCloudBaseURL = upstream.URL
	wechatCloudClient = upstream.Client()

	server := &Server{cfg: config.Config{}, cache: map[string]cacheEntry{}}
	fields := server.templateFields(t.Context(), "exam", "tpl-1")
	data := buildWechatTemplateData(fields, wechatTemplateValues{
		Topic: "考试提醒", Course: "信号与系统分析",
		Date: "2026-11-28", Time: "09:00", Detail: "座位12号",
	})
	value, ok := data["thing8"].(map[string]string)
	if !ok || value["value"] != "信号与系统分析" {
		t.Fatalf("thing8 = %#v, fields=%#v", data["thing8"], fields)
	}
}

func TestFallbackTemplateFieldsCanIncludeThing8(t *testing.T) {
	t.Setenv("SUBSCRIBE_TPL_EXAM_FIELDS", "thing1,thing8")
	fields := fallbackTemplateFields("exam")
	if len(fields) != 2 || fields[1].Key != "thing8" {
		t.Fatalf("unexpected fallback fields: %#v", fields)
	}
	data := buildWechatTemplateData(fields, wechatTemplateValues{
		Topic: "考试提醒", Course: "信号与系统分析", Detail: "座位12号",
	})
	value, ok := data["thing8"].(map[string]string)
	if !ok || strings.TrimSpace(value["value"]) == "" {
		t.Fatalf("thing8 must not be empty: %#v", data)
	}
}
