package httpapi

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestAllowLiveRefreshDefaultsToDisabled(t *testing.T) {
	t.Setenv("ALLOW_LIVE_REFRESH", "0")
	server := &Server{}
	if server.allowLiveRefresh() {
		t.Fatal("默认必须关闭手动刷新")
	}
	t.Setenv("ALLOW_LIVE_REFRESH", "1")
	if !server.allowLiveRefresh() {
		t.Fatal("显式 ALLOW_LIVE_REFRESH=1 才允许回源")
	}
}

// 默认关闭时，刷新接口即使未登录也不能访问教务，只返回夜间同步提示。
func TestRefreshEndpointsReturnNightlyNoticeByDefault(t *testing.T) {
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
		t.Fatalf("默认刷新响应错误: %+v", payload)
	}
	if !strings.Contains(payload.Message, "每日凌晨") {
		t.Fatalf("提示文案不正确: %q", payload.Message)
	}
}

func TestUserDataMarkerFresh(t *testing.T) {
	// 北京时间 2026-11-01 12:00 → 当天 00:20 后的标记才算新鲜。
	now := time.Date(2026, 11, 1, 4, 0, 0, 0, time.UTC) // 12:00 Asia/Shanghai
	dayStart := time.Date(2026, 11, 1, 0, 20, 0, 0, beijing)
	cases := []struct {
		name string
		raw  string
		want bool
	}{
		{name: "空标记", raw: "", want: false},
		{name: "非法标记", raw: "abc", want: false},
		{name: "零值", raw: "0", want: false},
		{name: "今日计划同步后", raw: itoa(dayStart.Add(10 * time.Minute).Unix()), want: true},
		{name: "昨日计划同步", raw: itoa(dayStart.AddDate(0, 0, -1).Unix()), want: false},
		{name: "未来时间视为新鲜", raw: itoa(now.Add(time.Hour).Unix()), want: true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := userDataMarkerFresh(tc.raw, now); got != tc.want {
				t.Fatalf("userDataMarkerFresh(%q) = %v, want %v", tc.raw, got, tc.want)
			}
		})
	}
	// 凌晨 00:10（计划同步开始前）：昨日 00:20 后的标记仍应视为新鲜。
	early := time.Date(2026, 11, 1, 0, 10, 0, 0, beijing)
	if !userDataMarkerFresh(itoa(dayStart.AddDate(0, 0, -1).Add(time.Hour).Unix()), early) {
		t.Fatal("00:20 前的凌晨窗口应复用昨日数据")
	}
}

func TestLoginDataFreshRequiresSameSemester(t *testing.T) {
	now := time.Date(2026, 11, 1, 4, 0, 0, 0, time.UTC) // 北京时间 12:00
	marker := itoa(time.Date(2026, 11, 1, 0, 30, 0, 0, beijing).Unix())
	if !loginDataFresh("2026-2027-1", "2026-2027-1", marker, now) {
		t.Fatal("同学校且今日已同步应直接复用快照")
	}
	if loginDataFresh("2026-2026-2", "2026-2027-1", marker, now) {
		t.Fatal("学期变化必须触发兜底预抓")
	}
	if loginDataFresh("", "2026-2027-1", marker, now) {
		t.Fatal("首次登录(旧学期为空)必须触发兜底预抓")
	}
}

func TestUserSessionActiveLookback(t *testing.T) {
	now := time.Date(2026, 11, 1, 12, 0, 0, 0, time.UTC)
	if !userSessionActive(0, now, 30) {
		t.Fatal("无时间戳的持久会话视为活跃")
	}
	if !userSessionActive(now.AddDate(0, 0, -29).Unix(), now, 30) {
		t.Fatal("30 天内活跃用户应参与同步")
	}
	if userSessionActive(now.AddDate(0, 0, -31).Unix(), now, 30) {
		t.Fatal("超过 30 天未活跃用户不应参与同步")
	}
	if !userSessionActive(now.AddDate(0, 0, -999).Unix(), now, 0) {
		t.Fatal("lookback=0 表示不限制活跃时间")
	}
}

func itoa(value int64) string {
	return strconv.FormatInt(value, 10)
}
