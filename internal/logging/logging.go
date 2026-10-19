package logging

import (
	"io"
	"log/slog"
	"time"
)

var beijing = time.FixedZone("CST", 8*60*60)

// New returns one-line, human-readable logs that cloud log viewers can display
// without collapsing structured fields into an opaque object.
func New(output io.Writer, level slog.Level) *slog.Logger {
	handler := slog.NewTextHandler(output, &slog.HandlerOptions{
		Level: level,
		ReplaceAttr: func(groups []string, attr slog.Attr) slog.Attr {
			if len(groups) == 0 && attr.Key == slog.TimeKey {
				return slog.String(
					slog.TimeKey,
					attr.Value.Time().In(beijing).Format("2006-01-02T15:04:05-07:00"),
				)
			}
			return attr
		},
	})
	return slog.New(handler)
}
