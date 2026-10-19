package security

import (
	"bytes"
	"testing"

	"github.com/resetinging/njust-schedule/internal/store"
)

func TestDecryptPythonAESGCMVector(t *testing.T) {
	key := make([]byte, 32)
	for i := range key {
		key[i] = byte(i)
	}
	crypto, err := New(key)
	if err != nil {
		t.Fatal(err)
	}
	const token = "AQABAgMEBQYHCAkKCzwgtXSqjqt+/mOt0MrLFgzus6UO0jEMOWs0rMpTIESQLTLYncO0d7pOhh6P66UEGoo2DewzuIHgHfVBc2/Nm4SFT7JUtrVTT386iELN/2+cUKjzQFlBLjXR3/+vG5/M47+nLZ/UJOogvGlQ1i0HRg3bAxfKl6AHtm+LJO+411k+i2Iw9oTn+y4Lz4/U/1+zBzI5SQZ37PaE"
	var got store.PersistentSession
	if err = crypto.Decrypt("924101960000", token, &got); err != nil {
		t.Fatal(err)
	}
	if got.Timestamp != 1700000000 || got.AccountType != "undergraduate" || len(got.Cookies) != 1 {
		t.Fatalf("unexpected payload: %#v", got)
	}
	want := store.Cookie{Name: "JSESSIONID", Value: "abc", Domain: "bkjw.njust.edu.cn", Path: "/"}
	if got.Cookies[0] != want {
		t.Fatalf("cookie = %#v, want %#v", got.Cookies[0], want)
	}
}

func TestEncryptRoundTripAndAADBinding(t *testing.T) {
	key := bytes.Repeat([]byte{7}, 32)
	crypto, err := New(key)
	if err != nil {
		t.Fatal(err)
	}
	token, err := crypto.Encrypt("student-a", map[string]string{"pwd": "secret"})
	if err != nil {
		t.Fatal(err)
	}
	var got map[string]string
	if err = crypto.Decrypt("student-a", token, &got); err != nil || got["pwd"] != "secret" {
		t.Fatalf("round trip failed: payload=%#v err=%v", got, err)
	}
	if err = crypto.Decrypt("student-b", token, &got); err == nil {
		t.Fatal("ciphertext must be bound to AAD")
	}
}
