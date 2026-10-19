package httpapi

import (
	"context"
	"database/sql"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/naughtygopher/webgo/v7"
	"github.com/resetinging/njust-schedule/internal/authn"
	"github.com/resetinging/njust-schedule/internal/captcha"
	"github.com/resetinging/njust-schedule/internal/config"
	"github.com/resetinging/njust-schedule/internal/jwc"
	"github.com/resetinging/njust-schedule/internal/security"
	"github.com/resetinging/njust-schedule/internal/session"
	"github.com/resetinging/njust-schedule/internal/store"
)

type Server struct {
	httpServer *http.Server
	cfg        config.Config
	db         *sql.DB
	store      *store.Store
	crypto     *security.Crypto
	auth       *authn.Service
	sessions   *session.Manager
	logger     *slog.Logger
	jwcSlots   chan struct{}
	captcha    *captcha.Solver

	ctx      context.Context
	cancel   context.CancelFunc
	wg       sync.WaitGroup
	migrated atomic.Bool
	stage    atomic.Value

	bootPending bool
	jobsOnce    sync.Once

	qrMu sync.Mutex
	qrs  map[string]*qrSession

	cacheMu sync.Mutex
	cache   map[string]cacheEntry

	dedupeMu sync.Mutex
	dedupe   map[string]*inflight

	rateMu sync.Mutex
	rates  map[string][]time.Time

	adminStarted time.Time
	adminMu      sync.Mutex
	adminTotal   int64
	adminSeq     int64
	adminRecent  []requestRecord
	adminAuthMu  sync.Mutex
	adminRevoked map[[32]byte]int64
	auditMu      sync.Mutex
	auditSync    auditSyncState
	analyticsMu  sync.Mutex
}

type qrSession struct {
	client    *jwc.Client
	expiresAt time.Time
	mu        sync.Mutex
	finished  bool
	payload   map[string]any
}

type cacheEntry struct {
	value     any
	expiresAt time.Time
}

type inflight struct {
	done    chan struct{}
	value   any
	err     error
	waiters int
}

type requestRecord struct {
	ID     int64   `json:"id"`
	TS     string  `json:"ts"`
	Epoch  float64 `json:"t"`
	Method string  `json:"method"`
	Path   string  `json:"path"`
	Status int     `json:"status"`
	MS     int64   `json:"ms"`
	SID    string  `json:"sid"`
	IP     string  `json:"ip"`
}

func New(cfg config.Config, db *sql.DB, logger *slog.Logger) (*Server, error) {
	crypto, err := security.New(cfg.SessionKey)
	if err != nil {
		return nil, err
	}
	repository := store.New(db)
	sessions, err := session.NewManager(cfg.SessionTTL, cfg.MaxSessions, cfg.RedisURL, crypto, logger)
	if err != nil {
		return nil, err
	}
	ctx, cancel := context.WithCancel(context.Background())
	s := &Server{
		cfg: cfg, db: db, store: repository, crypto: crypto,
		auth: authn.New(repository, crypto, cfg.PersistentSessionTTL, cfg.CredentialTrustTTL), sessions: sessions,
		logger: logger, jwcSlots: make(chan struct{}, cfg.JWMaxConcurrent),
		captcha: captcha.NewSolver(cfg.CaptchaOCRModelPath, cfg.CaptchaOCRRuntimePath),
		ctx:     ctx, cancel: cancel, qrs: map[string]*qrSession{}, cache: map[string]cacheEntry{},
		dedupe: map[string]*inflight{}, rates: map[string][]time.Time{}, adminStarted: time.Now(),
		adminRevoked: map[[32]byte]int64{}, bootPending: true,
	}
	s.stage.Store("booting")
	writeTimeout := serverWriteTimeout(cfg.JWCRequestTimeout)
	router := webgo.NewRouter(&webgo.Config{
		Host: "", Port: "", ReadTimeout: 15 * time.Second, WriteTimeout: writeTimeout,
	}, s.routes()...)
	s.httpServer = &http.Server{
		Addr: cfg.Address, Handler: middleware(logger, s, router),
		ReadHeaderTimeout: 10 * time.Second, ReadTimeout: 30 * time.Second,
		WriteTimeout: writeTimeout, IdleTimeout: 90 * time.Second,
	}
	return s, nil
}

