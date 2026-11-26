package campus

import (
	"strings"
	"testing"
)

func validService() Service {
	return Service{
		ID:           "campus-test",
		Category:     CategoryGraduate,
		ProviderName: "示例升学服务中心",
		Title:        "保研材料咨询",
		Summary:      "提供材料梳理和面试经验咨询",
		Audience:     "大三、大四学生",
		PriceLabel:   "按次咨询",
		CampusScope:  CampusAll,
		Verified:     true,
		Enabled:      true,
		StartDate:    "2026-11-24",
	}
}

func TestValidateService(t *testing.T) {
	item := validService()
	item.Details = "第一段\n第二段"
	NormalizeService(&item, "2026-11-24")
	if err := ValidateService(item); err != nil {
		t.Fatal(err)
	}

	item.Enabled = true
	item.Verified = false
	if err := ValidateService(item); err == nil || !strings.Contains(err.Error(), "完成审核") {
		t.Fatalf("unexpected verification error: %v", err)
	}

	item = validService()
	item.Details = "承诺保过并保证内部名额"
	if err := ValidateService(item); err == nil || !strings.Contains(err.Error(), "不允许的承诺") {
		t.Fatalf("unexpected claim error: %v", err)
	}

	item = validService()
	item.Title = "<script>alert(1)</script>"
	if err := ValidateService(item); err == nil {
		t.Fatal("HTML title should be rejected")
	}

	item = validService()
	item.PriceLabel = ""
	if err := ValidateService(item); err == nil || !strings.Contains(err.Error(), "价格说明") {
		t.Fatalf("unexpected price error: %v", err)
	}
}

func TestNormalizeContact(t *testing.T) {
	normalized, masked, err := NormalizeContact(ContactPhone, "138 0013 8000")
	if err != nil || normalized != "13800138000" || masked != "138****8000" {
		t.Fatalf("phone normalized=%q masked=%q err=%v", normalized, masked, err)
	}

	normalized, masked, err = NormalizeContact(ContactWeChat, "njust_2026")
	if err != nil || normalized != "njust_2026" || !strings.Contains(masked, "*") {
		t.Fatalf("wechat normalized=%q masked=%q err=%v", normalized, masked, err)
	}

	if _, _, err = NormalizeContact(ContactPhone, "12345"); err == nil {
		t.Fatal("invalid phone accepted")
	}
	if _, _, err = NormalizeContact("email", "a@example.com"); err == nil {
		t.Fatal("invalid contact type accepted")
	}
}

func TestServiceDateValidation(t *testing.T) {
	item := validService()
	item.EndDate = "2026-11-23"
	if err := ValidateService(item); err == nil || !strings.Contains(err.Error(), "结束日期") {
		t.Fatalf("unexpected date error: %v", err)
	}
}
