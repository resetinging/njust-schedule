package jwc

import (
	"strings"
	"testing"

	"github.com/PuerkitoBio/goquery"
)

func TestParseFormPreservesSuccessfulControls(t *testing.T) {
	doc, err := goquery.NewDocumentFromReader(strings.NewReader(`
<form id="pwdFromId" action="/authserver/login" method="POST" enctype="application/x-www-form-urlencoded; charset=UTF-8">
  <input type="hidden" name="execution" id="execution" value="e2s1">
  <input type="hidden" name="lt" id="lt" value="LT-1">
  <input type="hidden" name="dynamic" value="server-value">
  <input type="checkbox" name="enabled" value="yes" checked>
  <input type="checkbox" name="ignored" value="no">
  <input type="text" name="disabled" value="x" disabled>
  <select name="locale"><option value="en">EN</option><option value="zh" selected>ZH</option></select>
  <textarea name="note">hello</textarea>
  <button name="submitButton" value="ignored">Submit</button>
</form>`))
	if err != nil {
		t.Fatal(err)
	}
	form := doc.Find("form#pwdFromId")
	parsed := parseForm(form)
	if err = validatePostForm(parsed); err != nil {
		t.Fatal(err)
	}
	if parsed.Action != "/authserver/login" || parsed.Method != "post" || parsed.Enctype != "application/x-www-form-urlencoded" {
		t.Fatalf("unexpected metadata: %#v", parsed)
	}
	for key, want := range map[string]string{"execution": "e2s1", "lt": "LT-1", "dynamic": "server-value", "enabled": "yes", "locale": "zh", "note": "hello"} {
		if got := parsed.Values.Get(key); got != want {
			t.Fatalf("%s = %q, want %q", key, got, want)
		}
	}
	for _, key := range []string{"ignored", "disabled", "submitButton"} {
		if parsed.Values.Has(key) {
			t.Fatalf("unexpected control %q in payload", key)
		}
	}
}

func TestValidatePostFormRejectsUnexpectedFormat(t *testing.T) {
	for _, test := range []struct {
		name string
		form parsedForm
	}{
		{"get", parsedForm{Method: "get", Enctype: "application/x-www-form-urlencoded"}},
		{"multipart", parsedForm{Method: "post", Enctype: "multipart/form-data"}},
	} {
		t.Run(test.name, func(t *testing.T) {
			if err := validatePostForm(test.form); err == nil {
				t.Fatal("unexpected form format should be rejected")
			}
		})
	}
}

func TestResolveFormURLRequiresSameOrigin(t *testing.T) {
	got, err := resolveFormURL("https://ids.njust.edu.cn/authserver/login?service=x", "/authserver/login")
	if err != nil || got != "https://ids.njust.edu.cn/authserver/login" {
		t.Fatalf("resolveFormURL() = %q, %v", got, err)
	}
	for _, action := range []string{"https://evil.example/collect", "//evil.example/collect", "javascript:alert(1)"} {
		if _, err = resolveFormURL("https://ids.njust.edu.cn/authserver/login", action); err == nil {
			t.Fatalf("external form action %q was accepted", action)
		}
	}
}