func serverWriteTimeout(jwcTimeout time.Duration) time.Duration {
	return max(60*time.Second, 2*jwcTimeout+30*time.Second)
}

func (s *Server) ListenAndServe() error { return s.httpServer.ListenAndServe() }

func (s *Server) Listen() (net.Listener, error) {
	return net.Listen("tcp", s.httpServer.Addr)
}

func (s *Server) Serve(listener net.Listener) error {
	return s.httpServer.Serve(listener)
}

func (s *Server) MarkReady() { s.migrated.Store(true) }

func (s *Server) SetMigrationStage(stage string) {
	if stage != "" {
		s.stage.Store(stage)
	}
}

func (s *Server) MigrationStage() string {
	if value, ok := s.stage.Load().(string); ok {
		return value
	}
	return ""
}

func (s *Server) IsReady() bool {
	return !s.bootPending || s.migrated.Load()
}

func (s *Server) StartJobs() {
	s.jobsOnce.Do(s.startJobs)
}

func (s *Server) Shutdown(ctx context.Context) error {
	s.cancel()
	err := s.httpServer.Shutdown(ctx)
	done := make(chan struct{})
	go func() { s.wg.Wait(); close(done) }()
	select {
	case <-done:
	case <-ctx.Done():
		if err == nil {
			err = ctx.Err()
		}
	}
	if closeErr := s.sessions.Close(); err == nil {
		err = closeErr
	}
	if closeErr := s.captcha.Close(); err == nil {
		err = closeErr
	}
	return err
}

