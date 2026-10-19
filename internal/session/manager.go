package session

import (
	"container/list"
	"context"
	"crypto/hmac"
	"errors"
	"log/slog"
	"strings"
	"sync"
	"time"

	"github.com/redis/go-redis/v9"
	"github.com/resetinging/njust-schedule/internal/jwc"
	"github.com/resetinging/njust-schedule/internal/security"
	"github.com/resetinging/njust-schedule/internal/store"
)

type Session struct {
	Token        string         `json:"-"`
	StudentID    string         `json:"student_id"`
	StudentName  string         `json:"student_name"`
	AccountType  string         `json:"account_type"`
	LoginMethod  string         `json:"login_method"`
	Cookies      []store.Cookie `json:"cookies"`
	LastActivity time.Time      `json:"-"`
	CreatedAt    time.Time      `json:"-"`
	RefreshState map[string]any `json:"-"`
	JWC          *jwc.Client    `json:"-"`
	mu           sync.Mutex
	stateMu      sync.RWMutex
	lifecycleMu  sync.Mutex
	lifecycleCtx context.Context
	cancel       context.CancelFunc
	remoteSaved  time.Time
}

func (s *Session) Lock() func() { s.mu.Lock(); return s.mu.Unlock }

func (s *Session) SetRefreshState(value map[string]any) {
	s.stateMu.Lock()
	s.RefreshState = value
	s.stateMu.Unlock()
}

func (s *Session) GetRefreshState() map[string]any {
	s.stateMu.RLock()
	defer s.stateMu.RUnlock()
	if s.RefreshState == nil {
		return nil
	}
	copy := make(map[string]any, len(s.RefreshState))
	for key, value := range s.RefreshState {
		copy[key] = value
	}
	return copy
}

func (s *Session) Context() context.Context {
	s.lifecycleMu.Lock()
	defer s.lifecycleMu.Unlock()
	if s.lifecycleCtx == nil {
		s.lifecycleCtx, s.cancel = context.WithCancel(context.Background())
	}
	return s.lifecycleCtx
}

func (s *Session) activate() {
	s.lifecycleMu.Lock()
	if s.cancel != nil {
		s.cancel()
	}
	s.lifecycleCtx, s.cancel = context.WithCancel(context.Background())
	s.lifecycleMu.Unlock()
}

func (s *Session) close() {
	s.lifecycleMu.Lock()
	if s.cancel != nil {
		s.cancel()
	}
	s.lifecycleMu.Unlock()
	if s.JWC != nil {
		s.JWC.CloseIdleConnections()
	}
}

type entry struct {
	session *Session
	element *list.Element
}

type Manager struct {
	mu         sync.Mutex
	mutationMu sync.Mutex
	byToken    map[string]*entry
	byStudent  map[string]string
	lru        *list.List
	ttl        time.Duration
	max        int
	redis      *redis.Client
	crypto     *security.Crypto
	logger     *slog.Logger
}

func NewManager(ttl time.Duration, max int, redisURL string, crypto *security.Crypto, loggers ...*slog.Logger) (*Manager, error) {
	logger := slog.Default()
	if len(loggers) > 0 && loggers[0] != nil {
		logger = loggers[0]
	}
	m := &Manager{byToken: map[string]*entry{}, byStudent: map[string]string{}, lru: list.New(), ttl: ttl, max: max, crypto: crypto, logger: logger}
	if strings.TrimSpace(redisURL) != "" {
		options, err := redis.ParseURL(redisURL)
		if err != nil {
			return nil, err
		}
		m.redis = redis.NewClient(options)
	}
	return m, nil
}

func (m *Manager) Close() error {
	m.mutationMu.Lock()
	defer m.mutationMu.Unlock()
	m.mu.Lock()
	for token := range m.byToken {
		m.removeLocked(token)
	}
	m.mu.Unlock()
	if m.redis != nil {
		return m.redis.Close()
	}
	return nil
}

func (m *Manager) Ready(ctx context.Context) (bool, error) {
	if m.redis == nil {
		return false, nil
	}
	return true, m.redis.Ping(ctx).Err()
}

func (m *Manager) Add(ctx context.Context, value *Session) (string, error) {
	m.mutationMu.Lock()
	defer m.mutationMu.Unlock()

	token, err := security.NewOpaqueToken()
	if err != nil {
		return "", err
	}
	now := time.Now()
	value.Token = token
	value.CreatedAt = now
	value.LastActivity = now
	value.remoteSaved = now
	var staleTokens []string
	if err := m.saveRemote(ctx, value); err != nil {
		rollbackErr := m.rollbackRemoteAdd(ctx, value.StudentID, token)
		return "", errors.Join(err, rollbackErr)
	}
	m.mu.Lock()
	value.activate()
	if old := m.byStudent[value.StudentID]; old != "" {
		staleTokens = append(staleTokens, old)
		m.removeLocked(old)
	}
	element := m.lru.PushFront(token)
	m.byToken[token] = &entry{session: value, element: element}
	m.byStudent[value.StudentID] = token
	for len(m.byToken) > m.max {
		stale := m.lru.Back().Value.(string)
		staleTokens = append(staleTokens, stale)
		m.removeLocked(stale)
	}
	m.mu.Unlock()
	for _, stale := range staleTokens {
		if err := m.deleteRemoteToken(ctx, stale, ""); err != nil {
			m.logger.Warn("删除被替代的远端会话失败", "error", err)
		}
	}
	return token, nil
}

