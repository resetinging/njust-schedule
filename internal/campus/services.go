package campus

import (
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

const (
	CategoryOperator  = "operator"
	CategoryMaterials = "materials"
	CategoryGraduate  = "graduate"
	CategoryExam      = "exam"

	CampusAll      = "all"
	CampusNanjing  = "nanjing"
	CampusJiangyin = "jiangyin"

	ContactPhone  = "phone"
	ContactWeChat = "wechat"

	ConsentVersion = "campus-service-2026-11-24"

	LeadStatusNew       = "new"
	LeadStatusContacted = "contacted"
	LeadStatusConverted = "converted"
	LeadStatusInvalid   = "invalid"

	MaxServices = 200
)

var (
	serviceIDPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`)
	phonePattern     = regexp.MustCompile(`^1[3-9][0-9]{9}$`)
	wechatPattern    = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_-]{2,39}$`)
)

var forbiddenClaims = []string{
	"保过", "包过", "保上岸", "包上岸", "内部名额", "内部指标",
	"必过", "稳过", "100%通过", "百分百通过", "代考", "替考", "卖答案",
}

// Service is the administrator-facing campus service record.
type Service struct {
	ID                string `json:"id"`
	Category          string `json:"category"`
	ProviderName      string `json:"provider_name"`
	Title             string `json:"title"`
	Summary           string `json:"summary"`
	Details           string `json:"details"`
	Audience          string `json:"audience"`
	PriceLabel        string `json:"price_label"`
	CampusScope       string `json:"campus_scope"`
	QualificationNote string `json:"qualification_note"`
	Sponsored         bool   `json:"sponsored"`
	Verified          bool   `json:"verified"`
	Enabled           bool   `json:"enabled"`
	Priority          int    `json:"priority"`
	StartDate         string `json:"start_date"`
	EndDate           string `json:"end_date"`
}

type PublicService struct {
	ID                string `json:"id"`
	Category          string `json:"category"`
	ProviderName      string `json:"provider_name"`
	Title             string `json:"title"`
	Summary           string `json:"summary"`
	Details           string `json:"details,omitempty"`
	Audience          string `json:"audience"`
	PriceLabel        string `json:"price_label"`
	CampusScope       string `json:"campus_scope"`
	QualificationNote string `json:"qualification_note"`
	Sponsored         bool   `json:"sponsored"`
	StartDate         string `json:"start_date"`
	EndDate           string `json:"end_date"`
}

func (s Service) Public() PublicService {
	return PublicService{
		ID: s.ID, Category: s.Category, ProviderName: s.ProviderName,
		Title: s.Title, Summary: s.Summary, Details: s.Details,
		Audience: s.Audience, PriceLabel: s.PriceLabel,
		CampusScope: s.CampusScope, QualificationNote: s.QualificationNote,
		Sponsored: s.Sponsored, StartDate: s.StartDate, EndDate: s.EndDate,
	}
}

func (s Service) PublicSummary() PublicService {
	item := s.Public()
	item.Details = ""
	return item
}

func NormalizeService(service *Service, today string) {
	service.ID = strings.TrimSpace(service.ID)
	service.Category = strings.ToLower(strings.TrimSpace(service.Category))
	service.ProviderName = strings.TrimSpace(service.ProviderName)
	service.Title = strings.TrimSpace(service.Title)
	service.Summary = strings.TrimSpace(service.Summary)
	service.Details = strings.TrimSpace(service.Details)
	service.Audience = strings.TrimSpace(service.Audience)
	service.PriceLabel = strings.TrimSpace(service.PriceLabel)
	service.CampusScope = strings.ToLower(strings.TrimSpace(service.CampusScope))
	service.QualificationNote = strings.TrimSpace(service.QualificationNote)
	service.StartDate = strings.TrimSpace(service.StartDate)
	service.EndDate = strings.TrimSpace(service.EndDate)
	if service.CampusScope == "" {
		service.CampusScope = CampusAll
	}
	if service.StartDate == "" {
		service.StartDate = today
	}
}

