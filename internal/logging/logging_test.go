package logging

import (
	"bytes"
	"log/slog"
	"strings"
	"testing"
)

func TestNewWritesReadableSingleLineLog(t *testing.T) {
	var output bytes.Buffer
	logger := New(&output, slog.LevelInfo)
	logger.Info("请求完成", "method", "GET", "path", "/api/status", "status", 200)

	line := strings.TrimSpace(output.String())
	if line == "" || strings.Contains(line, "\n") {
		t.Fatalf("expected one log line, got %q", output.String())
	}
	if strings.HasPrefix(line, "{") || !strings.Contains(line, "level=INFO") || !strings.Contains(line, "path=/api/status") {
		t.Fatalf("log is not readable text: %q", line)
	}
	if !strings.Contains(line, "T") || !strings.Contains(line, "+08:00") {
		t.Fatalf("unexpected timestamp: %q", line)
	}
}
