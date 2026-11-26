package httpapi

import (
	"testing"
	"time"
)

func TestPreferredSemesterInListChoosesCurrentAutumnSemester(t *testing.T) {
	now := time.Date(2026, 11, 27, 12, 0, 0, 0, beijing)
	got := preferredSemesterInList([]string{"2026-2027-2", "2026-2027-1"}, now)
	if got != "2026-2027-1" {
		t.Fatalf("preferred semester = %q", got)
	}
}

func TestPreferredSemesterInListFallsBackToFirst(t *testing.T) {
	now := time.Date(2026, 11, 27, 12, 0, 0, 0, beijing)
	got := preferredSemesterInList([]string{"2025-2026-2", "2025-2026-1"}, now)
	if got != "2025-2026-2" {
		t.Fatalf("fallback semester = %q", got)
	}
}
