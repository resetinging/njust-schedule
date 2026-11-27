package httpapi

import (
	"net/http"
	"os"
	"strings"
)

// allowLiveRefresh 默认开启：用户主动刷新应实时获取教务数据。
// 仅在运维需要临时止损时显式设置 ALLOW_LIVE_REFRESH=0。
func (s *Server) allowLiveRefresh() bool {
	value := strings.ToLower(strings.TrimSpace(os.Getenv("ALLOW_LIVE_REFRESH")))
	return value != "0" && value != "false" && value != "off"
}

// writeNoManualRefresh 用于运维临时关闭实时刷新时的统一响应。
func writeNoManualRefresh(w http.ResponseWriter) {
	writeJSON(w, http.StatusOK, map[string]any{
		"success": true, "refreshed": false,
		"message": "实时刷新已由管理员暂时关闭，请稍后重试",
	})
}
