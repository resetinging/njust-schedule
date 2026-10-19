package captcha

import (
	"context"
	"testing"
)

func TestSolveRejectsEmptyImageWithoutLoadingModel(t *testing.T) {
	_, err := NewSolver("missing.onnx", "").Solve(context.Background(), nil)
	if err == nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestDecodeCollapsesRepeatedClasses(t *testing.T) {
	old := charset
	charset = []string{"", "a", "b", "c"}
	t.Cleanup(func() { charset = old })
	if got := decode([]int64{0, 1, 1, 0, 2, 3, 3, 1}); got != "abca" {
		t.Fatalf("decode() = %q, want %q", got, "abca")
	}
}

func TestDecodeScores(t *testing.T) {
	old := charset
	charset = []string{"", "a", "b", "c"}
	t.Cleanup(func() { charset = old })
	scores := []float32{
		0, 1, 0, 0,
		0, 1, 0, 0,
		0, 0, 1, 0,
		0, 0, 0, 1,
		0, 0, 0, 1,
	}
	if got := decodeScores(scores, len(charset)); got != "abc" {
		t.Fatalf("decodeScores() = %q, want %q", got, "abc")
	}
}
