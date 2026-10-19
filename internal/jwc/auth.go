package jwc

import (
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const randomAlphabet = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"

func randomString(length int) (string, error) {
	raw := make([]byte, length)
	if _, err := io.ReadFull(rand.Reader, raw); err != nil {
		return "", err
	}
	for i := range raw {
		raw[i] = randomAlphabet[int(raw[i])%len(randomAlphabet)]
	}
	return string(raw), nil
}

func encryptPassword(password, salt string) (string, error) {
	prefix, err := randomString(64)
	if err != nil {
		return "", err
	}
	iv, err := randomString(aes.BlockSize)
	if err != nil {
		return "", err
	}
	key := make([]byte, aes.BlockSize)
	copy(key, []byte(salt))
	block, err := aes.NewCipher(key)
	if err != nil {
		return "", err
	}
	plain := []byte(prefix + password)
	padding := aes.BlockSize - len(plain)%aes.BlockSize
	plain = append(plain, bytesRepeat(byte(padding), padding)...)
	encrypted := make([]byte, len(plain))
	cipher.NewCBCEncrypter(block, []byte(iv)).CryptBlocks(encrypted, plain)
	return base64.StdEncoding.EncodeToString(encrypted), nil
}

func bytesRepeat(value byte, count int) []byte {
	out := make([]byte, count)
	for i := range out {
		out[i] = value
	}
	return out
}

func (c *Client) Login(ctx context.Context, studentID, password string) error {
	c.StudentID = strings.TrimSpace(studentID)
	c.LastError = ""
	resp, err := c.request(ctx, http.MethodGet, SSOLoginURL, nil)
	if err != nil {
		return fmt.Errorf("无法连接智慧理工统一认证: %w", err)
	}
	raw, err := readResponse(resp)
	if err != nil {
		return err
	}
	if !strings.Contains(resp.Request.URL.String(), "authserver/login") {
		return c.finishAccountSSO(ctx, "sso")
	}
	doc, err := parseDocument(raw)
	if err != nil {
		return err
	}
	form := doc.Find("form#pwdFromId").First()
	if form.Length() == 0 {
		return fmt.Errorf("未找到智慧理工登录表单")
	}
	loginForm := parseForm(form)
	if err := validatePostForm(loginForm); err != nil {
		return err
	}
	execution := formField(form, loginForm.Values, "execution")
	salt := formField(form, loginForm.Values, "pwdEncryptSalt")
	if salt == "" {
		// 2026-07 SSO 改版后盐值位于登录表单外，但与用户名密码表单同页。
		saltNode := doc.Find("#pwdEncryptSalt").First()
		if saltNode.Length() > 0 {
			salt, _ = saltNode.Attr("value")
			salt = strings.TrimSpace(salt)
		}
	}
	lt := formField(form, loginForm.Values, "lt")
	if execution == "" || salt == "" {
		return fmt.Errorf("智慧理工登录表单缺少 execution/pwdEncryptSalt")
	}
	check := url.Values{"username": {c.StudentID}}
	checkResp, checkErr := c.request(ctx, http.MethodPost, SSOBase+"/authserver/checkNeedCaptcha.htl", check)
	captchaRequired := false
	if checkErr == nil {
		checkRaw, readErr := readResponse(checkResp)
		if readErr != nil {
			return fmt.Errorf("读取验证码检查结果: %w", readErr)
		}
		var result struct {
			IsNeed bool `json:"isNeed"`
		}
		if json.Unmarshal(checkRaw, &result) == nil {
			captchaRequired = result.IsNeed
		} else {
			// Keep compatibility with the previous plain-text response.
			captchaRequired = strings.Contains(strings.ToLower(string(checkRaw)), "true")
		}
	}
	if captchaRequired && c.captchaSolver == nil {
		return ErrCaptchaRequired
	}
	encrypted, err := encryptPassword(password, salt)
	if err != nil {
		return err
	}
	postURL, err := resolveFormURL(resp.Request.URL.String(), loginForm.Action)
	if err != nil {
		return err
	}
	if service := resp.Request.URL.Query().Get("service"); service != "" {
		u, parseErr := url.Parse(postURL)
		if parseErr != nil {
			return fmt.Errorf("智慧理工登录地址无效: %w", parseErr)
		}
		q := u.Query()
		if q.Get("service") == "" {
			q.Set("service", service)
			u.RawQuery = q.Encode()
			postURL = u.String()
		}
	}
	values := loginForm.Values
	for key, value := range map[string]string{
		"username": c.StudentID, "passwordText": password, "password": encrypted,
		"captcha": "", "rememberMe": "true", "_eventId": "submit",
		"cllt": "userNameLogin", "dllt": "generalLogin", "lt": lt, "execution": execution,
	} {
		values.Set(key, value)
	}
	attempts := 1
	for attempt := 0; attempt < attempts; attempt++ {
		if captchaRequired {
			captchaText, solveErr := c.solveCaptcha(ctx)
			if solveErr != nil {
				return solveErr
			}
			values.Set("captcha", captchaText)
		}
		loginResp, requestErr := c.request(ctx, http.MethodPost, postURL, values)
		if requestErr != nil {
			return requestErr
		}
		loginRaw, readErr := readResponse(loginResp)
		if readErr != nil {
			return readErr
		}
		loginDoc, parseErr := parseDocument(loginRaw)
		if parseErr != nil {
			return fmt.Errorf("解析智慧理工登录结果: %w", parseErr)
		}
		tip := strings.TrimSpace(loginDoc.Find("#showErrorTip").Text())
		if tip != "" {
			if strings.Contains(tip, "验证码") {
				if c.captchaSolver != nil && attempt+1 < 2 {
					captchaRequired = true
					attempts = 2
					continue
				}
				return ErrCaptchaRequired
			}
			return fmt.Errorf("智慧理工登录失败: %s", tip)
		}
		if loginResp.StatusCode == http.StatusUnauthorized {
			return fmt.Errorf("智慧理工账号或密码错误")
		}
		hasTicket := false
		for _, cookie := range c.Cookies() {
			if strings.Contains(cookie.Name, "CASTGC") {
				hasTicket = true
				break
			}
		}
		if !hasTicket {
			if strings.Contains(loginResp.Request.URL.String(), "error.njust.edu.cn") ||
				strings.Contains(string(loginRaw), "出错啦") {
				return fmt.Errorf("智慧理工登录被拒绝，请改用二维码登录")
			}
			return fmt.Errorf("智慧理工未建立有效会话")
		}
		return c.finishAccountSSO(ctx, "sso")
	}
	return ErrCaptchaRequired
}

func (c *Client) solveCaptcha(ctx context.Context) (string, error) {
	if c.captchaSolver == nil {
		return "", ErrCaptchaRequired
	}
	var lastErr error
	for attempt := 0; attempt < 2; attempt++ {
		captchaURL := fmt.Sprintf("%s/authserver/getCaptcha.htl?ts=%d", SSOBase, time.Now().UnixNano())
		resp, err := c.request(ctx, http.MethodGet, captchaURL, nil)
		if err != nil {
			lastErr = err
			continue
		}
		raw, err := readResponse(resp)
		if err != nil {
			lastErr = err
			continue
		}
		if resp.StatusCode < http.StatusOK || resp.StatusCode >= http.StatusMultipleChoices {
			lastErr = fmt.Errorf("验证码接口返回 HTTP %d", resp.StatusCode)
			continue
		}
		text, err := c.captchaSolver.Solve(ctx, raw)
		if err != nil {
			lastErr = err
			continue
		}
		text = strings.TrimSpace(text)
		if text != "" {
			return text, nil
		}
		lastErr = fmt.Errorf("验证码识别结果为空")
	}
	return "", fmt.Errorf("%w: %v", ErrCaptchaRequired, lastErr)
}

func (c *Client) finishAccountSSO(ctx context.Context, method string) error {
	if strings.HasPrefix(c.StudentID, "1") {
		return c.finishGraduateSSO(ctx, method)
	}
	return c.finishSSO(ctx, method)
}

func (c *Client) finishSSO(ctx context.Context, method string) error {
	resp, err := c.request(ctx, http.MethodGet, JWSSOEntry, nil)
	if err != nil {
		return fmt.Errorf("访问教务 SSO 入口: %w", err)
	}
	raw, err := readResponse(resp)
	if err != nil {
		return err
	}
	if resp.StatusCode != http.StatusOK || c.isLoginPage(resp, raw) {
		return fmt.Errorf("智慧理工已登录，但未能建立教务会话")
	}
	text := string(raw)
	if strings.Contains(resp.Request.URL.String(), "error.njust.edu.cn") || strings.Contains(text, "出错啦") {
		return fmt.Errorf("教务 SSO 返回错误页")
	}
	c.extractIdentity(text)
	c.LoginMethod = method
	c.AccountType = "undergraduate"
	return nil
}

func (c *Client) Resume(ctx context.Context, studentID string) error {
	c.StudentID = studentID
	if strings.HasPrefix(studentID, "1") {
		c.AccountType = "graduate"
		if err := c.validateGraduate(ctx); err != nil {
			if err = c.finishGraduateSSO(ctx, "sso-cached"); err != nil {
				return err
			}
		}
		c.LoginMethod = "sso-cached"
		return nil
	}
	if err := c.Validate(ctx); err != nil {
		resp, e := c.request(ctx, http.MethodGet, JWSSOEntry, nil)
		if e != nil {
			return err
		}
		raw, e := readResponse(resp)
		if e != nil || c.isLoginPage(resp, raw) {
			return err
		}
		c.extractIdentity(string(raw))
	}
	c.LoginMethod = "sso-cached"
	c.AccountType = "undergraduate"
	return nil
}
