package jwc

import (
	"context"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"testing"
)

type stubCaptchaSolver struct {
	mu      sync.Mutex
	results []string
	calls   int
	images  [][]byte
}

func (s *stubCaptchaSolver) Solve(_ context.Context, image []byte) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calls++
	s.images = append(s.images, append([]byte(nil), image...))
	if len(s.results) == 0 {
		return "", io.ErrUnexpectedEOF
	}
	value := s.results[0]
	s.results = s.results[1:]
	return value, nil
}

func TestLoginSolvesCaptchaAndContinuesSSO(t *testing.T) {
	loginPage := `<form id="pwdFromId" action="/authserver/login" method="post" enctype="application/x-www-form-urlencoded">
<input id="execution" name="execution" value="e1s1"><input id="lt" name="lt" value="LT-1"></form>
<input id="pwdEncryptSalt" value="1234567890123456">`
	solver := &stubCaptchaSolver{results: []string{"Ab12"}}
	client := New(nil)
	client.SetCaptchaSolver(solver)
	var posted url.Values
	client.HTTP.Transport = roundTripFunc(func(request *http.Request) (*http.Response, error) {
		switch {
		case request.URL.Host == "bkjw.njust.edu.cn" && request.URL.Path == "/njlgdx/indexsso.jsp":
			return response(request, http.StatusOK, io.NopCloser(strings.NewReader(`<div>张三，同学</div>`))), nil
		case strings.Contains(request.URL.Path, "checkNeedCaptcha"):
			return response(request, http.StatusOK, io.NopCloser(strings.NewReader(`{"isNeed":true}`))), nil
		case strings.Contains(request.URL.Path, "getCaptcha"):
			return response(request, http.StatusOK, io.NopCloser(strings.NewReader("jpeg-data"))), nil
		case request.Method == http.MethodPost && request.URL.Path == "/authserver/login":
			raw, _ := io.ReadAll(request.Body)
			posted, _ = url.ParseQuery(string(raw))
			resp := response(request, http.StatusOK, io.NopCloser(strings.NewReader(`<html>ok</html>`)))
			resp.Header.Set("Set-Cookie", "CASTGC=TGT-1; Path=/authserver; Domain=ids.njust.edu.cn")
			return resp, nil
		default:
			return response(request, http.StatusOK, io.NopCloser(strings.NewReader(loginPage))), nil
		}
	})

	if err := client.Login(t.Context(), "924101960000", "password"); err != nil {
		t.Fatal(err)
	}
	if solver.calls != 1 {
		t.Fatalf("OCR calls = %d, want 1", solver.calls)
	}
	if got := posted.Get("captcha"); got != "Ab12" {
		t.Fatalf("posted captcha = %q, want %q", got, "Ab12")
	}
	if client.LoginMethod != "sso" {
		t.Fatalf("LoginMethod = %q", client.LoginMethod)
	}
}

func TestLoginRefreshesCaptchaAfterWrongCode(t *testing.T) {
	loginPage := `<form id="pwdFromId" action="/authserver/login" method="post" enctype="application/x-www-form-urlencoded">
<input id="execution" name="execution" value="e1s1"><input id="lt" name="lt" value="LT-1"></form>
<input id="pwdEncryptSalt" value="1234567890123456">`
	solver := &stubCaptchaSolver{results: []string{"bad1", "good"}}
	client := New(nil)
	client.SetCaptchaSolver(solver)
	loginPosts := 0
	captchaImages := 0
	client.HTTP.Transport = roundTripFunc(func(request *http.Request) (*http.Response, error) {
		switch {
		case request.URL.Host == "bkjw.njust.edu.cn" && request.URL.Path == "/njlgdx/indexsso.jsp":
			return response(request, http.StatusOK, io.NopCloser(strings.NewReader(`<div>张三，同学</div>`))), nil
		case strings.Contains(request.URL.Path, "checkNeedCaptcha"):
			return response(request, http.StatusOK, io.NopCloser(strings.NewReader(`{"isNeed":true}`))), nil
		case strings.Contains(request.URL.Path, "getCaptcha"):
			captchaImages++
			return response(request, http.StatusOK, io.NopCloser(strings.NewReader("jpeg-data"))), nil
		case request.Method == http.MethodPost && request.URL.Path == "/authserver/login":
			loginPosts++
			if loginPosts == 1 {
				return response(request, http.StatusOK, io.NopCloser(strings.NewReader(`<span id="showErrorTip">验证码错误</span>`))), nil
			}
			resp := response(request, http.StatusOK, io.NopCloser(strings.NewReader(`<html>ok</html>`)))
			resp.Header.Set("Set-Cookie", "CASTGC=TGT-1; Path=/authserver; Domain=ids.njust.edu.cn")
			return resp, nil
		default:
			return response(request, http.StatusOK, io.NopCloser(strings.NewReader(loginPage))), nil
		}
	})

	if err := client.Login(t.Context(), "924101960000", "password"); err != nil {
		t.Fatal(err)
	}
	if solver.calls != 2 || captchaImages != 2 || loginPosts != 2 {
		t.Fatalf("calls: OCR=%d images=%d posts=%d", solver.calls, captchaImages, loginPosts)
	}
}

