package jwc

import (
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/resetinging/njust-schedule/internal/store"
)

// persistentCookieJar keeps the original cookie scope because net/http's
// CookieJar intentionally omits Domain and Path when cookies are read back.
type persistentCookieJar struct {
	inner   http.CookieJar
	mu      sync.Mutex
	records map[string]store.Cookie
}

func newPersistentCookieJar() *persistentCookieJar {
	inner, _ := cookiejar.New(nil)
	return &persistentCookieJar{inner: inner, records: map[string]store.Cookie{}}
}

func (j *persistentCookieJar) Cookies(u *url.URL) []*http.Cookie {
	return j.inner.Cookies(u)
}

func (j *persistentCookieJar) SetCookies(u *url.URL, values []*http.Cookie) {
	j.inner.SetCookies(u, values)
	if u == nil {
		return
	}
	now := time.Now()
	j.mu.Lock()
	defer j.mu.Unlock()
	for _, item := range values {
		if item == nil || strings.TrimSpace(item.Name) == "" {
			continue
		}
		domain := strings.TrimSpace(item.Domain)
		if domain == "" {
			domain = strings.ToLower(u.Hostname())
		}
		path := strings.TrimSpace(item.Path)
		if path == "" {
			path = defaultCookiePath(u.EscapedPath())
		}
		key := cookieRecordKey(item.Name, domain, path)
		if item.MaxAge < 0 || (!item.Expires.IsZero() && !item.Expires.After(now)) {
			delete(j.records, key)
			continue
		}
		j.records[key] = store.Cookie{Name: item.Name, Value: item.Value, Domain: domain, Path: path}
	}
}

func (j *persistentCookieJar) PersistentCookies() []store.Cookie {
	j.mu.Lock()
	defer j.mu.Unlock()
	out := make([]store.Cookie, 0, len(j.records))
	for _, item := range j.records {
		out = append(out, item)
	}
	sort.Slice(out, func(a, b int) bool {
		if out[a].Domain != out[b].Domain {
			return out[a].Domain < out[b].Domain
		}
		if out[a].Path != out[b].Path {
			return out[a].Path < out[b].Path
		}
		return out[a].Name < out[b].Name
	})
	return out
}

func cookieRecordKey(name, domain, path string) string {
	return name + "\x00" + strings.ToLower(strings.TrimPrefix(domain, ".")) + "\x00" + path
}

func defaultCookiePath(requestPath string) string {
	if requestPath == "" || requestPath[0] != '/' {
		return "/"
	}
	lastSlash := strings.LastIndexByte(requestPath, '/')
	if lastSlash <= 0 {
		return "/"
	}
	return requestPath[:lastSlash]
}
