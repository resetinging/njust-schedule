package authn

import (
	"context"
	"crypto/hmac"
	"time"

	"github.com/resetinging/njust-schedule/internal/security"
	"github.com/resetinging/njust-schedule/internal/store"
)

const credentialKey = "credential"
const persistentSessionKey = "jwc_session"

type Service struct {
	store              *store.Store
	crypto             *security.Crypto
	cacheTTL, trustTTL time.Duration
}
type credential struct {
	Password   string `json:"pwd"`
	Timestamp  int64  `json:"ts"`
	VerifiedAt int64  `json:"verified_at"`
	UsedAt     int64  `json:"used_at"`
	Fail       int    `json:"fail"`
}

func New(repository *store.Store, crypto *security.Crypto, cacheTTL, trustTTL time.Duration) *Service {
	return &Service{store: repository, crypto: crypto, cacheTTL: cacheTTL, trustTTL: trustTTL}
}

func (s *Service) SaveCredential(ctx context.Context, sid, password string) error {
	now := time.Now().Unix()
	value := credential{password, now, now, 0, 0}
	blob, err := s.crypto.Encrypt(sid, value)
	if err != nil {
		return err
	}
	return s.store.SetUserSetting(ctx, sid, credentialKey, blob)
}
func (s *Service) Credential(ctx context.Context, sid string) (string, bool) {
	value, ok := s.loadCredential(ctx, sid)
	if !ok {
		return "", false
	}
	return value.Password, true
}
func (s *Service) CanResume(ctx context.Context, sid, password string) bool {
	value, ok := s.loadCredential(ctx, sid)
	if !ok || !hmac.Equal([]byte(value.Password), []byte(password)) {
		return false
	}
	verified := value.VerifiedAt
	if verified == 0 {
		verified = value.Timestamp
	}
	age := time.Since(time.Unix(verified, 0))
	return age >= 0 && age < s.trustTTL
}
func (s *Service) loadCredential(ctx context.Context, sid string) (credential, bool) {
	blob, err := s.store.UserSetting(ctx, sid, credentialKey)
	if err != nil || blob == "" {
		return credential{}, false
	}
	var value credential
	if s.crypto.Decrypt(sid, blob, &value) != nil || value.Password == "" {
		return credential{}, false
	}
	return value, true
}
func (s *Service) MarkCredentialUsed(ctx context.Context, sid string) error {
	value, ok := s.loadCredential(ctx, sid)
	if !ok {
		return nil
	}
	value.UsedAt = time.Now().Unix()
	value.Fail = 0
	blob, err := s.crypto.Encrypt(sid, value)
	if err != nil {
		return err
	}
	return s.store.SetUserSetting(ctx, sid, credentialKey, blob)
}
func (s *Service) DropCredential(ctx context.Context, sid string) error {
	return s.store.DeleteUserSetting(ctx, sid, credentialKey)
}
func (s *Service) DeleteToken(sid string) string         { return s.crypto.DeleteToken(sid, 30*24*time.Hour) }
func (s *Service) VerifyDeleteToken(token string) string { return s.crypto.VerifyDeleteToken(token) }
func (s *Service) SavePersistentSession(ctx context.Context, sid, accountType string, cookies []store.Cookie) error {
	value := store.PersistentSession{Timestamp: time.Now().Unix(), Cookies: cookies, AccountType: accountType}
	blob, err := s.crypto.Encrypt(sid, value)
	if err != nil {
		return err
	}
	return s.store.SetUserSetting(ctx, sid, persistentSessionKey, blob)
}
func (s *Service) PersistentSession(ctx context.Context, sid string) (store.PersistentSession, bool) {
	blob, err := s.store.UserSetting(ctx, sid, persistentSessionKey)
	if err != nil || blob == "" {
		return store.PersistentSession{}, false
	}
	var value store.PersistentSession
	if s.crypto.Decrypt(sid, blob, &value) != nil || len(value.Cookies) == 0 {
		return store.PersistentSession{}, false
	}
	age := time.Since(time.Unix(value.Timestamp, 0))
	if age < 0 || age > s.cacheTTL {
		return store.PersistentSession{}, false
	}
	return value, true
}
func (s *Service) PersistentStudentIDs(ctx context.Context) ([]string, error) {
	return s.store.UserIDsForSetting(ctx, persistentSessionKey)
}