func (m *Manager) Get(ctx context.Context, token string) (*Session, bool) {
	if token == "" {
		return nil, false
	}
	m.mu.Lock()
	if item := m.byToken[token]; item != nil {
		if time.Since(item.session.LastActivity) <= m.ttl {
			now := time.Now()
			item.session.LastActivity = now
			m.lru.MoveToFront(item.element)
			value := item.session
			persist := now.Sub(value.remoteSaved) >= time.Minute
			if persist {
				value.remoteSaved = now
			}
			m.mu.Unlock()
			if persist {
				renewed, err := m.refreshRemote(ctx, value)
				if err != nil {
					m.logger.Warn("续期远端会话失败", "student_id_prefix", maskedStudentID(value.StudentID), "error", err)
					m.mu.Lock()
					if current := m.byToken[token]; current != nil && current.session == value {
						value.remoteSaved = time.Time{}
					}
					m.mu.Unlock()
				} else if !renewed {
					m.mu.Lock()
					if current := m.byToken[token]; current != nil && current.session == value {
						m.removeLocked(token)
					}
					m.mu.Unlock()
					return nil, false
				}
			}
			return value, true
		}
		m.removeLocked(token)
	}
	m.mu.Unlock()
	value, err := m.loadRemote(ctx, token)
	if err != nil || value == nil {
		return nil, false
	}
	value.Token = token
	value.LastActivity = time.Now()
	value.CreatedAt = time.Now()
	value.remoteSaved = time.Now()
	value.JWC = jwc.New(value.Cookies)
	value.JWC.StudentID = value.StudentID
	value.JWC.StudentName = value.StudentName
	value.JWC.AccountType = value.AccountType
	value.JWC.LoginMethod = value.LoginMethod
	value.activate()
	m.mu.Lock()
	if existing := m.byToken[token]; existing != nil {
		m.mu.Unlock()
		value.close()
		return existing.session, true
	}
	if current := m.byStudent[value.StudentID]; current != "" && current != token {
		m.mu.Unlock()
		value.close()
		return nil, false
	}
	element := m.lru.PushFront(token)
	m.byToken[token] = &entry{session: value, element: element}
	m.byStudent[value.StudentID] = token
	var staleTokens []string
	for len(m.byToken) > m.max {
		stale := m.lru.Back().Value.(string)
		staleTokens = append(staleTokens, stale)
		m.removeLocked(stale)
	}
	m.mu.Unlock()
	for _, stale := range staleTokens {
		if err := m.deleteRemoteToken(ctx, stale, ""); err != nil {
			m.logger.Warn("删除淘汰的远端会话失败", "error", err)
		}
	}
	return value, true
}

func maskedStudentID(value string) string {
	if len(value) <= 3 {
		return "***"
	}
	return value[:3] + "****"
}

func (m *Manager) Delete(ctx context.Context, token string) error {
	m.mutationMu.Lock()
	defer m.mutationMu.Unlock()
	m.mu.Lock()
	sid := m.removeLocked(token)
	m.mu.Unlock()
	return m.deleteRemoteToken(ctx, token, sid)
}

func (m *Manager) DeleteStudent(ctx context.Context, sid string) (bool, error) {
	m.mutationMu.Lock()
	defer m.mutationMu.Unlock()
	m.mu.Lock()
	token := m.byStudent[sid]
	m.removeLocked(token)
	m.mu.Unlock()
	if m.redis == nil {
		return token != "", nil
	}
	const script = `
local current = redis.call('GET', KEYS[1])
local expected = ARGV[1]
local token_prefix = ARGV[2]
if expected ~= '' then
  local removed = redis.call('DEL', token_prefix .. expected)
  if current == expected then
    redis.call('DEL', KEYS[1])
    return 1
  end
  return removed
end
if not current then
  return 0
end
redis.call('DEL', KEYS[1])
redis.call('DEL', token_prefix .. current)
return 1`
	removed, err := m.redis.Eval(ctx, script, []string{"wx:session:sid:" + sid}, token, "wx:session:token:").Int64()
	if err != nil {
		return false, err
	}
	return removed != 0, nil
}

func (m *Manager) List() []map[string]any {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]map[string]any, 0, len(m.byToken))
	for token, item := range m.byToken {
		s := item.session
		prefix := token
		if len(prefix) > 6 {
			prefix = prefix[:6] + "…"
		}
		out = append(out, map[string]any{"student_id": s.StudentID, "student_name": s.StudentName, "name": s.StudentName, "account_type": s.AccountType, "login_method": s.LoginMethod, "last_activity": s.LastActivity.Unix(), "active_sec": max(0, int(time.Since(s.LastActivity).Seconds())), "age": max(0, int(time.Since(s.CreatedAt).Seconds())), "token": prefix})
	}
	return out
}

