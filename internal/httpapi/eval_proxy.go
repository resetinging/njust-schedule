package httpapi

import (
	"bytes"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"
	"net/url"
	"strings"

	"github.com/naughtygopher/webgo/v7"
	"github.com/resetinging/njust-schedule/internal/jwc"
	"github.com/resetinging/njust-schedule/internal/session"
)

func (s *Server) evalPage(r *http.Request, sess *session.Session, rawPath string) (jwc.ProxyResponse, error) {
	var result jwc.ProxyResponse
	err := s.withSessionJWC(r.Context(), sess, func() error {
		var err error
		result, err = sess.JWC.Proxy(r.Context(), http.MethodGet, rawPath, "", nil, "")
		return err
	})
	return result, err
}

func (s *Server) evalCourses(w http.ResponseWriter, r *http.Request) {
	rawPath := strings.TrimSpace(r.URL.Query().Get("url"))
	if rawPath == "" {
		writeError(w, http.StatusBadRequest, "缺少 URL")
		return
	}
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	result, err := s.evalPage(r, sess, rawPath)
	if err != nil {
		s.writeEvalError(w, err, "课程页请求失败")
		return
	}
	title, courses, hidden, err := jwc.ParseEvalCourses(result.Body)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "batch_title": title, "courses": courses, "hidden_fields": hidden})
}

func (s *Server) evalForm(w http.ResponseWriter, r *http.Request) {
	rawPath := strings.TrimSpace(r.URL.Query().Get("url"))
	if rawPath == "" {
		writeError(w, http.StatusBadRequest, "缺少评教 URL")
		return
	}
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	result, err := s.evalPage(r, sess, rawPath)
	if err != nil {
		s.writeEvalError(w, err, "表单请求失败")
		return
	}
	name, hidden, indicators, action, err := jwc.ParseEvalForm(result.Body)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "course_name": name, "hidden_fields": hidden, "indicators": indicators, "action": action})
}

