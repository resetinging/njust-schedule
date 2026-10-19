package jwc

import (
	"errors"
	"io"
	"net/http"
	"net/url"
	"strings"
	"testing"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (fn roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) { return fn(request) }

type failingBody struct{}

func (failingBody) Read([]byte) (int, error) { return 0, errors.New("read failed") }
func (failingBody) Close() error             { return nil }

func response(request *http.Request, status int, body io.ReadCloser) *http.Response {
	return &http.Response{StatusCode: status, Header: http.Header{}, Body: body, Request: request}
}

func TestLoginPropagatesCaptchaCheckReadFailure(t *testing.T) {
	loginPage := `<form id="pwdFromId" action="/authserver/login" method="post" enctype="application/x-www-form-urlencoded">
<input id="execution" name="execution" value="e1s1"><input id="lt" name="lt" value="LT-1"></form>
<input id="pwdEncryptSalt" value="1234567890123456">`
	client := New(nil)
	client.HTTP.Transport = roundTripFunc(func(request *http.Request) (*http.Response, error) {
		if strings.Contains(request.URL.Path, "checkNeedCaptcha") {
			return response(request, http.StatusOK, failingBody{}), nil
		}
		return response(request, http.StatusOK, io.NopCloser(strings.NewReader(loginPage))), nil
	})
	err := client.Login(t.Context(), "924101960000", "password")
	if err == nil || !strings.Contains(err.Error(), "读取验证码检查结果") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestLoginReadsPasswordSaltOutsideFormAndDetectsCaptcha(t *testing.T) {
	loginPage := `<form id="pwdFromId" action="/authserver/login" method="post" enctype="application/x-www-form-urlencoded">
<input id="execution" name="execution" value="e1s1"><input id="lt" name="lt" value=""></form>
<input id="pwdEncryptSalt" value="1234567890123456">`
	client := New(nil)
	client.HTTP.Transport = roundTripFunc(func(request *http.Request) (*http.Response, error) {
		if strings.Contains(request.URL.Path, "checkNeedCaptcha") {
			return response(request, http.StatusOK, io.NopCloser(strings.NewReader(`{"isNeed":true}`))), nil
		}
		return response(request, http.StatusOK, io.NopCloser(strings.NewReader(loginPage))), nil
	})
	err := client.Login(t.Context(), "924101960000", "password")
	if !errors.Is(err, ErrCaptchaRequired) {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestFinishQRPropagatesIdentityFailure(t *testing.T) {
	client := New(nil)
	client.qrToken = "token"
	client.qrLoginURL = SSOLoginURL
	client.qrValues = url.Values{}
	client.HTTP.Transport = roundTripFunc(func(request *http.Request) (*http.Response, error) {
		if request.URL.Host == "ehall2.njust.edu.cn" && request.URL.Path == "/getLoginUser" {
			return response(request, http.StatusOK, io.NopCloser(strings.NewReader("not-json"))), nil
		}
		finalRequest := request.Clone(request.Context())
		finalRequest.URL, _ = url.Parse("https://ehall2.njust.edu.cn/home")
		return response(finalRequest, http.StatusOK, io.NopCloser(strings.NewReader("ok"))), nil
	})
	err := client.FinishQR(t.Context())
	if err == nil || !strings.Contains(err.Error(), "识别扫码用户") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestFinishQRPropagatesLoginBodyFailure(t *testing.T) {
	client := New(nil)
	client.qrToken = "token"
	client.qrLoginURL = SSOLoginURL
	client.qrValues = url.Values{}
	client.HTTP.Transport = roundTripFunc(func(request *http.Request) (*http.Response, error) {
		return response(request, http.StatusOK, failingBody{}), nil
	})
	err := client.FinishQR(t.Context())
	if err == nil || !strings.Contains(err.Error(), "读取二维码登录结果") {
		t.Fatalf("unexpected error: %v", err)
	}
}
