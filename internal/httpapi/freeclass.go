package httpapi

import (
	"context"
	"errors"
	"fmt"
	"math/rand"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/resetinging/njust-schedule/internal/jwc"
	"github.com/resetinging/njust-schedule/internal/session"
)

var freeClassroomSlots = map[string][2]int{
	"1-3": {1, 3}, "4-5": {4, 5}, "6-7": {6, 7}, "8-10": {8, 10}, "11-13": {11, 13},
}

var weekdayNames = []string{"", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"}

func teachingWeek(firstMonday string, now time.Time) int {
	date, err := time.ParseInLocation("2006-01-02", strings.TrimSpace(firstMonday), beijing)
	if err != nil {
		return 1
	}
	week := int(now.In(beijing).Sub(date).Hours()/24)/7 + 1
	if week < 1 || week > 25 {
		return 1
	}
	return week
}

func freeClassCacheKey(campus string, weekday, jc1, jc2, week int, semester, building string) string {
	return fmt.Sprintf("freeclass:%s:%d:%d:%d:%d:%s:%s", campus, weekday, jc1, jc2, week, semester, building)
}

func untilTomorrow() time.Duration {
	now := time.Now().In(beijing)
	tomorrow := time.Date(now.Year(), now.Month(), now.Day()+1, 0, 2, 0, 0, beijing)
	return max(2*time.Minute, time.Until(tomorrow))
}

func freeClassResponse(campus string, weekday, jc1, jc2, week int, semester string, result jwc.FreeClassroomResult) map[string]any {
	timeText := fmt.Sprintf("第%d-%d节", jc1, jc2)
	return map[string]any{
		"success": true, "campus": campus, "weekday": weekday, "week": week, "semester": semester,
		"jc1": jc1, "jc2": jc2, "slot": "", "slot_name": timeText, "time_text": timeText,
		"weekday_name": weekdayNames[weekday], "building": result.BuildingName, "buildings": result.Buildings,
		"count": len(result.Rooms), "rooms": result.Rooms, "updated_at": time.Now().Unix(),
	}
}

type sharedJWCCandidate struct {
	sid    string
	client *jwc.Client
	sess   *session.Session
	source string
	owned  bool
}

func closeSharedJWCCandidates(candidates []sharedJWCCandidate) {
	for _, candidate := range candidates {
		if candidate.owned && candidate.client != nil {
			candidate.client.CloseIdleConnections()
		}
	}
}

func (s *Server) randomPersistentClients(ctx context.Context) []sharedJWCCandidate {
	result := make([]sharedJWCCandidate, 0, 8)
	seen := map[string]bool{}
	active := s.sessions.ActiveUndergraduate(20)
	rand.Shuffle(len(active), func(i, j int) { active[i], active[j] = active[j], active[i] })
	for _, sess := range active {
		if sess.StudentID == "" || strings.HasPrefix(sess.StudentID, "1") || seen[sess.StudentID] {
			continue
		}
		seen[sess.StudentID] = true
		result = append(result, sharedJWCCandidate{sid: sess.StudentID, client: sess.JWC, sess: sess, source: "active-session"})
		if len(result) >= 5 {
			return result
		}
	}
	ids, err := s.auth.PersistentStudentIDs(ctx)
	if err != nil {
		s.logger.Warn("读取教务 Cookie 池失败", "error", err)
		return result
	}
	rand.Shuffle(len(ids), func(i, j int) { ids[i], ids[j] = ids[j], ids[i] })
	if len(ids) > 50 {
		ids = ids[:50]
	}
	for _, sid := range ids {
		if strings.HasPrefix(sid, "1") || seen[sid] {
			continue
		}
		record, ok := s.auth.PersistentSession(ctx, sid)
		if !ok || strings.EqualFold(record.AccountType, "graduate") {
			continue
		}
		client := jwc.New(record.Cookies)
		client.StudentID = sid
		client.AccountType = record.AccountType
		client.SetTimeout(s.cfg.JWCRequestTimeout)
		seen[sid] = true
		result = append(result, sharedJWCCandidate{sid: sid, client: client, source: "persistent-cookie", owned: true})
		if len(result) >= 5 {
			break
		}
	}
	return result
}

func (s *Server) serviceAccountClient(ctx context.Context) (string, *jwc.Client, error) {
	sid, err := s.store.Setting(ctx, "free_classroom_sid")
	if err != nil {
		return "", nil, fmt.Errorf("读取本科服务账号: %w", err)
	}
	if sid = strings.TrimSpace(sid); sid == "" {
		sid = strings.TrimSpace(s.cfg.FreeClassroomSID)
	}
	if sid == "" {
		return "", nil, errors.New("未配置本科服务账号")
	}
	client := jwc.New(nil)
	client.SetTimeout(s.cfg.JWCRequestTimeout)
	if record, ok := s.auth.PersistentSession(ctx, sid); ok {
		client.ApplyCookies(record.Cookies)
	}
	err = s.withJWC(ctx, func() error {
		if err := client.Resume(ctx, sid); err == nil {
			return nil
		}
		password, ok, passwordErr := s.servicePassword(ctx)
		if passwordErr != nil {
			return passwordErr
		}
		if !ok {
			password, ok = s.auth.Credential(ctx, sid)
		}
		if !ok {
			return errors.New("服务账号 Cookie 已失效且没有可用密码")
		}
		return client.Login(ctx, sid, password)
	})
	if err != nil {
		client.CloseIdleConnections()
		return sid, nil, err
	}
	if saveErr := s.auth.SavePersistentSession(ctx, sid, client.AccountType, client.Cookies()); saveErr != nil {
		s.logger.Warn("服务账号登录后保存教务 Cookie 失败", "sid_prefix", maskedSID(sid), "error", saveErr)
	}
	return sid, client, nil
}

func (s *Server) queryFreeClassrooms(ctx context.Context, campus string, weekday, jc1, jc2, week int, semester, building string) (jwc.FreeClassroomResult, error) {
	var lastErr error
	candidates := s.randomPersistentClients(ctx)
	defer closeSharedJWCCandidates(candidates)
	for _, candidate := range candidates {
		var result jwc.FreeClassroomResult
		candidateCtx, cancel := contextWithSession(ctx, candidate.sess)
		unlock := func() {}
		if candidate.sess != nil {
			unlock = candidate.sess.Lock()
		}
		err := s.withJWC(candidateCtx, func() error {
			if err := candidate.client.Resume(candidateCtx, candidate.sid); err != nil {
				return err
			}
			var queryErr error
			result, queryErr = candidate.client.FreeClassrooms(candidateCtx, campus, weekday, jc1, jc2, week, semester, building)
			return queryErr
		})
		unlock()
		cancel()
		if err == nil {
			if saveErr := s.auth.SavePersistentSession(ctx, candidate.sid, candidate.client.AccountType, candidate.client.Cookies()); saveErr != nil {
				s.logger.Warn("空教室刷新后保存教务 Cookie 失败", "sid_prefix", maskedSID(candidate.sid), "error", saveErr)
			}
			s.logger.Info("空教室共享数据刷新成功", "source", candidate.source, "sid_prefix", maskedSID(candidate.sid))
			return result, nil
		}
		lastErr = err
	}

	// 服务账号兜底使用其持久 Cookie；若 Cookie 失效且保存过密码，再重新建立智慧理工会话。
	_, client, err := s.serviceAccountClient(ctx)
	if err == nil {
		defer client.CloseIdleConnections()
		var result jwc.FreeClassroomResult
		err = s.withJWC(ctx, func() error {
			var queryErr error
			result, queryErr = client.FreeClassrooms(ctx, campus, weekday, jc1, jc2, week, semester, building)
			return queryErr
		})
		if err == nil {
			return result, nil
		}
	}
	lastErr = err
	if lastErr == nil {
		lastErr = errors.New("没有可用的本科教务 Cookie")
	}
	return jwc.FreeClassroomResult{}, lastErr
}

func maskedSID(sid string) string {
	if len(sid) <= 3 {
		return "***"
	}
	return sid[:3] + "****"
}

func (s *Server) loadFreeClassrooms(ctx context.Context, campus string, weekday, jc1, jc2, week int, semester, building string) (map[string]any, error) {
	key := freeClassCacheKey(campus, weekday, jc1, jc2, week, semester, building)
	if value, ok := s.cacheGet(key); ok {
		if payload, valid := value.(map[string]any); valid {
			return payload, nil
		}
	}
	value, err := doOnceValue(ctx, s, key, func(callCtx context.Context) (map[string]any, error) {
		result, queryErr := s.queryFreeClassrooms(callCtx, campus, weekday, jc1, jc2, week, semester, building)
		if queryErr != nil {
			return nil, queryErr
		}
		payload := freeClassResponse(campus, weekday, jc1, jc2, week, semester, result)
		s.cacheSet(key, payload, untilTomorrow())
		return payload, nil
	})
	if err != nil {
		return nil, err
	}
	return value, nil
}

func (s *Server) freeClassrooms(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	q := r.URL.Query()
	campus := strings.TrimSpace(q.Get("campus"))
	if campus != "江阴" {
		campus = "孝陵卫"
	}
	weekday := parseInt(q.Get("weekday"), 0, 0, 7)
	if weekday == 0 {
		weekday = int(time.Now().In(beijing).Weekday())
		if weekday == 0 {
			weekday = 7
		}
	}
	jc1 := parseInt(q.Get("jc1"), 0, 0, 13)
	jc2 := parseInt(q.Get("jc2"), 0, 0, 13)
	if jc1 < 1 || jc2 < jc1 {
		slot := freeClassroomSlots[strings.TrimSpace(q.Get("slot"))]
		if slot == [2]int{} {
			slot = [2]int{6, 7}
		}
		jc1, jc2 = slot[0], slot[1]
	}
	semester := s.semesterFor(r, sess)
	week := parseInt(q.Get("week"), 0, 0, 30)
	if week == 0 {
		firstMonday, err := s.store.UserSetting(r.Context(), sess.StudentID, "first_week_date:"+semester)
		if err != nil {
			writeError(w, http.StatusInternalServerError, "读取教学周次失败")
			return
		}
		if firstMonday == "" {
			firstMonday, err = s.store.Setting(r.Context(), "first_week_date")
			if err != nil {
				writeError(w, http.StatusInternalServerError, "读取教学周次失败")
				return
			}
		}
		week = teachingWeek(firstMonday, time.Now())
	}
	building := strings.TrimSpace(q.Get("building"))
	if len([]rune(building)) > 50 {
		building = string([]rune(building)[:50])
	}
	payload, err := s.loadFreeClassrooms(r.Context(), campus, weekday, jc1, jc2, week, semester, building)
	if err != nil {
		s.logger.Warn("空教室查询失败", "error", err)
		mapJWCError(w, err, "教室数据暂时获取失败，请稍后重试")
		return
	}
	writeJSON(w, http.StatusOK, payload)
}

func parseUnix(raw string) int64 {
	value, _ := strconv.ParseInt(strings.TrimSpace(raw), 10, 64)
	return value
}
