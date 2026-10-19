package httpapi

import (
	"encoding/base64"
	"io"
	"mime"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/naughtygopher/webgo/v7"
)

const galleryChunkBytes = 300 * 1024

func (s *Server) index(w http.ResponseWriter, r *http.Request) {
	http.Redirect(w, r, "/admin", http.StatusFound)
}

func (s *Server) recordRequest(r *http.Request, status int, elapsed time.Duration) {
	if status == 0 {
		status = http.StatusOK
	}
	sid := ""
	if value, ok := s.session(r); ok {
		sid = value.StudentID
	}
	now := time.Now().In(beijing)
	s.adminMu.Lock()
	s.adminTotal++
	s.adminSeq++
	s.adminRecent = append(s.adminRecent, requestRecord{
		ID: s.adminSeq, TS: now.Format("15:04:05"), Epoch: float64(now.UnixMilli()) / 1000,
		Method: r.Method, Path: requestLogPath(r), Status: status,
		MS: elapsed.Milliseconds(), SID: sid, IP: s.clientIP(r),
	})
	if len(s.adminRecent) > 1000 {
		s.adminRecent = append([]requestRecord(nil), s.adminRecent[len(s.adminRecent)-1000:]...)
	}
	s.adminMu.Unlock()
}

func requestLogPath(r *http.Request) string {
	if r == nil || r.URL == nil {
		return ""
	}
	return r.URL.Path
}

