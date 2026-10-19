package jwc

import "testing"

func TestSafeJWPath(t *testing.T) {
	tests := []struct {
		name string
		raw  string
		want string
		ok   bool
	}{
		{name: "relative path", raw: "/njlgdx/xspj/xspj_find.do?a=1", want: "/njlgdx/xspj/xspj_find.do?a=1", ok: true},
		{name: "absolute URL", raw: "http://example.com/njlgdx/x", ok: false},
		{name: "wrong prefix", raw: "/njlgdx.evil/x", ok: false},
		{name: "plain traversal", raw: "/njlgdx/../admin", ok: false},
		{name: "encoded traversal", raw: "/njlgdx/%252e%252e/admin", ok: false},
		{name: "encoded backslash", raw: "/njlgdx/%5c../admin", ok: false},
		{name: "double encoded backslash", raw: "/njlgdx/%255c../admin", ok: false},
		{name: "encoded query delimiter", raw: "/njlgdx/a%3fb", ok: false},
		{name: "encoded fragment delimiter", raw: "/njlgdx/a%23b", ok: false},
		{name: "encoded control", raw: "/njlgdx/a%00b", ok: false},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got, err := SafeJWPath(test.raw)
			if (err == nil) != test.ok {
				t.Fatalf("SafeJWPath(%q) error = %v, want ok=%v", test.raw, err, test.ok)
			}
			if test.ok && got != test.want {
				t.Fatalf("SafeJWPath(%q) = %q, want %q", test.raw, got, test.want)
			}
		})
	}
}

func TestSafeJWPathRejectsExcessiveEncoding(t *testing.T) {
	raw := "/njlgdx/%25252525252525252e"
	if _, err := SafeJWPath(raw); err == nil {
		t.Fatal("excessively encoded path was accepted")
	}
}
