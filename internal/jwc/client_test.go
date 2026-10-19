package jwc

import (
	"bytes"
	"io"
	"net/http"
	"net/url"
	"reflect"
	"testing"

	"github.com/resetinging/njust-schedule/internal/store"
)

type trackedBody struct {
	io.Reader
	closed bool
}

func (b *trackedBody) Close() error {
	b.closed = true
	return nil
}

func TestReadResponseAcceptsLimitAndClosesBody(t *testing.T) {
	body := &trackedBody{Reader: bytes.NewReader(bytes.Repeat([]byte("x"), maxResponseBody))}
	raw, err := readResponse(&http.Response{Body: body})
	if err != nil {
		t.Fatal(err)
	}
	if len(raw) != maxResponseBody {
		t.Fatalf("body length = %d, want %d", len(raw), maxResponseBody)
	}
	if !body.closed {
		t.Fatal("response body was not closed")
	}
}

func TestReadResponseRejectsOversizedBody(t *testing.T) {
	body := &trackedBody{Reader: bytes.NewReader(bytes.Repeat([]byte("x"), maxResponseBody+1))}
	if _, err := readResponse(&http.Response{Body: body}); err == nil {
		t.Fatal("oversized response should be rejected")
	}
	if !body.closed {
		t.Fatal("response body was not closed")
	}
}

func TestCookiesPreserveOriginalDomainAndPath(t *testing.T) {
	want := []store.Cookie{
		{Name: "CASTGC", Value: "ticket", Domain: ".njust.edu.cn", Path: "/"},
		{Name: "JSESSIONID", Value: "session", Domain: "bkjw.njust.edu.cn", Path: "/njlgdx"},
	}
	client := New(want)
	if got := client.Cookies(); !reflect.DeepEqual(got, want) {
		t.Fatalf("Cookies() = %#v, want %#v", got, want)
	}
}

func TestCookiesUseRFCDefaultPathWithoutDuplicates(t *testing.T) {
	client := New(nil)
	u, err := url.Parse("https://bkjw.njust.edu.cn/njlgdx/framework/main.jsp")
	if err != nil {
		t.Fatal(err)
	}
	client.HTTP.Jar.SetCookies(u, []*http.Cookie{{Name: "JSESSIONID", Value: "session"}})
	want := []store.Cookie{{Name: "JSESSIONID", Value: "session", Domain: "bkjw.njust.edu.cn", Path: "/njlgdx/framework"}}
	if got := client.Cookies(); !reflect.DeepEqual(got, want) {
		t.Fatalf("Cookies() = %#v, want %#v", got, want)
	}

	for _, rawURL := range []string{
		"https://bkjw.njust.edu.cn/",
		"https://bkjw.njust.edu.cn/njlgdx/",
		"https://bkjw.njust.edu.cn/njlgdx/framework/main.jsp",
	} {
		requestURL, _ := url.Parse(rawURL)
		_ = client.HTTP.Jar.Cookies(requestURL)
	}
	if got := client.Cookies(); !reflect.DeepEqual(got, want) {
		t.Fatalf("reading cookies changed persistence records: %#v", got)
	}
}

func TestCookiesRemoveExpiredRecord(t *testing.T) {
	client := New([]store.Cookie{{Name: "JSESSIONID", Value: "old", Domain: "bkjw.njust.edu.cn", Path: "/"}})
	u, _ := url.Parse("https://bkjw.njust.edu.cn/")
	client.HTTP.Jar.SetCookies(u, []*http.Cookie{{Name: "JSESSIONID", Value: "", Path: "/", MaxAge: -1}})
	if got := client.Cookies(); len(got) != 0 {
		t.Fatalf("expired cookies were persisted: %#v", got)
	}
}

func TestNewUsesIndependentHTTPTransport(t *testing.T) {
	first := New(nil)
	second := New(nil)
	firstTransport, firstOK := first.HTTP.Transport.(*http.Transport)
	secondTransport, secondOK := second.HTTP.Transport.(*http.Transport)
	if !firstOK || !secondOK {
		t.Fatalf("unexpected transports: %T %T", first.HTTP.Transport, second.HTTP.Transport)
	}
	if firstTransport == secondTransport || firstTransport == http.DefaultTransport || secondTransport == http.DefaultTransport {
		t.Fatal("JWC clients must not share an HTTP transport")
	}
}

func TestExtractIdentityFromTopLoginName(t *testing.T) {
	client := New(nil)
	client.extractIdentity(`<div id="Top1_divLoginName">肖尧麓(924101960123)</div>`)
	if client.StudentName != "肖尧麓" {
		t.Fatalf("StudentName = %q", client.StudentName)
	}
	if client.StudentID != "924101960123" {
		t.Fatalf("StudentID = %q", client.StudentID)
	}
}