func ValidateService(service Service) error {
	if !ValidID(service.ID) {
		return errors.New("校园服务 ID 无效")
	}
	if !ValidCategory(service.Category) {
		return errors.New("校园服务分类无效")
	}
	if service.ProviderName == "" || !validText(service.ProviderName, 100) {
		return errors.New("商家名称不能为空且不能超过 100 字")
	}
	if service.Title == "" || !validText(service.Title, 120) {
		return errors.New("服务标题不能为空且不能超过 120 字")
	}
	if !validMultilineText(service.Summary, 300) {
		return errors.New("服务摘要不能超过 300 字")
	}
	if service.Summary == "" && service.Details == "" {
		return errors.New("服务摘要和详情至少填写一项")
	}
	if !validMultilineText(service.Details, 6000) {
		return errors.New("服务详情不能超过 6000 字")
	}
	if !validText(service.Audience, 120) {
		return errors.New("适用人群不能超过 120 字")
	}
	if service.PriceLabel == "" || !validText(service.PriceLabel, 100) {
		return errors.New("价格说明不能为空且不能超过 100 字")
	}
	if !ValidCampusScope(service.CampusScope) {
		return errors.New("服务校区无效")
	}
	if !validText(service.QualificationNote, 200) {
		return errors.New("资质说明不能超过 200 字")
	}
	if !validDate(service.StartDate) {
		return errors.New("开始日期格式无效")
	}
	if service.EndDate != "" {
		if !validDate(service.EndDate) {
			return errors.New("结束日期格式无效")
		}
		if service.EndDate < service.StartDate {
			return errors.New("结束日期不能早于开始日期")
		}
	}
	if service.Priority < -100 || service.Priority > 100 {
		return errors.New("排序值必须在 -100 到 100 之间")
	}
	if service.Enabled && !service.Verified {
		return errors.New("服务上架前必须完成审核")
	}
	combined := strings.Join([]string{
		service.Title, service.Summary, service.Details,
		service.Audience, service.PriceLabel, service.QualificationNote,
	}, " ")
	for _, claim := range forbiddenClaims {
		if strings.Contains(combined, claim) {
			return fmt.Errorf("服务文案包含不允许的承诺：%s", claim)
		}
	}
	return nil
}

func ValidID(value string) bool {
	return serviceIDPattern.MatchString(strings.TrimSpace(value))
}

func ValidCategory(value string) bool {
	switch value {
	case CategoryOperator, CategoryMaterials, CategoryGraduate, CategoryExam:
		return true
	default:
		return false
	}
}

func ValidCampusScope(value string) bool {
	switch value {
	case CampusAll, CampusNanjing, CampusJiangyin:
		return true
	default:
		return false
	}
}

func ValidLeadStatus(value string) bool {
	switch value {
	case LeadStatusNew, LeadStatusContacted, LeadStatusConverted, LeadStatusInvalid:
		return true
	default:
		return false
	}
}

func NormalizeContact(contactType, raw string) (normalized, masked string, err error) {
	contactType = strings.ToLower(strings.TrimSpace(contactType))
	raw = strings.TrimSpace(raw)
	switch contactType {
	case ContactPhone:
		raw = strings.NewReplacer(" ", "", "-", "").Replace(raw)
		if !phonePattern.MatchString(raw) {
			return "", "", errors.New("请输入有效的 11 位手机号")
		}
		return raw, raw[:3] + "****" + raw[7:], nil
	case ContactWeChat:
		if !wechatPattern.MatchString(raw) {
			return "", "", errors.New("微信号需为 3-40 位字母、数字、下划线或短横线")
		}
		if len(raw) <= 4 {
			return raw, strings.Repeat("*", len(raw)), nil
		}
		return raw, raw[:2] + strings.Repeat("*", max(1, len(raw)-3)) + raw[len(raw)-1:], nil
	default:
		return "", "", errors.New("联系方式类型无效")
	}
}

func validDate(value string) bool {
	if len(value) != 10 {
		return false
	}
	_, err := time.Parse("2006-01-02", value)
	return err == nil
}

func validText(value string, maxRunes int) bool {
	if !utf8.ValidString(value) || utf8.RuneCountInString(value) > maxRunes {
		return false
	}
	for _, r := range value {
		if unicode.IsControl(r) || r == '<' || r == '>' {
			return false
		}
	}
	return true
}

func validMultilineText(value string, maxRunes int) bool {
	if !utf8.ValidString(value) || utf8.RuneCountInString(value) > maxRunes {
		return false
	}
	for _, r := range value {
		if r == '<' || r == '>' || (unicode.IsControl(r) && r != '\n' && r != '\r') {
			return false
		}
	}
	return true
}