func (m *Manager) Count() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	return len(m.byToken)
}

func (m *Manager) ActiveUndergraduate(limit int) []*Session {
	m.mu.Lock()
	defer m.mu.Unlock()
	if limit <= 0 {
		limit = m.max
	}
	out := make([]*Session, 0, min(limit, len(m.byToken)))
	for element := m.lru.Front(); element != nil && len(out) < limit; element = element.Next() {
		item := m.byToken[element.Value.(string)]
		if item == nil || item.session == nil || strings.EqualFold(item.session.AccountType, "graduate") || item.session.JWC == nil {
			continue
		}
		out = append(out, item.session)
	}
	return out
}

func (m *Manager) removeLocked(token string) string {
	if token == "" {
		return ""
	}
	item := m.byToken[token]
	if item == nil {
		return ""
	}
	delete(m.byToken, token)
	if m.byStudent[item.session.StudentID] == token {
		delete(m.byStudent, item.session.StudentID)
	}
	m.lru.Remove(item.element)
	item.session.close()
	return item.session.StudentID
}

func (m *Manager) saveRemote(ctx context.Context, s *Session) error {
	if m.redis == nil {
		return nil
	}
	blob, err := m.remotePayload(s)
	if err != nil {
		return err
	}
	pipe := m.redis.TxPipeline()
	pipe.Set(ctx, "wx:session:token:"+s.Token, blob, m.ttl)
	pipe.Set(ctx, "wx:session:sid:"+s.StudentID, s.Token, m.ttl)
	_, err = pipe.Exec(ctx)
	return err
}

func (m *Manager) refreshRemote(ctx context.Context, s *Session) (bool, error) {
	if m.redis == nil {
		return true, nil
	}
	blob, err := m.remotePayload(s)
	if err != nil {
		return false, err
	}
	const script = `if redis.call('GET', KEYS[2]) ~= ARGV[1] then return 0 end; redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3]); redis.call('EXPIRE', KEYS[2], ARGV[3]); return 1`
	result, err := m.redis.Eval(ctx, script,
		[]string{"wx:session:token:" + s.Token, "wx:session:sid:" + s.StudentID},
		s.Token, blob, max(1, int(m.ttl/time.Second))).Int64()
	if err != nil {
		return false, err
	}
	return result == 1, nil
}

func (m *Manager) remotePayload(s *Session) (string, error) {
	cookies := s.Cookies
	if s.JWC != nil {
		cookies = s.JWC.Cookies()
	}
	payload := map[string]any{"student_id": s.StudentID, "student_name": s.StudentName, "account_type": s.AccountType, "login_method": s.LoginMethod, "cookies": cookies}
	return m.crypto.Encrypt(s.Token, payload)
}

func (m *Manager) deleteRemoteToken(ctx context.Context, token, sid string) error {
	if m.redis == nil || token == "" {
		return nil
	}
	const script = `local sid = redis.call('GET', KEYS[2]); redis.call('DEL', KEYS[1]); if sid == ARGV[1] then redis.call('DEL', KEYS[2]); end; return 1`
	if sid == "" {
		blob, err := m.redis.Get(ctx, "wx:session:token:"+token).Result()
		if err != nil && !errors.Is(err, redis.Nil) {
			return err
		}
		if err == nil {
			var value Session
			if err = m.crypto.Decrypt(token, blob, &value); err != nil {
				return err
			}
			sid = value.StudentID
		}
	}
	if sid == "" {
		return m.redis.Del(ctx, "wx:session:token:"+token).Err()
	}
	return m.redis.Eval(ctx, script, []string{"wx:session:token:" + token, "wx:session:sid:" + sid}, token).Err()
}

func (m *Manager) rollbackRemoteAdd(ctx context.Context, sid, token string) error {
	if m.redis == nil || token == "" {
		return nil
	}
	const script = `redis.call('DEL', KEYS[1]); if redis.call('GET', KEYS[2]) == ARGV[1] then redis.call('DEL', KEYS[2]); end; return 1`
	return m.redis.Eval(ctx, script, []string{"wx:session:token:" + token, "wx:session:sid:" + sid}, token).Err()
}

func (m *Manager) loadRemote(ctx context.Context, token string) (*Session, error) {
	if m.redis == nil {
		return nil, errors.New("redis disabled")
	}
	blob, err := m.redis.Get(ctx, "wx:session:token:"+token).Result()
	if err != nil {
		return nil, err
	}
	var value Session
	if err = m.crypto.Decrypt(token, blob, &value); err != nil {
		return nil, err
	}
	if value.StudentID == "" {
		return nil, errors.New("invalid session")
	}
	current, err := m.redis.Get(ctx, "wx:session:sid:"+value.StudentID).Result()
	if err != nil || !hmac.Equal([]byte(current), []byte(token)) {
		cleanupErr := m.redis.Del(ctx, "wx:session:token:"+token).Err()
		return nil, errors.Join(errors.New("session superseded"), err, cleanupErr)
	}
	return &value, nil
}

func EqualPassword(a, b string) bool { return hmac.Equal([]byte(a), []byte(b)) }
