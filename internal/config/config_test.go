package config

import (
	"encoding/base64"
	"testing"
	"time"
)

func TestLoadRequiresProductionSecrets(t *testing.T) {
	t.Setenv("MYSQL_ADDRESS", "127.0.0.1:3306")
	t.Setenv("MYSQL_USERNAME", "root")
	t.Setenv("MYSQL_PASSWORD", "secret")
	t.Setenv("ADMIN_PASSWORD", "admin-secret")
	t.Setenv("SESSION_KEY", base64.StdEncoding.EncodeToString(make([]byte, 32)))

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}
	if cfg.MySQLDatabase != "flask_demo" || cfg.Address != ":80" {
		t.Fatalf("unexpected config: %+v", cfg)
	}
	if cfg.CredentialTrustTTL != 24*time.Hour || cfg.PersistentSessionTTL != 30*24*time.Hour {
		t.Fatalf("unexpected credential TTLs: trust=%s persistent=%s", cfg.CredentialTrustTTL, cfg.PersistentSessionTTL)
	}
	if cfg.TrustedProxyHops != 1 {
		t.Fatalf("TrustedProxyHops = %d", cfg.TrustedProxyHops)
	}
	if cfg.MigrationsAuto {
		t.Fatal("MigrationsAuto should default to false")
	}
	if cfg.CaptchaOCRModelPath != "common.onnx" || cfg.CaptchaOCRRuntimePath != "" {
		t.Fatalf("unexpected captcha OCR config: %+v", cfg)
	}
}

func TestLoadCredentialTTLOverrides(t *testing.T) {
	t.Setenv("MYSQL_ADDRESS", "127.0.0.1:3306")
	t.Setenv("MYSQL_USERNAME", "root")
	t.Setenv("MYSQL_PASSWORD", "secret")
	t.Setenv("ADMIN_PASSWORD", "admin-secret")
	t.Setenv("SESSION_KEY", base64.StdEncoding.EncodeToString(make([]byte, 32)))
	t.Setenv("CREDENTIAL_TRUST_TTL", "7200")
	t.Setenv("SSO_SESSION_MAX_AGE", "86400")
	t.Setenv("TRUSTED_PROXY_HOPS", "2")
	t.Setenv("MIGRATIONS_AUTO", "1")
	t.Setenv("CAPTCHA_OCR_MODEL_PATH", "/models/common.onnx")
	t.Setenv("ONNXRUNTIME_SHARED_LIBRARY_PATH", "/opt/libonnxruntime.so")

	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.CredentialTrustTTL != 2*time.Hour || cfg.PersistentSessionTTL != 24*time.Hour {
		t.Fatalf("unexpected overrides: trust=%s persistent=%s", cfg.CredentialTrustTTL, cfg.PersistentSessionTTL)
	}
	if cfg.TrustedProxyHops != 2 {
		t.Fatalf("TrustedProxyHops = %d", cfg.TrustedProxyHops)
	}
	if !cfg.MigrationsAuto {
		t.Fatal("MigrationsAuto override was ignored")
	}
	if cfg.CaptchaOCRModelPath != "/models/common.onnx" || cfg.CaptchaOCRRuntimePath != "/opt/libonnxruntime.so" {
		t.Fatalf("unexpected captcha OCR config: %+v", cfg)
	}
}

func TestLoadRejectsInvalidSessionKey(t *testing.T) {
	t.Setenv("MYSQL_ADDRESS", "127.0.0.1:3306")
	t.Setenv("MYSQL_USERNAME", "root")
	t.Setenv("MYSQL_PASSWORD", "secret")
	t.Setenv("ADMIN_PASSWORD", "admin-secret")
	t.Setenv("SESSION_KEY", "not-base64")

	if _, err := Load(); err == nil {
		t.Fatal("Load() should reject invalid SESSION_KEY")
	}
}