func (s *Server) postFeedback(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	var body struct {
		Type    string `json:"type"`
		Content string `json:"content"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	kind := strings.TrimSpace(body.Type)
	if kind != "suggest" && kind != "bug" && kind != "other" {
		kind = "other"
	}
	content := strings.TrimSpace(body.Content)
	if content == "" {
		writeError(w, http.StatusBadRequest, "反馈内容不能为空")
		return
	}
	if len([]rune(content)) > 500 {
		writeError(w, http.StatusBadRequest, "内容不能超过 500 字")
		return
	}
	for _, word := range []string{"代考", "代做", "代写", "出售答案", "买答案", "刷课", "代刷", "代课", "替考", "枪手", "作弊", "卖答案", "发答案", "有偿代", "包过"} {
		if strings.Contains(content, word) {
			writeError(w, http.StatusBadRequest, "内容包含敏感词，请修改")
			return
		}
	}
	if s.rateLimited("feedback:"+sess.StudentID, 1, 10*time.Second) {
		writeError(w, http.StatusTooManyRequests, "提交太频繁，请稍后再试")
		return
	}
	item, err := s.store.CreateFeedback(r.Context(), sess.StudentID, sess.StudentName, kind, content)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "保存反馈失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "message": "反馈已提交，可在「我的反馈」查看回复", "fb": item.JSON()})
}

func (s *Server) myFeedback(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	items, err := s.store.FeedbackByUser(r.Context(), sess.StudentID, 50)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取反馈失败")
		return
	}
	unread, err := s.store.FeedbackUnread(r.Context(), sess.StudentID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取反馈失败")
		return
	}
	values := make([]map[string]any, 0, len(items))
	for _, item := range items {
		values = append(values, item.JSON())
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "feedback": values, "unread": unread})
}

func (s *Server) readFeedback(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	marked, err := s.store.MarkRepliesRead(r.Context(), sess.StudentID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "更新反馈状态失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "marked": marked})
}

func (s *Server) announcement(w http.ResponseWriter, r *http.Request) {
	settings, err := s.store.Settings(r.Context(), "announcement_text", "announcement_enabled", "announcement_updated")
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取公告失败")
		return
	}
	text, enabled, updated := settings["announcement_text"], settings["announcement_enabled"], settings["announcement_updated"]
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "enabled": enabled != "0" && strings.TrimSpace(text) != "", "text": strings.TrimSpace(text), "updated": updated})
}

func (s *Server) galleryDir() string { return filepath.Join(s.cfg.StaticDir, "gallery") }

func (s *Server) galleryImages(w http.ResponseWriter, _ *http.Request) {
	entries, err := os.ReadDir(s.galleryDir())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取图库失败")
		return
	}
	images := []string{}
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		switch strings.ToLower(filepath.Ext(entry.Name())) {
		case ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp":
			images = append(images, entry.Name())
		}
	}
	sort.Strings(images)
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "images": images})
}

func (s *Server) galleryPath(name string) (string, bool) {
	name = strings.TrimSpace(name)
	if name == "" || filepath.Base(name) != name || strings.Contains(name, "..") {
		return "", false
	}
	path := filepath.Join(s.galleryDir(), name)
	info, err := os.Stat(path)
	return path, err == nil && !info.IsDir()
}

func imageMIME(raw []byte) string {
	if len(raw) == 0 {
		return "application/octet-stream"
	}
	return http.DetectContentType(raw)
}

func (s *Server) galleryImage(w http.ResponseWriter, r *http.Request) {
	name := strings.TrimSpace(r.URL.Query().Get("name"))
	path, ok := s.galleryPath(name)
	if !ok {
		writeError(w, http.StatusNotFound, "图片不存在")
		return
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取图片失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "name": name, "mime": imageMIME(raw), "data_b64": base64.StdEncoding.EncodeToString(raw)})
}

func (s *Server) galleryImageMeta(w http.ResponseWriter, r *http.Request) {
	name := strings.TrimSpace(r.URL.Query().Get("name"))
	path, ok := s.galleryPath(name)
	if !ok {
		writeError(w, http.StatusNotFound, "图片不存在")
		return
	}
	info, err := os.Stat(path)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取图片失败")
		return
	}
	parts := max(1, int((info.Size()+galleryChunkBytes-1)/galleryChunkBytes))
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "name": name, "size": info.Size(), "parts": parts, "chunk_bytes": galleryChunkBytes})
}

func (s *Server) galleryImagePart(w http.ResponseWriter, r *http.Request) {
	name := strings.TrimSpace(r.URL.Query().Get("name"))
	part, err := strconv.Atoi(r.URL.Query().Get("part"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "无效的分片序号")
		return
	}
	path, ok := s.galleryPath(name)
	if !ok {
		writeError(w, http.StatusNotFound, "图片不存在")
		return
	}
	file, err := os.Open(path)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取图片失败")
		return
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取图片信息失败")
		return
	}
	parts := max(1, int((info.Size()+galleryChunkBytes-1)/galleryChunkBytes))
	if part < 0 || part >= parts {
		writeError(w, http.StatusBadRequest, "分片序号越界")
		return
	}
	if _, err = file.Seek(int64(part*galleryChunkBytes), io.SeekStart); err != nil {
		writeError(w, http.StatusInternalServerError, "定位图片分片失败")
		return
	}
	raw, err := io.ReadAll(io.LimitReader(file, galleryChunkBytes))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "读取图片失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "name": name, "part": part, "parts": parts, "data_b64": base64.StdEncoding.EncodeToString(raw)})
}

func (s *Server) fontPath(name string) string { return filepath.Join(s.cfg.StaticDir, "fonts", name) }

func (s *Server) pixelFont(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Cache-Control", "public, max-age=604800")
	http.ServeFile(w, r, s.fontPath("pixel.woff2"))
}

func (s *Server) pixelFontJSON(w http.ResponseWriter, r *http.Request) {
	if s.rateLimited("fontjson:"+s.clientIP(r), 5, time.Minute) {
		writeError(w, http.StatusTooManyRequests, "too many requests")
		return
	}
	raw, err := os.ReadFile(s.fontPath("pixel.woff2"))
	if err != nil {
		writeError(w, http.StatusNotFound, "font not found")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"format": "woff2", "encoding": "base64", "data": base64.StdEncoding.EncodeToString(raw)})
}

func (s *Server) fontSubset(w http.ResponseWriter, r *http.Request) {
	if s.rateLimited("fontsubset:"+s.clientIP(r), 10, time.Minute) {
		writeError(w, http.StatusTooManyRequests, "too many requests")
		return
	}
	var body struct {
		Text string `json:"text"`
		Font string `json:"font"`
	}
	if err := decodeJSON(r, &body); err != nil || strings.TrimSpace(body.Text) == "" {
		writeError(w, http.StatusBadRequest, "no text")
		return
	}
	characters := []rune(body.Text)
	if len(characters) > 512 {
		writeError(w, http.StatusBadRequest, "text too long")
		return
	}
	name := strings.TrimSpace(body.Font)
	if name == "" || name == "pixel" {
		name = "pixel"
	}
	if !map[string]bool{"pixel": true, "wenkai": true, "smiley": true}[name] {
		writeError(w, http.StatusBadRequest, "unknown font")
		return
	}
	var path string
	for _, ext := range []string{".woff2", ".woff", ".ttf", ".otf"} {
		candidate := s.fontPath(name + ext)
		if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
			path = candidate
			break
		}
	}
	if path == "" {
		writeError(w, http.StatusNotFound, "font not found")
		return
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "font read failed")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"format": strings.TrimPrefix(filepath.Ext(path), "."), "encoding": "base64", "chars": len(characters), "full": true, "data": base64.StdEncoding.EncodeToString(raw)})
}

func (s *Server) fontList(w http.ResponseWriter, _ *http.Request) {
	fonts := []map[string]any{{"key": "pixel", "name": "像素点阵", "builtin": true}}
	for key, name := range map[string]string{"wenkai": "霞鹜文楷", "smiley": "得意黑"} {
		for _, ext := range []string{".woff2", ".ttf", ".otf"} {
			if info, err := os.Stat(s.fontPath(key + ext)); err == nil && !info.IsDir() {
				fonts = append(fonts, map[string]any{"key": key, "name": name, "builtin": false})
				break
			}
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "fonts": fonts})
}

func (s *Server) staticFile(w http.ResponseWriter, r *http.Request) {
	escapedPath := webgo.Context(r).Params()["path"]
	decodedPath, err := url.PathUnescape(escapedPath)
	if err != nil {
		http.NotFound(w, r)
		return
	}
	clean := filepath.Clean(filepath.FromSlash(decodedPath))
	if clean == "." || filepath.IsAbs(clean) || strings.HasPrefix(clean, "..") {
		http.NotFound(w, r)
		return
	}
	root, err := filepath.Abs(s.cfg.StaticDir)
	if err != nil {
		http.NotFound(w, r)
		return
	}
	full, err := filepath.Abs(filepath.Join(root, clean))
	if err != nil {
		http.NotFound(w, r)
		return
	}
	relative, err := filepath.Rel(root, full)
	if err != nil || relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) {
		http.NotFound(w, r)
		return
	}
	w.Header().Set("Cache-Control", "public, max-age=3600")
	if kind := mime.TypeByExtension(filepath.Ext(full)); kind != "" {
		w.Header().Set("Content-Type", kind)
	}
	http.ServeFile(w, r, full)
}
