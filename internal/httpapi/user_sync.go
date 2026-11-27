package httpapi

import (
	"context"
	"fmt"
	"math/rand"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/resetinging/njust-schedule/internal/jwc"
	"github.com/resetinging/njust-schedule/internal/session"
	"github.com/resetinging/njust-schedule/internal/store"
)

// 用户数据刷新策略（与空教室一致）：
//   - 服务端每天凌晨批量预热用户数据（登录/刷新不再作为常规教务访问路径）；
//   - 服务端缓存未命中时（如首次登录、新用户、换学期）允许一次兜底预抓；
//   - 用户主动刷新默认实时访问教务；后台凌晨预热只负责改善首次打开速度。
const (
	userDataSyncMarker      = "data_cache_at" // 与登录预抓共用同一时间标记
	userDataSyncDefaultHour = 0
	userDataSyncDefaultMin  = 20
	userDataSyncNoLiveMsg   = "数据每日凌晨自动更新，当前为服务器已同步数据"
)

func envBool(name string, fallback bool) bool {
	raw := strings.ToLower(strings.TrimSpace(os.Getenv(name)))
	if raw == "" {
		return fallback
	}
	return raw != "0" && raw != "false" && raw != "off"
}

func envInt(name string, fallback, minValue, maxValue int) int {
	raw := strings.TrimSpace(os.Getenv(name))
	if raw == "" {
		return fallback
	}
	value, err := strconv.Atoi(raw)
	if err != nil {
		return fallback
	}
	if value < minValue || value > maxValue {
		return fallback
	}
	return value
}

// allowLiveRefresh 默认开启：用户主动刷新应实时获取教务数据。
// 仅在运维需要临时止损时显式设置 ALLOW_LIVE_REFRESH=0。
func (s *Server) allowLiveRefresh() bool {
	return envBool("ALLOW_LIVE_REFRESH", true)
}

// writeNoManualRefresh 是刷新接口的默认响应：不访问教务，只告知数据由夜间同步维护。
func writeNoManualRefresh(w http.ResponseWriter) {
	writeJSON(w, http.StatusOK, map[string]any{
		"success": true, "refreshed": false,
		"message": userDataSyncNoLiveMsg,
	})
}

// userDataMarkerFresh 按“最近一次计划同步时刻”判断数据是否仍可直接服务：
// 当前时间未到今日 00:20 时，昨天 00:20 后的同步视为新鲜；已过 00:20 则要求今天
// 00:20 后同步过。这样凌晨登录不会在夜间任务开始前触发不必要的教务回源。
func userDataMarkerFresh(raw string, now time.Time) bool {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return false
	}
	unix, err := strconv.ParseInt(raw, 10, 64)
	if err != nil || unix <= 0 {
		return false
	}
	local := now.In(beijing)
	scheduled := time.Date(local.Year(), local.Month(), local.Day(), userDataSyncDefaultHour, userDataSyncDefaultMin, 0, 0, beijing)
	if local.Before(scheduled) {
		scheduled = scheduled.AddDate(0, 0, -1)
	}
	return !time.Unix(unix, 0).Before(scheduled)
}

func userSessionActive(timestamp int64, now time.Time, lookbackDays int) bool {
	if lookbackDays <= 0 || timestamp <= 0 {
		return true
	}
	return !time.Unix(timestamp, 0).Before(now.AddDate(0, 0, -lookbackDays))
}

// loginDataFresh 判断登录时是否可直接复用服务器快照：学期一致且昨/今计划同步之后已成功同步过。
func loginDataFresh(oldSemester, currentSemester, marker string, now time.Time) bool {
	return strings.TrimSpace(oldSemester) == strings.TrimSpace(currentSemester) && userDataMarkerFresh(marker, now)
}

func (s *Server) userDataFresh(ctx context.Context, sid string) bool {
	raw, err := s.store.UserSetting(ctx, sid, userDataSyncMarker)
	if err != nil {
		return false
	}
	return userDataMarkerFresh(raw, time.Now())
}

