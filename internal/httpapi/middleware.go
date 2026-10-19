package httpapi

import (
	"compress/gzip"
	"context"
	"crypto/rand"
	"encoding/hex"
	"io"
	"log/slog"
	"net/http"
	"runtime/debug"
	"strconv"
	"strings"
	"time"
)

type contextKey string

const requestIDKey contextKey = "request-id"

type statusWriter struct {
	http.ResponseWriter
	status int
}

func (w *statusWriter) WriteHeader(status int) {
	if w.status != 0 {
		return
	}
	w.status = status
	w.ResponseWriter.WriteHeader(status)
}

func (w *statusWriter) Write(data []byte) (int, error) {
	if w.status == 0 {
		w.WriteHeader(http.StatusOK)
	}
	return w.ResponseWriter.Write(data)
}

const gzipMinSize = 500

type gzipResponseWriter struct {
	http.ResponseWriter
	request     *http.Request
	status      int
	buffer      []byte
	decided     bool
	compressing bool
	zipper      *gzip.Writer
}

func (w *gzipResponseWriter) WriteHeader(status int) {
	if w.status == 0 {
		w.status = status
	}
}

func (w *gzipResponseWriter) Write(data []byte) (int, error) {
	if w.status == 0 {
		w.status = http.StatusOK
	}
	if w.decided {
		if w.compressor() != nil {
			return w.zipper.Write(data)
		}
		return w.ResponseWriter.Write(data)
	}
	w.buffer = append(w.buffer, data...)
	if len(w.buffer) < gzipMinSize {
		return len(data), nil
	}
	if err := w.commit(false); err != nil {
		return 0, err
	}
	return len(data), nil
}

func (w *gzipResponseWriter) compressor() io.Writer {
	if w.compressionAllowed() {
		return w.zipper
	}
	return nil
}

func (w *gzipResponseWriter) compressionAllowed() bool {
	return w.compressing && w.zipper != nil
}

func (w *gzipResponseWriter) commit(force bool) error {
	if w.decided {
		return nil
	}
	w.decided = true
	status := w.status
	if status == 0 {
		status = http.StatusOK
		w.status = status
	}
	contentType := strings.ToLower(w.Header().Get("Content-Type"))
	compressible := strings.HasPrefix(contentType, "application/json") ||
		strings.HasPrefix(contentType, "application/javascript") ||
		strings.HasPrefix(contentType, "text/")
	if compressible {
		addVary(w.Header(), "Accept-Encoding")
	}
	w.compressing = !force && len(w.buffer) >= gzipMinSize && acceptsGzip(w.request.Header.Get("Accept-Encoding")) &&
		compressible && w.Header().Get("Content-Encoding") == "" && status != http.StatusNoContent && status != http.StatusNotModified
	if w.compressing {
		w.Header().Del("Content-Length")
		w.Header().Set("Content-Encoding", "gzip")
		w.ResponseWriter.WriteHeader(status)
		zipper, err := gzip.NewWriterLevel(w.ResponseWriter, 6)
		if err != nil {
			return err
		}
		w.zipper = zipper
		if len(w.buffer) > 0 {
			_, err = w.zipper.Write(w.buffer)
		}
		w.buffer = nil
		return err
	}
	w.ResponseWriter.WriteHeader(status)
	if len(w.buffer) > 0 {
		_, err := w.ResponseWriter.Write(w.buffer)
		w.buffer = nil
		return err
	}
	return nil
}

func (w *gzipResponseWriter) close() error {
	if !w.decided {
		if err := w.commit(len(w.buffer) < gzipMinSize); err != nil {
			return err
		}
	}
	if w.zipper != nil {
		return w.zipper.Close()
	}
	return nil
}

func acceptsGzip(raw string) bool {
	wildcard := false
	for _, part := range strings.Split(raw, ",") {
		fields := strings.Split(strings.TrimSpace(part), ";")
		coding := strings.TrimSpace(fields[0])
		if !strings.EqualFold(coding, "gzip") && coding != "*" {
			continue
		}
		quality := 1.0
		for _, parameter := range fields[1:] {
			key, value, found := strings.Cut(strings.TrimSpace(parameter), "=")
			if found && strings.EqualFold(strings.TrimSpace(key), "q") {
				parsed, err := strconv.ParseFloat(strings.TrimSpace(value), 64)
				if err != nil || parsed < 0 || parsed > 1 {
					quality = 0
				} else {
					quality = parsed
				}
			}
		}
		if strings.EqualFold(coding, "gzip") {
			return quality > 0
		}
		wildcard = quality > 0
	}
	return wildcard
}

func addVary(header http.Header, value string) {
	for _, existing := range header.Values("Vary") {
		for _, item := range strings.Split(existing, ",") {
			if strings.EqualFold(strings.TrimSpace(item), value) {
				return
			}
		}
	}
	header.Add("Vary", value)
}

func middleware(logger *slog.Logger, server *Server, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		started := time.Now()
		rid := strings.TrimSpace(r.Header.Get("X-Request-ID"))
		if rid == "" || len(rid) > 64 {
			rid = randomID()
		}
		w.Header().Set("X-Request-ID", rid)
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Referrer-Policy", "no-referrer")
		if strings.HasPrefix(r.URL.Path, "/api/") || strings.HasPrefix(r.URL.Path, "/proxy/jw/") || r.URL.Path == "/admin" || r.URL.Path == "/admin/" {
			w.Header().Set("Cache-Control", "no-store")
		}
		ctx := context.WithValue(r.Context(), requestIDKey, rid)
		compressed := &gzipResponseWriter{ResponseWriter: w, request: r}
		sw := &statusWriter{ResponseWriter: compressed}

		defer func() {
			if recovered := recover(); recovered != nil {
				logger.Error("请求处理发生 panic", "rid", rid, "error", recovered,
					"stack", string(debug.Stack()))
				if sw.status == 0 {
					writeJSON(sw, http.StatusInternalServerError, map[string]any{
						"error": "服务器内部错误",
						"rid":   rid,
					})
				}
			}
			if err := compressed.close(); err != nil {
				logger.Warn("响应压缩写入失败", "rid", rid, "error", err)
			}
			logger.Info("请求完成", "rid", rid, "method", r.Method,
				"path", r.URL.Path, "status", sw.status,
				"duration_ms", time.Since(started).Milliseconds())
			server.recordRequest(r, sw.status, time.Since(started))
		}()

		if !server.IsReady() && !startupProbePath(r.URL.Path) {
			w.Header().Set("Retry-After", "5")
			writeError(sw, http.StatusServiceUnavailable, "服务正在初始化，请稍后重试")
			return
		}

		if (r.Method == http.MethodGet || r.Method == http.MethodHead) && r.URL.Path == "/admin/" {
			target := "/admin"
			if r.URL.RawQuery != "" {
				target += "?" + r.URL.RawQuery
			}
			http.Redirect(sw, r, target, http.StatusPermanentRedirect)
			return
		}

		if values, exists := r.URL.Query()["semester"]; exists {
			allowAll := r.URL.Path == "/api/grades"
			if len(values) != 1 || strings.TrimSpace(values[0]) != "" && !validSemester(values[0], allowAll) {
				writeError(sw, http.StatusBadRequest, "学期格式无效")
				return
			}
		}

		next.ServeHTTP(sw, r.WithContext(ctx))
	})
}

func startupProbePath(path string) bool {
	return path == "/healthz" || path == "/readyz"
}

func randomID() string {
	var value [8]byte
	if _, err := rand.Read(value[:]); err != nil {
		return "unknown"
	}
	return hex.EncodeToString(value[:])
}
