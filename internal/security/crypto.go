package security

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strconv"
	"strings"
	"time"
)

const (
	keyVersion = byte(1)
	ivLength   = 12
)

type Crypto struct{ key []byte }

func New(key []byte) (*Crypto, error) {
	if len(key) != 32 {
		return nil, errors.New("AES-GCM 密钥必须为 32 字节")
	}
	copyKey := append([]byte(nil), key...)
	return &Crypto{key: copyKey}, nil
}

// Encrypt reproduces Python cookie_crypto.encrypt: base64(version|nonce|ciphertext|tag).
func (c *Crypto) Encrypt(aad string, value any) (string, error) {
	plain, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	block, err := aes.NewCipher(c.key)
	if err != nil {
		return "", err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", err
	}
	nonce := make([]byte, ivLength)
	if _, err = io.ReadFull(rand.Reader, nonce); err != nil {
		return "", err
	}
	sealed := gcm.Seal(nil, nonce, plain, []byte(aad))
	result := make([]byte, 1+len(nonce)+len(sealed))
	result[0] = keyVersion
	copy(result[1:], nonce)
	copy(result[1+len(nonce):], sealed)
	return base64.StdEncoding.EncodeToString(result), nil
}

func (c *Crypto) Decrypt(aad, token string, value any) error {
	raw, err := base64.StdEncoding.DecodeString(token)
	if err != nil || len(raw) < 1+ivLength+16 || raw[0] != keyVersion {
		return errors.New("无效密文")
	}
	block, err := aes.NewCipher(c.key)
	if err != nil {
		return err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return err
	}
	plain, err := gcm.Open(nil, raw[1:1+ivLength], raw[1+ivLength:], []byte(aad))
	if err != nil {
		return errors.New("密文校验失败")
	}
	return json.Unmarshal(plain, value)
}

func (c *Crypto) DeleteToken(studentID string, ttl time.Duration) string {
	exp := time.Now().Add(ttl).Unix()
	payload := []byte(studentID + "|" + strconv.FormatInt(exp, 10))
	body := base64.RawURLEncoding.EncodeToString(payload)
	derived := sha256.Sum256(append([]byte("credential-delete-v1|"), c.key...))
	mac := hmac.New(sha256.New, derived[:])
	_, _ = mac.Write(payload)
	return body + "." + hex.EncodeToString(mac.Sum(nil))
}

func (c *Crypto) VerifyDeleteToken(token string) string {
	parts := strings.Split(token, ".")
	if len(parts) != 2 {
		return ""
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return ""
	}
	derived := sha256.Sum256(append([]byte("credential-delete-v1|"), c.key...))
	mac := hmac.New(sha256.New, derived[:])
	_, _ = mac.Write(payload)
	provided, err := hex.DecodeString(parts[1])
	if err != nil || !hmac.Equal(provided, mac.Sum(nil)) {
		return ""
	}
	text := string(payload)
	index := strings.LastIndexByte(text, '|')
	if index <= 0 {
		return ""
	}
	exp, err := strconv.ParseInt(text[index+1:], 10, 64)
	if err != nil || exp < time.Now().Unix() {
		return ""
	}
	return text[:index]
}

func NewOpaqueToken() (string, error) {
	raw := make([]byte, 32)
	if _, err := io.ReadFull(rand.Reader, raw); err != nil {
		return "", fmt.Errorf("生成 token: %w", err)
	}
	return base64.RawURLEncoding.EncodeToString(raw), nil
}