func (s *Server) submitEval(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	var body struct {
		FormData   map[string]any `json:"form_data"`
		SubmitType string         `json:"submit_type"`
		Action     string         `json:"action"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if body.FormData == nil {
		writeError(w, http.StatusBadRequest, "缺少评教表单")
		return
	}
	if body.SubmitType == "" {
		body.SubmitType = "0"
	}
	if body.Action == "" {
		body.Action = "/njlgdx/xspj/xspj_save.do"
	}
	encoded := jwc.OrderedEvalForm(body.FormData, body.SubmitType)
	var result jwc.ProxyResponse
	err := s.withSessionJWC(r.Context(), sess, func() error {
		var err error
		result, err = sess.JWC.Proxy(r.Context(), http.MethodPost, body.Action, "", strings.NewReader(encoded), "application/x-www-form-urlencoded")
		return err
	})
	if err != nil {
		s.writeEvalError(w, err, "提交失败，请稍后重试")
		return
	}
	message := "已提交（请返回教务确认）"
	text := string(result.Body)
	if strings.Contains(text, "评价成功") || strings.Contains(text, "提交成功") || strings.Contains(text, "保存成功") {
		message = "评教提交成功！"
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "message": message})
}

func (s *Server) jwProxy(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	var body struct {
		Method string         `json:"method"`
		Path   string         `json:"path"`
		Query  string         `json:"query"`
		Data   map[string]any `json:"data"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	body.Method = strings.ToUpper(strings.TrimSpace(body.Method))
	if body.Method == "" {
		body.Method = http.MethodGet
	}
	if body.Path == "" {
		writeError(w, http.StatusBadRequest, "缺少 path")
		return
	}
	if body.Method != http.MethodGet && body.Method != http.MethodPost {
		writeError(w, http.StatusBadRequest, "method 仅支持 GET/POST")
		return
	}
	var reader io.Reader
	contentType := ""
	if body.Method == http.MethodPost {
		values := url.Values{}
		for key, value := range body.Data {
			values.Set(key, fmt.Sprint(value))
		}
		reader = strings.NewReader(values.Encode())
		contentType = "application/x-www-form-urlencoded"
	}
	var result jwc.ProxyResponse
	err := s.withSessionJWC(r.Context(), sess, func() error {
		var err error
		result, err = sess.JWC.Proxy(r.Context(), body.Method, body.Path, body.Query, reader, contentType)
		return err
	})
	if err != nil {
		s.writeEvalError(w, err, "教务请求失败，请稍后重试")
		return
	}
	payload := map[string]any{"success": true, "status": result.Status, "content_type": result.ContentType}
	mediaType, _, _ := mime.ParseMediaType(result.ContentType)
	if strings.HasPrefix(mediaType, "text/") || mediaType == "application/json" || mediaType == "application/javascript" || mediaType == "" {
		payload["text"] = string(result.Body)
	} else {
		payload["data_b64"] = base64.StdEncoding.EncodeToString(result.Body)
	}
	writeJSON(w, http.StatusOK, payload)
}

func (s *Server) jwBrowserProxy(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	target := "/njlgdx/" + strings.TrimLeft(webgo.Context(r).Params()["target_path"], "/")
	var reader io.Reader
	contentType := ""
	if r.Method == http.MethodPost {
		r.Body = http.MaxBytesReader(w, r.Body, 2<<20)
		if err := r.ParseForm(); err != nil {
			http.Error(w, "表单格式错误", http.StatusBadRequest)
			return
		}
		reader = strings.NewReader(r.PostForm.Encode())
		contentType = "application/x-www-form-urlencoded"
	}
	var result jwc.ProxyResponse
	err := s.withSessionJWC(r.Context(), sess, func() error {
		var err error
		result, err = sess.JWC.Proxy(r.Context(), r.Method, target, r.URL.RawQuery, reader, contentType)
		return err
	})
	if err != nil {
		var statusErr *jwc.HTTPStatusError
		if errors.As(err, &statusErr) {
			http.Error(w, statusErr.Message, statusErr.Status)
			return
		}
		http.Error(w, "教务请求失败，请稍后重试", http.StatusBadGateway)
		return
	}
	w.Header().Set("Content-Security-Policy", "sandbox allow-forms; script-src 'none'; object-src 'none'; base-uri 'none'")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Referrer-Policy", "no-referrer")
	w.Header().Set("Content-Type", result.ContentType)
	w.WriteHeader(result.Status)
	data := result.Body
	if strings.Contains(strings.ToLower(result.ContentType), "text/html") {
		for _, pair := range [][2][]byte{
			{[]byte(`src="/njlgdx/`), []byte(`src="/proxy/jw/`)}, {[]byte(`href="/njlgdx/`), []byte(`href="/proxy/jw/`)}, {[]byte(`action="/njlgdx/`), []byte(`action="/proxy/jw/`)},
			{[]byte(`src='/njlgdx/`), []byte(`src='/proxy/jw/`)}, {[]byte(`href='/njlgdx/`), []byte(`href='/proxy/jw/`)}, {[]byte(`action='/njlgdx/`), []byte(`action='/proxy/jw/`)},
		} {
			data = bytes.ReplaceAll(data, pair[0], pair[1])
		}
	}
	_, _ = w.Write(data)
}

func (s *Server) writeEvalError(w http.ResponseWriter, err error, fallback string) {
	var statusErr *jwc.HTTPStatusError
	if errors.As(err, &statusErr) {
		writeError(w, statusErr.Status, statusErr.Message)
		return
	}
	if _, pathErr := jwc.SafeJWPath(err.Error()); pathErr == nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	for _, marker := range []string{"只允许", "路径穿越", "非法教务路径", "查询参数格式错误"} {
		if strings.Contains(err.Error(), marker) {
			writeError(w, http.StatusBadRequest, err.Error())
			return
		}
	}
	mapJWCError(w, err, fallback)
}