func (s *Server) routes() []*webgo.Route {
	route := func(method, pattern string, handler http.HandlerFunc) *webgo.Route {
		name := strings.ToLower(method) + "-" + strings.NewReplacer("/", "-", ":", "", "*", "wildcard").Replace(strings.TrimPrefix(pattern, "/"))
		return &webgo.Route{Name: name, Method: method, Pattern: pattern, Handlers: []http.HandlerFunc{handler}}
	}
	return []*webgo.Route{
		route(http.MethodGet, "/", s.index), route(http.MethodGet, "/healthz", s.health), route(http.MethodGet, "/readyz", s.ready), route(http.MethodGet, "/metrics", s.metrics),
		route(http.MethodGet, "/api/get-captcha", s.legacyCaptcha), route(http.MethodPost, "/api/login", s.legacyLogin), route(http.MethodPost, "/api/login-manual", s.legacyLogin), route(http.MethodPost, "/api/get-webvpn-captcha", s.loginCompat), route(http.MethodPost, "/api/login-webvpn-manual", s.legacyManualLogin), route(http.MethodPost, "/api/login-webvpn", s.login),
		route(http.MethodPost, "/api/sso-qr/start", s.qrStart), route(http.MethodGet, "/api/sso-qr/image", s.qrImage), route(http.MethodGet, "/api/sso-qr/status", s.qrStatus), route(http.MethodPost, "/api/sso-qr/cancel", s.qrCancel), route(http.MethodPost, "/api/logout", s.logout), route(http.MethodDelete, "/api/credentials", s.deleteCredential),
		route(http.MethodGet, "/api/status", s.status), route(http.MethodGet, "/api/prefetch-status", s.prefetchStatus), route(http.MethodGet, "/api/connect-test", s.connectTest),
		route(http.MethodGet, "/api/settings", s.getSettings), route(http.MethodPost, "/api/settings", s.saveSettings), route(http.MethodGet, "/api/semesters", s.semesters), route(http.MethodPost, "/api/semester", s.setSemester), route(http.MethodPost, "/api/clear-data", s.clearData),
		route(http.MethodGet, "/api/courses", s.courses), route(http.MethodGet, "/api/exams", s.exams), route(http.MethodPost, "/api/refresh-schedule", s.refreshSchedule), route(http.MethodPost, "/api/refresh-exams", s.refreshExams), route(http.MethodPost, "/api/refresh-all", s.refreshAll), route(http.MethodGet, "/api/yjs/courses", s.yjsCourses), route(http.MethodGet, "/api/yjs/exams", s.yjsExams),
		route(http.MethodGet, "/api/grades", s.grades), route(http.MethodPost, "/api/refresh-grades", s.refreshGrades), route(http.MethodGet, "/api/cet-scores", s.cetScores), route(http.MethodPost, "/api/refresh-cet", s.refreshCET), route(http.MethodGet, "/api/yjs/grades", s.yjsGrades),
		route(http.MethodGet, "/api/evaluations", s.evaluations), route(http.MethodPost, "/api/refresh-evaluations", s.refreshEvaluations), route(http.MethodGet, "/api/eval-courses", s.evalCourses), route(http.MethodGet, "/api/eval-form", s.evalForm), route(http.MethodPost, "/api/submit-eval", s.submitEval), route(http.MethodPost, "/api/jw-proxy", s.jwProxy),
		route(http.MethodGet, "/proxy/jw/:target_path*", s.jwBrowserProxy), route(http.MethodPost, "/proxy/jw/:target_path*", s.jwBrowserProxy),
		route(http.MethodGet, "/api/calendar", s.calendar), route(http.MethodPost, "/api/refresh-calendar", s.refreshCalendar), route(http.MethodGet, "/api/programme", s.programme), route(http.MethodPost, "/api/refresh-programme", s.refreshProgramme), route(http.MethodGet, "/api/profile", s.profile), route(http.MethodPost, "/api/refresh-profile", s.refreshProfile),
		route(http.MethodGet, "/api/free-classrooms", s.freeClassrooms), route(http.MethodGet, "/api/audit-courses", s.auditCourses), route(http.MethodGet, "/api/audit-options", s.auditOptions), route(http.MethodGet, "/api/audit-favorites", s.auditFavorites), route(http.MethodPost, "/api/audit-favorites", s.saveAuditFavorite), route(http.MethodDelete, "/api/audit-favorites/:favoriteID", s.deleteAuditFavorite),
		route(http.MethodGet, "/api/sync/versions", s.syncVersions), route(http.MethodPost, "/api/feedback", s.postFeedback), route(http.MethodGet, "/api/my-feedback", s.myFeedback), route(http.MethodPost, "/api/my-feedback/read", s.readFeedback), route(http.MethodGet, "/api/announcement", s.announcement), route(http.MethodGet, "/api/content-board", s.contentBoard),
		route(http.MethodGet, "/api/gallery-images", s.galleryImages), route(http.MethodGet, "/api/gallery-image", s.galleryImage), route(http.MethodGet, "/api/gallery-image-meta", s.galleryImageMeta), route(http.MethodGet, "/api/gallery-image-part", s.galleryImagePart),
		route(http.MethodGet, "/api/font/pixel", s.pixelFont), route(http.MethodGet, "/api/font/pixel.json", s.pixelFontJSON), route(http.MethodPost, "/api/font/subset", s.fontSubset), route(http.MethodGet, "/api/font/list", s.fontList),
		route(http.MethodPost, "/api/subscribe/grant", s.subscribeGrant), route(http.MethodGet, "/api/subscribe/status", s.subscribeStatus), route(http.MethodPost, "/api/subscribe/test-send", s.subscribeTestSend), route(http.MethodPost, "/api/analytics/events", s.analyticsEvents),
		route(http.MethodGet, "/admin", s.adminPage), route(http.MethodGet, "/admin/", s.adminPage), route(http.MethodPost, "/api/admin/login", s.adminLogin), route(http.MethodPost, "/api/admin/logout", s.adminLogout), route(http.MethodGet, "/api/admin/summary", s.adminSummary), route(http.MethodGet, "/api/admin/users", s.adminUsers), route(http.MethodGet, "/api/admin/users/:sid", s.adminUser), route(http.MethodGet, "/api/admin/stats/grades", s.adminGradeStats), route(http.MethodGet, "/api/admin/requests", s.adminRequests), route(http.MethodGet, "/api/admin/sessions", s.adminSessions), route(http.MethodDelete, "/api/admin/sessions/:sid", s.adminDeleteSession), route(http.MethodGet, "/api/admin/audit-status", s.adminAuditStatus), route(http.MethodPost, "/api/admin/audit-sync", s.adminAuditSync), route(http.MethodGet, "/api/admin/stats/requests", s.adminRequestStats), route(http.MethodGet, "/api/admin/analytics", s.adminAnalytics), route(http.MethodGet, "/api/admin/announcement", s.adminAnnouncement), route(http.MethodPost, "/api/admin/announcement", s.adminSaveAnnouncement), route(http.MethodGet, "/api/admin/content-board", s.adminContentBoard), route(http.MethodPost, "/api/admin/content-board", s.adminSaveContentBoard), route(http.MethodGet, "/api/admin/freeclass-account", s.adminFreeclassAccount), route(http.MethodPost, "/api/admin/freeclass-account", s.adminSaveFreeclassAccount), route(http.MethodPost, "/api/admin/fetch-names", s.adminFetchNames), route(http.MethodGet, "/api/admin/feedback", s.adminFeedback), route(http.MethodPost, "/api/admin/feedback/:fid", s.adminFeedbackStatus), route(http.MethodDelete, "/api/admin/feedback/:fid", s.adminDeleteFeedback), route(http.MethodPost, "/api/admin/feedback/:fid/reply", s.adminReplyFeedback), route(http.MethodGet, "/api/admin/check", s.adminCheck),
		route(http.MethodGet, "/static/:path*", s.staticFile),
	}
}