func TestLoginSolvesCaptchaWhenCheckEndpointMissesIt(t *testing.T) {
	loginPage := `<form id="pwdFromId" action="/authserver/login" method="post" enctype="application/x-www-form-urlencoded">
<input id="execution" name="execution" value="e1s1"><input id="lt" name="lt" value="LT-1"></form>
<input id="pwdEncryptSalt" value="1234567890123456">`
	solver := &stubCaptchaSolver{results: []string{"Ab12"}}
	client := New(nil)
	client.SetCaptchaSolver(solver)
	loginPosts := 0
	client.HTTP.Transport = roundTripFunc(func(request *http.Request) (*http.Response, error) {
		switch {
		case request.URL.Host == "bkjw.njust.edu.cn" && request.URL.Path == "/njlgdx/indexsso.jsp":
			return response(request, http.StatusOK, io.NopCloser(strings.NewReader(`<div>张三，同学</div>`))), nil
		case strings.Contains(request.URL.Path, "checkNeedCaptcha"):
			return response(request, http.StatusOK, io.NopCloser(strings.NewReader(`{"isNeed":false}`))), nil
		case strings.Contains(request.URL.Path, "getCaptcha"):
			return response(request, http.StatusOK, io.NopCloser(strings.NewReader("jpeg-data"))), nil
		case request.Method == http.MethodPost && request.URL.Path == "/authserver/login":
			loginPosts++
			if loginPosts == 1 {
				return response(request, http.StatusOK, io.NopCloser(strings.NewReader(`<span id="showErrorTip">请输入验证码</span>`))), nil
			}
			resp := response(request, http.StatusOK, io.NopCloser(strings.NewReader(`<html>ok</html>`)))
			resp.Header.Set("Set-Cookie", "CASTGC=TGT-1; Path=/authserver; Domain=ids.njust.edu.cn")
			return resp, nil
		default:
			return response(request, http.StatusOK, io.NopCloser(strings.NewReader(loginPage))), nil
		}
	})

	if err := client.Login(t.Context(), "924101960000", "password"); err != nil {
		t.Fatal(err)
	}
	if solver.calls != 1 || loginPosts != 2 {
		t.Fatalf("OCR=%d posts=%d", solver.calls, loginPosts)
	}
}

func TestResumeNeverInvokesCaptchaSolver(t *testing.T) {
	solver := &stubCaptchaSolver{results: []string{"unused"}}
	client := New(nil)
	client.SetCaptchaSolver(solver)
	client.HTTP.Transport = roundTripFunc(func(request *http.Request) (*http.Response, error) {
		return response(request, http.StatusOK, io.NopCloser(strings.NewReader(`<div>张三，同学</div>`))), nil
	})

	if err := client.Resume(t.Context(), "924101960000"); err != nil {
		t.Fatal(err)
	}
	if solver.calls != 0 {
		t.Fatalf("OCR calls = %d, want 0", solver.calls)
	}
}
