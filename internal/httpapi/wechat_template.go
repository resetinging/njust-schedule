package httpapi

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"strings"
	"time"
)

const (
	wechatTemplateListPath = "/wxaapi/newtmpl/gettemplate"
	wechatTemplateCacheTTL = 6 * time.Hour
	wechatTemplateRetryTTL = 5 * time.Minute
)

var wechatTemplatePlaceholder = regexp.MustCompile(`\{\{\s*([A-Za-z0-9_]+)\.DATA\s*\}\}`)

type wechatTemplateField struct {
	Key  string `json:"key"`
	Name string `json:"name"`
}

type wechatTemplateValues struct {
	Topic    string
	Course   string
	Date     string
	Time     string
	Location string
	Duration string
	Detail   string
}

func (s *Server) templateFields(ctx context.Context, kind, templateID string) []wechatTemplateField {
	templateID = strings.TrimSpace(templateID)
	if templateID == "" {
		return fallbackTemplateFields(kind)
	}
	cacheKey := "wechat-template-fields:" + templateID
	if s.cache != nil {
		if value, ok := s.cacheGet(cacheKey); ok {
			if fields, valid := value.([]wechatTemplateField); valid && len(fields) > 0 {
				return fields
			}
		}
		retryKey := cacheKey + ":fallback"
		if _, ok := s.cacheGet(retryKey); ok {
			return fallbackTemplateFields(kind)
		}
	}
	fields, err := s.fetchTemplateFields(ctx, templateID)
	if err == nil && len(fields) > 0 {
		if s.cache != nil {
			s.cacheSet(cacheKey, fields, wechatTemplateCacheTTL)
			s.cacheDeletePrefix(cacheKey + ":fallback")
		}
		return fields
	}
	if err != nil && s.logger != nil {
		s.logger.Warn("读取微信订阅模板字段失败，使用兜底字段", "kind", kind, "error", err)
	}
	if s.cache != nil {
		s.cacheSet(cacheKey+":fallback", true, wechatTemplateRetryTTL)
	}
	return fallbackTemplateFields(kind)
}

func (s *Server) fetchTemplateFields(ctx context.Context, templateID string) ([]wechatTemplateField, error) {
	endpoint := wechatCloudBaseURL + wechatTemplateListPath
	client := wechatCloudClient
	requireCloudRun := true
	if s.wechatOpenAPIMode() != "cloudrun" {
		token, err := s.wechatAccessToken(ctx)
		if err != nil {
			return nil, err
		}
		endpoint = wechatPublicBaseURL + wechatTemplateListPath + "?access_token=" + url.QueryEscape(token)
		client = wechatHTTPClient
		requireCloudRun = false
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return nil, fmt.Errorf("创建模板字段请求失败")
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("请求模板字段失败: %w", sanitizeWechatError(err))
	}
	defer resp.Body.Close()
	if requireCloudRun && strings.TrimSpace(resp.Header.Get("x-openapi-seqid")) == "" {
		return nil, fmt.Errorf("云调用链路未生效(x-openapi-seqid 缺失)")
	}
	var payload struct {
		ErrCode int    `json:"errcode"`
		ErrMsg  string `json:"errmsg"`
		Data    []struct {
			PriTmplID string          `json:"priTmplId"`
			Content   json.RawMessage `json:"content"`
		} `json:"data"`
	}
	if err := decodeWechatResponse(resp.Body, &payload); err != nil {
		return nil, fmt.Errorf("解析模板字段失败: %w", err)
	}
	if payload.ErrCode != 0 {
		return nil, fmt.Errorf("读取模板字段失败: %d %s", payload.ErrCode, payload.ErrMsg)
	}
	for _, item := range payload.Data {
		if item.PriTmplID != templateID {
			continue
		}
		if fields := parseTemplateContent(item.Content); len(fields) > 0 {
			return fields, nil
		}
	}
	return nil, fmt.Errorf("未找到模板 %s 的字段定义", templateID)
}

func parseTemplateContent(raw json.RawMessage) []wechatTemplateField {
	value := strings.TrimSpace(string(raw))
	if value == "" || value == "null" {
		return nil
	}
	switch value[0] {
	case '[':
		var fields []wechatTemplateField
		if json.Unmarshal([]byte(value), &fields) != nil {
			return nil
		}
		out := make([]wechatTemplateField, 0, len(fields))
		for _, field := range fields {
			field.Key = strings.TrimSpace(field.Key)
			field.Name = strings.TrimSpace(field.Name)
			if field.Key != "" {
				out = append(out, field)
			}
		}
		return out
	case '"':
		var content string
		if json.Unmarshal([]byte(value), &content) != nil {
			return nil
		}
		return parseTemplateText(content)
	default:
		return nil
	}
}

