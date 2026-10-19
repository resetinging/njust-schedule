package httpapi

import "testing"

func TestAnalyticsWhitelistsNoticeContent(t *testing.T) {
	if !usagePages["notice"] {
		t.Fatal("notice must be accepted as an analytics page")
	}
	if !usageFeatures["notice"] {
		t.Fatal("notice must be accepted as an analytics feature")
	}
}