func (s *Server) health(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"ok": true, "service": "njust-schedule", "runtime": "webgo"})
}

func (s *Server) ready(w http.ResponseWriter, r *http.Request) {
	checks := map[string]any{
		"migration": s.IsReady(),
		"stage":     s.MigrationStage(),
		"database":  true,
		"redis":     "disabled",
	}
	if !s.IsReady() {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{"ok": false, "checks": checks})
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	if err := s.db.PingContext(ctx); err != nil {
		checks["database"] = false
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{"ok": false, "checks": checks})
		return
	}
	if enabled, err := s.sessions.Ready(ctx); enabled {
		checks["redis"] = err == nil
		if err != nil {
			writeJSON(w, http.StatusServiceUnavailable, map[string]any{"ok": false, "checks": checks})
			return
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true, "checks": checks})
}

func (s *Server) acquireJWC(ctx context.Context) error {
	select {
	case s.jwcSlots <- struct{}{}:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (s *Server) releaseJWC() { <-s.jwcSlots }

func (s *Server) withJWC(ctx context.Context, fn func() error) error {
	if err := s.acquireJWC(ctx); err != nil {
		return err
	}
	defer s.releaseJWC()
	return fn()
}

type sessionLocker interface {
	Lock() func()
}

func (s *Server) withSessionJWC(ctx context.Context, sess sessionLocker, fn func() error) error {
	unlock := sess.Lock()
	defer unlock()
	return s.withJWC(ctx, fn)
}

func doOnceValue[T any](ctx context.Context, s *Server, key string, fn func(context.Context) (T, error)) (T, error) {
	var zero T
	s.dedupeMu.Lock()
	call := s.dedupe[key]
	if call == nil {
		call = &inflight{done: make(chan struct{})}
		s.dedupe[key] = call
		parent := s.ctx
		if parent == nil {
			parent = context.Background()
		}
		timeout := max(2*time.Minute, 3*s.cfg.JWCRequestTimeout)
		s.wg.Add(1)
		go runDedupedCall(s, parent, timeout, key, call, fn)
	}
	call.waiters++
	s.dedupeMu.Unlock()
	defer func() {
		s.dedupeMu.Lock()
		call.waiters--
		s.dedupeMu.Unlock()
	}()
	select {
	case <-ctx.Done():
		return zero, ctx.Err()
	case <-call.done:
		if call.err != nil {
			return zero, call.err
		}
		value, ok := call.value.(T)
		if !ok {
			return zero, fmt.Errorf("合并请求结果类型不匹配: %s", key)
		}
		return value, nil
	}
}

func runDedupedCall[T any](s *Server, parent context.Context, timeout time.Duration, key string, call *inflight, fn func(context.Context) (T, error)) {
	defer s.wg.Done()
	ctx, cancel := context.WithTimeout(parent, timeout)
	defer cancel()
	var value T
	func() {
		defer func() {
			if recovered := recover(); recovered != nil {
				call.err = fmt.Errorf("合并请求执行异常: %v", recovered)
			}
		}()
		value, call.err = fn(ctx)
	}()
	call.value = value
	s.dedupeMu.Lock()
	if s.dedupe[key] == call {
		delete(s.dedupe, key)
	}
	close(call.done)
	s.dedupeMu.Unlock()
}
