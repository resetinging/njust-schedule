package httpapi

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
)

func TestAllowLiveRefreshDefaultsToEnabled(t *testing.T) {
	t.Setenv("ALLOW_LIVE_REFRESH", "")
	server := &Server{}
	if !server.allowLiveRefresh() {
		t.Fatal("默认必须允许用户主动刷新访问教务")
	}
	t.Setenv("ALLOW_LIVE_REFRESH", "0")
	if server.allowLiveRefresh() {
		t.Fatal("显式 ALLOW_LIVE_REFRESH=0 应允许运维临时关闭实时刷新")
	}
}

func TestRefreshEndpointsReturnMaintenanceNoticeWhenDisabled(t *testing.T) {
	t.Setenv("ALLOW_LIVE_REFRESH", "0")
	server := &Server{cache: map[string]cacheEntry{}}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/api/refresh-all", nil)
	server.refreshAll(recorder, request)
	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	var payload struct {
		Success   bool   `json:"success"`
		Refreshed bool   `json:"refreshed"`
		Message   string `json:"message"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if !payload.Success || payload.Refreshed {
		t.Fatalf("刷新响应错误: %+v", payload)
	}
	if !strings.Contains(payload.Message, "暂时关闭") {
		t.Fatalf("提示文案不正确: %q", payload.Message)
	}
}

func TestNoAutomaticUserDataPrefetch(t *testing.T) {
	jobs, err := os.ReadFile("jobs.go")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(jobs), "user-data-daily-sync") {
		t.Fatal("用户数据夜间批量同步任务必须移除")
	}
	auth, err := os.ReadFile("auth.go")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(auth), "startPrefetch(") {
		t.Fatal("登录流程不得自动触发全量教务预抓")
	}
}
