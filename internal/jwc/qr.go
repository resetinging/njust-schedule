package jwc

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
	"strings"
)

func (c *Client) StartQR(ctx context.Context) ([]byte, error) {
	resp, err := c.request(ctx, http.MethodGet, SSOLoginURL, nil)
	if err != nil {
		return nil, err
	}
	raw, err := readResponse(resp)
	if err != nil {
		return nil, err
	}
	doc, err := parseDocument(raw)
	if err != nil {
		return nil, err
	}
	form := doc.Find("form#qrLoginForm").First()
	if form.Length() == 0 {
		form = doc.Find("form#pwdFromId").First()
	}
	if form.Length() == 0 {
		return nil, fmt.Errorf("未找到智慧理工二维码登录表单")
	}
	qrForm := parseForm(form)
	if err := validatePostForm(qrForm); err != nil {
		return nil, err
	}
	c.qrValues = qrForm.Values
	c.qrLT = formField(form, qrForm.Values, "lt")
	c.qrExecution = formField(form, qrForm.Values, "execution")
	if c.qrExecution == "" {
		c.qrExecution = "e1s1"
	}
	c.qrLoginURL = resp.Request.URL.String()
	tokenResp, err := c.request(ctx, http.MethodPost, SSOBase+"/authserver/qrCode/getToken", url.Values{"uuid": {""}})
	if err != nil {
		return nil, err
	}
	tokenRaw, err := readResponse(tokenResp)
	if err != nil {
		return nil, err
	}
	c.qrToken = strings.TrimSpace(string(tokenRaw))
	if c.qrToken == "" {
		return nil, fmt.Errorf("智慧理工未返回二维码 token")
	}
	imageResp, err := c.request(ctx, http.MethodGet, SSOBase+"/authserver/qrCode/getCode?uuid="+url.QueryEscape(c.qrToken), nil)
	if err != nil {
		return nil, err
	}
	image, err := readResponse(imageResp)
	if err != nil {
		return nil, err
	}
	if !strings.HasPrefix(strings.ToLower(imageResp.Header.Get("Content-Type")), "image/") || len(image) < 200 {
		return nil, fmt.Errorf("智慧理工未返回有效二维码图片")
	}
	c.qrImage = image
	return image, nil
}

func (c *Client) PollQR(ctx context.Context) (string, error) {
	if c.qrToken == "" {
		return "-1", fmt.Errorf("二维码会话不存在")
	}
	resp, err := c.request(ctx, http.MethodPost, SSOBase+"/authserver/qrCode/getStatus.htl", url.Values{"uuid": {c.qrToken}})
	if err != nil {
		return "-1", err
	}
	raw, err := readResponse(resp)
	return strings.TrimSpace(string(raw)), err
}

func (c *Client) FinishQR(ctx context.Context) error {
	loginURL := SSOBase + "/authserver/login?display=qrLogin"
	if u, err := url.Parse(c.qrLoginURL); err == nil {
		if service := u.Query().Get("service"); service != "" {
			loginURL += "&service=" + url.QueryEscape(service)
		}
	}
	values := url.Values{}
	for key, items := range c.qrValues {
		values[key] = append([]string(nil), items...)
	}
	for key, value := range map[string]string{"uuid": c.qrToken, "lt": c.qrLT, "cllt": "qrLogin", "dllt": "generalLogin", "execution": c.qrExecution, "_eventId": "submit", "rmShown": "1"} {
		values.Set(key, value)
	}
	resp, err := c.request(ctx, http.MethodPost, loginURL, values)
	if err != nil {
		return err
	}
	raw, err := readResponse(resp)
	if err != nil {
		return fmt.Errorf("读取二维码登录结果: %w", err)
	}
	if resp.StatusCode >= http.StatusBadRequest || c.isLoginPage(resp, raw) {
		return fmt.Errorf("智慧理工未接受二维码登录")
	}
	if err = c.identifyEHall(ctx); err != nil {
		return fmt.Errorf("识别扫码用户: %w", err)
	}
	if strings.HasPrefix(c.StudentID, "1") {
		if err := c.finishGraduateSSO(ctx, "sso-qr"); err != nil {
			return err
		}
	} else if err := c.finishSSO(ctx, "sso-qr"); err != nil {
		return err
	}
	if c.StudentID == "" {
		resp, err := c.request(ctx, http.MethodGet, mainURL, nil)
		if err != nil {
			return fmt.Errorf("读取教务用户信息: %w", err)
		}
		raw, err := readResponse(resp)
		if err != nil {
			return fmt.Errorf("读取教务用户信息: %w", err)
		}
		c.extractIdentity(string(raw))
	}
	if c.StudentID == "" {
		return fmt.Errorf("扫码成功但未能识别学号")
	}
	return nil
}

func (c *Client) QRImage() []byte { return append([]byte(nil), c.qrImage...) }
