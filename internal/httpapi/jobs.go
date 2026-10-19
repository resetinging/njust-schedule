package httpapi

import (
	"context"
	"os"
	"strings"
	"time"
)

func envEnabled(name string) bool {
	value := strings.ToLower(strings.TrimSpace(os.Getenv(name)))
	return value != "0" && value != "false" && value != "off"
}

func (s *Server) startJobs() {
	s.runLoop("state-cleanup", time.Minute, false, s.cleanupRuntimeState)
	s.runLoop("network-probe", 5*time.Minute, true, func(ctx context.Context) {
		s.networkStatus(ctx, true)
	})
	if envEnabled("AUDIT_CATALOG_SYNC") {
		s.runDaily("audit-catalog", 0, 5, func(ctx context.Context) {
			semester := currentSemester()
			status := s.auditStatus(ctx, semester)
			if status["needs_refresh"] == true {
				s.startAuditSync(semester)
			}
		})
	}
	if envEnabled("FREE_CLASSROOM_PREWARM") {
		s.runDaily("freeclass-prewarm", 0, 2, s.prewarmFreeClassrooms)
	}
	if envEnabled("EXAM_REMINDER") && s.cfg.MPAppID != "" && s.cfg.MPSecret != "" {
		s.runLoop("reminder", 10*time.Minute, true, s.runReminderJobs)
	}
}

func (s *Server) runLoop(name string, interval time.Duration, immediate bool, job func(context.Context)) {
	s.wg.Add(1)
	go func() {
		defer s.wg.Done()
		if immediate {
			s.runJob(name, job)
		}
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for {
			select {
			case <-s.ctx.Done():
				return
			case <-ticker.C:
				s.runJob(name, job)
			}
		}
	}()
}

func (s *Server) runDaily(name string, hour, minute int, job func(context.Context)) {
	s.wg.Add(1)
	go func() {
		defer s.wg.Done()
		s.runJob(name, job)
		for {
			now := time.Now().In(beijing)
			next := time.Date(now.Year(), now.Month(), now.Day(), hour, minute, 0, 0, beijing)
			if !next.After(now) {
				next = next.AddDate(0, 0, 1)
			}
			timer := time.NewTimer(time.Until(next))
			select {
			case <-s.ctx.Done():
				if !timer.Stop() {
					<-timer.C
				}
				return
			case <-timer.C:
				s.runJob(name, job)
			}
		}
	}()
}

func (s *Server) runJob(name string, job func(context.Context)) {
	ctx, cancel := context.WithTimeout(s.ctx, time.Hour)
	defer cancel()
	defer func() {
		if recovered := recover(); recovered != nil {
			s.logger.Error("后台任务发生 panic", "job", name, "error", recovered)
		}
	}()
	job(ctx)
}

func (s *Server) cleanupRuntimeState(_ context.Context) {
	now := time.Now()
	s.cacheMu.Lock()
	for key, item := range s.cache {
		if now.After(item.expiresAt) {
			delete(s.cache, key)
		}
	}
	s.cacheMu.Unlock()
	s.cleanupExpiredQR(now)
	s.rateMu.Lock()
	cutoff := now.Add(-24 * time.Hour)
	for key, values := range s.rates {
		kept := values[:0]
		for _, value := range values {
			if value.After(cutoff) {
				kept = append(kept, value)
			}
		}
		if len(kept) == 0 {
			delete(s.rates, key)
		} else {
			s.rates[key] = kept
		}
	}
	s.rateMu.Unlock()
}

func (s *Server) prewarmFreeClassrooms(ctx context.Context) {
	semester := currentSemester()
	firstMonday, err := s.store.Setting(ctx, "first_week_date")
	if err != nil {
		s.logger.Warn("空教室预热读取教学周次失败", "error", err)
		return
	}
	now := time.Now().In(beijing)
	weekday := int(now.Weekday())
	if weekday == 0 {
		weekday = 7
	}
	week := teachingWeek(firstMonday, now)
	for _, campus := range []string{"孝陵卫", "江阴"} {
		for _, slot := range [][2]int{{1, 3}, {4, 5}, {6, 7}, {8, 10}, {11, 13}} {
			if ctx.Err() != nil {
				return
			}
			if _, err := s.loadFreeClassrooms(ctx, campus, weekday, slot[0], slot[1], week, semester, ""); err != nil {
				s.logger.Warn("空教室预热失败", "campus", campus, "jc1", slot[0], "jc2", slot[1], "error", err)
			}
		}
	}
}

func (s *Server) runReminderJobs(ctx context.Context) {
	if err := s.sendDueExamReminders(ctx); err != nil {
		s.logger.Warn("考试提醒扫描失败", "error", err)
	}
	if envEnabled("REMINDER_LIFECYCLE") {
		if err := s.runReminderPool(ctx, 200); err != nil {
			s.logger.Warn("成绩提醒扫描失败", "error", err)
		}
	}
}