func parseTemplateText(content string) []wechatTemplateField {
	matches := wechatTemplatePlaceholder.FindAllStringSubmatchIndex(content, -1)
	if len(matches) == 0 {
		return nil
	}
	fields := make([]wechatTemplateField, 0, len(matches))
	seen := make(map[string]bool, len(matches))
	previousEnd := 0
	for _, match := range matches {
		key := strings.TrimSpace(content[match[2]:match[3]])
		if key == "" || seen[key] {
			previousEnd = match[1]
			continue
		}
		name := templateFieldName(content[previousEnd:match[0]])
		fields = append(fields, wechatTemplateField{Key: key, Name: name})
		seen[key] = true
		previousEnd = match[1]
	}
	return fields
}

func templateFieldName(prefix string) string {
	if index := strings.LastIndexAny(prefix, "\r\n"); index >= 0 {
		prefix = prefix[index+1:]
	}
	name := strings.Trim(prefix, " \t\r\n:：,，;；|、-—_")
	if len([]rune(name)) > 40 {
		return ""
	}
	return name
}

func fallbackTemplateFields(kind string) []wechatTemplateField {
	envName := "SUBSCRIBE_TPL_" + strings.ToUpper(kind) + "_FIELDS"
	if raw := strings.TrimSpace(os.Getenv(envName)); raw != "" {
		fields := make([]wechatTemplateField, 0)
		for _, key := range strings.Split(raw, ",") {
			if key = strings.TrimSpace(key); key != "" {
				fields = append(fields, wechatTemplateField{Key: key})
			}
		}
		if len(fields) > 0 {
			return fields
		}
	}
	return []wechatTemplateField{
		{Key: "thing1", Name: "日程主题"},
		{Key: "thing2", Name: "时长"},
		{Key: "time3", Name: "时间"},
		{Key: "thing4", Name: "地点"},
		{Key: "thing5", Name: "备注"},
	}
}

func buildWechatTemplateData(fields []wechatTemplateField, values wechatTemplateValues) map[string]any {
	out := make(map[string]any, len(fields))
	eventTime := strings.TrimSpace(values.Date + " " + values.Time)
	for _, field := range fields {
		key := strings.TrimSpace(field.Key)
		if key == "" {
			continue
		}
		name := strings.TrimSpace(field.Name)
		keyType := strings.TrimRight(key, "0123456789")
		value := values.Topic
		switch {
		case keyType == "date":
			value = values.Date
		case keyType == "time" || strings.Contains(name, "日期") || strings.Contains(name, "时间"):
			value = eventTime
		case strings.Contains(name, "课程") || strings.Contains(name, "科目"):
			value = values.Course
		case strings.Contains(name, "主题") || strings.Contains(name, "名称") || strings.Contains(name, "考试"):
			value = values.Topic
		case strings.Contains(name, "地点") || strings.Contains(name, "考场") || strings.Contains(name, "教室") || strings.Contains(name, "地址"):
			value = values.Location
		case strings.Contains(name, "时长"):
			value = values.Duration
		case strings.Contains(name, "备注") || strings.Contains(name, "说明") || strings.Contains(name, "结果") || strings.Contains(name, "成绩") || strings.Contains(name, "详情"):
			value = values.Detail
		case name == "":
			value = fallbackTemplateValue(key, values)
		}
		if strings.TrimSpace(value) == "" {
			value = defaultText(values.Detail, defaultText(values.Topic, "考试提醒"))
		}
		out[key] = map[string]string{"value": clipRunes(value, 20)}
	}
	return out
}

func fallbackTemplateValue(key string, values wechatTemplateValues) string {
	switch key {
	case "thing1":
		return values.Topic
	case "thing2":
		return values.Duration
	case "time3":
		return strings.TrimSpace(values.Date + " " + values.Time)
	case "thing4":
		return values.Location
	case "thing5":
		return values.Detail
	default:
		return defaultText(values.Course, defaultText(values.Detail, values.Topic))
	}
}
