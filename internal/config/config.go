package config

import (
	"encoding/base64"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	Address               string
	MySQLAddress          string
	MySQLUsername         string
	MySQLPassword         string
	MySQLDatabase         string
	RedisURL              string
	SessionKey            []byte
	AdminPassword         string
	SessionTTL            time.Duration
	DataCacheTTL          time.Duration
	CredentialTrustTTL    time.Duration
	PersistentSessionTTL  time.Duration
	MaxSessions           int
	JWMaxConcurrent       int
	TrustedProxyHops      int
	MigrationsAuto        bool
	StaticDir             string
	MPAppID               string
	MPSecret              string
	SubscribeExam         string
	SubscribeGrade        string
	FreeClassroomSID      string
	JWCRequestTimeout     time.Duration
	CaptchaOCRModelPath   string
	CaptchaOCRRuntimePath string
}

func Load() (Config, error) {
	cfg := Config{
		Address:               env("ADDRESS", ":80"),
		MySQLAddress:          strings.TrimSpace(os.Getenv("MYSQL_ADDRESS")),
		MySQLUsername:         strings.TrimSpace(os.Getenv("MYSQL_USERNAME")),
		MySQLPassword:         os.Getenv("MYSQL_PASSWORD"),
		MySQLDatabase:         env("MYSQL_DATABASE", "flask_demo"),
		RedisURL:              strings.TrimSpace(os.Getenv("REDIS_URL")),
		AdminPassword:         os.Getenv("ADMIN_PASSWORD"),
		SessionTTL:            seconds("SESSION_TTL", 12*time.Hour, time.Minute, 30*24*time.Hour),
		DataCacheTTL:          seconds("DATA_CACHE_TTL", 30*24*time.Hour, time.Minute, 365*24*time.Hour),
		CredentialTrustTTL:    seconds("CREDENTIAL_TRUST_TTL", 24*time.Hour, time.Minute, 30*24*time.Hour),
		PersistentSessionTTL:  seconds("SSO_SESSION_MAX_AGE", 30*24*time.Hour, time.Minute, 365*24*time.Hour),
		MaxSessions:           integer("MAX_SESSIONS", 200, 1, 100000),
		JWMaxConcurrent:       integer("JW_MAX_CONCURRENT", 4, 1, 64),
		TrustedProxyHops:      integer("TRUSTED_PROXY_HOPS", 1, 1, 20),
		MigrationsAuto:        boolean("MIGRATIONS_AUTO", false),
		StaticDir:             env("STATIC_DIR", "wxcloudrun/static"),
		MPAppID:               env("MP_APPID", "wx1d76c0631bdeebac"),
		MPSecret:              os.Getenv("MP_SECRET"),
		SubscribeExam:         env("SUBSCRIBE_TPL_EXAM", "ng8fatzWFGkwY5Q5X2QM-BNktLyMLQPaJl2xFi7Z180"),
		FreeClassroomSID:      env("FREE_CLASSROOM_SID", "924101960123"),
		JWCRequestTimeout:     seconds("JW_REQUEST_TIMEOUT", 30*time.Second, 5*time.Second, 2*time.Minute),
		CaptchaOCRModelPath:   env("CAPTCHA_OCR_MODEL_PATH", "common.onnx"),
		CaptchaOCRRuntimePath: strings.TrimSpace(os.Getenv("ONNXRUNTIME_SHARED_LIBRARY_PATH")),
	}
	cfg.SubscribeGrade = env("SUBSCRIBE_TPL_GRADE", cfg.SubscribeExam)

	if raw := strings.TrimSpace(os.Getenv("SESSION_KEY")); raw != "" {
		key, err := base64.StdEncoding.DecodeString(raw)
		if err != nil || len(key) != 32 {
			return Config{}, errors.New("SESSION_KEY 必须是可解码为 32 字节的 base64")
		}
		cfg.SessionKey = key
	}

	var missing []string
	for name, value := range map[string]string{
		"MYSQL_ADDRESS":  cfg.MySQLAddress,
		"MYSQL_USERNAME": cfg.MySQLUsername,
		"MYSQL_PASSWORD": cfg.MySQLPassword,
	} {
		if value == "" {
			missing = append(missing, name)
		}
	}
	if len(missing) > 0 {
		return Config{}, fmt.Errorf("数据库配置缺失: %s", strings.Join(missing, ", "))
	}
	if cfg.AdminPassword == "" {
		return Config{}, errors.New("ADMIN_PASSWORD 未配置")
	}
	if len(cfg.SessionKey) == 0 {
		return Config{}, errors.New("SESSION_KEY 未配置")
	}
	return cfg, nil
}

func LogLevel(raw string) slog.Level {
	switch strings.ToUpper(strings.TrimSpace(raw)) {
	case "DEBUG":
		return slog.LevelDebug
	case "WARN", "WARNING":
		return slog.LevelWarn
	case "ERROR":
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}

func env(name, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(name)); value != "" {
		return value
	}
	return fallback
}

func integer(name string, fallback, minValue, maxValue int) int {
	value, err := strconv.Atoi(strings.TrimSpace(os.Getenv(name)))
	if err != nil {
		value = fallback
	}
	if value < minValue {
		return minValue
	}
	if value > maxValue {
		return maxValue
	}
	return value
}

func boolean(name string, fallback bool) bool {
	value := strings.ToLower(strings.TrimSpace(os.Getenv(name)))
	if value == "" {
		return fallback
	}
	return value == "1" || value == "true" || value == "yes" || value == "on"
}

func seconds(name string, fallback, minValue, maxValue time.Duration) time.Duration {
	fallbackSeconds := int(fallback / time.Second)
	value := time.Duration(integer(name, fallbackSeconds,
		int(minValue/time.Second), int(maxValue/time.Second))) * time.Second
	return value
}
