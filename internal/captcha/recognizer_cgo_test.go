//go:build cgo

package captcha

import (
	"context"
	"os"
	"testing"
)

func TestSolverWithFixture(t *testing.T) {
	modelPath := os.Getenv("CAPTCHA_OCR_TEST_MODEL")
	fixturePath := os.Getenv("CAPTCHA_OCR_TEST_FIXTURE")
	if modelPath == "" || fixturePath == "" {
		t.Skip("未配置 CAPTCHA_OCR_TEST_MODEL/CAPTCHA_OCR_TEST_FIXTURE")
	}
	raw, err := os.ReadFile(fixturePath)
	if err != nil {
		t.Fatal(err)
	}
	text, err := NewSolver(modelPath, os.Getenv("ONNXRUNTIME_SHARED_LIBRARY_PATH")).Solve(context.Background(), raw)
	if err != nil {
		t.Fatal(err)
	}
	if text != "yL3m" {
		t.Fatalf("Solve() = %q, want %q", text, "yL3m")
	}
}