// prewarmUserData 每天凌晨批量刷新“有持久会话且近期活跃”的用户数据。
// 与空教室预热一致：启动时先跑一次（已同步用户自动跳过），之后按北京时间每日执行。
func (s *Server) prewarmUserData(ctx context.Context) {
	ids, err := s.auth.PersistentStudentIDs(ctx)
	if err != nil {
		s.logger.Warn("读取用户持久会话列表失败", "error", err)
		return
	}
	concurrency := envInt("USER_DATA_SYNC_CONCURRENCY", 2, 1, 8)
	lookbackDays := envInt("USER_DATA_SYNC_LOOKBACK_DAYS", 30, 0, 365)
	maxUsers := envInt("USER_DATA_SYNC_MAX_USERS", 0, 0, 100000)
	limitReached := func(processed int) bool { return maxUsers > 0 && processed >= maxUsers }

	now := time.Now()
	sem := make(chan struct{}, concurrency)
	var wg sync.WaitGroup
	selected := 0
	skippedFresh := 0
	skippedInactive := 0

	for _, raw := range ids {
		if ctx.Err() != nil || limitReached(selected) {
			break
		}
		sid := strings.TrimSpace(raw)
		if sid == "" {
			continue
		}
		if s.userDataFresh(ctx, sid) {
			skippedFresh++
			continue
		}
		record, ok := s.auth.PersistentSession(ctx, sid)
		if !ok || len(record.Cookies) == 0 {
			skippedInactive++
			continue
		}
		if !userSessionActive(record.Timestamp, now, lookbackDays) {
			skippedInactive++
			continue
		}
		selected++
		wg.Add(1)
		go func(sid string, record store.PersistentSession) {
			defer wg.Done()
			select {
			case sem <- struct{}{}:
				defer func() { <-sem }()
			case <-ctx.Done():
				return
			}
			// 轻微错峰，避免整点集中访问教务。
			jitter := time.Duration(rand.Intn(2000)) * time.Millisecond
			select {
			case <-time.After(jitter):
			case <-ctx.Done():
				return
			}
			s.syncPersistentUserData(ctx, sid, record)
		}(sid, record)
	}
	wg.Wait()
	s.logger.Info("用户数据夜间同步完成",
		"candidates", len(ids), "selected", selected,
		"skipped_fresh", skippedFresh, "skipped_inactive", skippedInactive)
}

func (s *Server) syncPersistentUserData(ctx context.Context, sid string, record store.PersistentSession) {
	if ctx.Err() != nil {
		return
	}
	client := jwc.New(record.Cookies)
	sess := &session.Session{
		StudentID: sid, AccountType: record.AccountType,
		Cookies: record.Cookies, JWC: client,
	}
	semester := currentSemester()
	var ok, failed []string
	if isGraduate(sess) {
		ok, failed = s.prefetchGraduate(ctx, sess)
	} else {
		ok, failed = s.prefetchUndergraduate(ctx, sess, semester)
	}

	// 教务会话可能刷新 Cookie；成功读到新 Cookie 时回写持久会话，供下次批量继续使用。
	if cookies := client.Cookies(); len(cookies) > 0 {
		accountType := client.AccountType
		if strings.TrimSpace(accountType) == "" {
			accountType = record.AccountType
		}
		if err := s.auth.SavePersistentSession(ctx, sid, accountType, cookies); err != nil {
			s.logger.Warn("保存用户持久会话失败", "sid_prefix", maskedSID(sid), "error", err)
		}
	}
	if len(failed) > 0 {
		s.logger.Warn("用户数据夜间同步未完全成功",
			"sid_prefix", maskedSID(sid), "ok", ok, "failed", failed)
		return
	}
	if err := s.store.SetUserSettings(ctx, sid, map[string]string{
		userDataSyncMarker: fmt.Sprint(time.Now().Unix()),
		"semester":         semester,
	}); err != nil {
		s.logger.Warn("写入用户数据同步标记失败", "sid_prefix", maskedSID(sid), "error", err)
		return
	}
	s.cacheDeletePrefix(sid + ":")
}
