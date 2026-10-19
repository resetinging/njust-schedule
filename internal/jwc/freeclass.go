package jwc

import (
	"context"
	"fmt"
	"net/http"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/PuerkitoBio/goquery"
)

const borrowQueryURL = JWBase + "/kbxx/jsjy_query"

type FreeClassroomResult struct {
	Rooms        []string `json:"rooms"`
	JC1          int      `json:"jc1"`
	JC2          int      `json:"jc2"`
	BuildingName string   `json:"building_name"`
	Buildings    []string `json:"buildings"`
}

func (c *Client) FreeClassrooms(ctx context.Context, campus string, weekday, jc1, jc2, week int, semester, building string) (FreeClassroomResult, error) {
	resp, err := c.request(ctx, http.MethodGet, borrowQueryURL, nil)
	if err != nil {
		return FreeClassroomResult{}, err
	}
	raw, err := readResponse(resp)
	if err != nil {
		return FreeClassroomResult{}, err
	}
	if c.isLoginPage(resp, raw) {
		return FreeClassroomResult{}, ErrSessionExpired
	}
	doc, err := parseDocument(raw)
	if err != nil {
		return FreeClassroomResult{}, fmt.Errorf("解析教室借用查询页: %w", err)
	}
	form := doc.Find("form[name='Form1']").First()
	if form.Length() == 0 {
		form = doc.Find("form").First()
	}
	semSelect := doc.Find("select[name='xnxqh']").First()
	if form.Length() == 0 || semSelect.Length() == 0 {
		return FreeClassroomResult{}, fmt.Errorf("教室借用页未找到查询表单")
	}
	validSem := false
	currentSem := ""
	semSelect.Find("option").Each(func(_ int, o *goquery.Selection) {
		value, _ := o.Attr("value")
		if value == semester {
			validSem = true
		}
		if _, selected := o.Attr("selected"); selected && value != "" {
			currentSem = value
		}
	})
	if !validSem {
		semester = currentSem
	}
	campusCode := map[string]string{"孝陵卫": "01", "江阴": "4y"}[campus]
	doc.Find("select[name='xqbh'] option").Each(func(_ int, o *goquery.Selection) {
		text := strings.TrimSpace(o.Text())
		value, _ := o.Attr("value")
		if strings.HasPrefix(text, campus) && value != "" {
			campusCode = value
		}
	})
	if campusCode == "" {
		campusCode = "01"
	}
	if weekday < 1 || weekday > 7 {
		weekday = 1
	}
	if week < 1 || week > 30 {
		week = 1
	}
	if jc1 < 1 || jc1 > 13 || jc2 < jc1 || jc2 > 13 {
		jc1, jc2 = 6, 7
	}
	parsed := parseForm(form)
	if err = validatePostForm(parsed); err != nil {
		return FreeClassroomResult{}, err
	}
	target, err := resolveFormURL(resp.Request.URL.String(), parsed.Action)
	if err != nil {
		return FreeClassroomResult{}, err
	}
	values := parsed.Values
	for key, value := range map[string]string{"typewhere": "jszq", "xnxqh": semester, "xqbh": campusCode, "jxqbh": "", "jxlbh": "", "jsbh": "", "bjfh": "=", "rnrs": "", "jszt": "5", "zc": strconv.Itoa(week), "zc2": strconv.Itoa(week), "xq": strconv.Itoa(weekday), "xq2": strconv.Itoa(weekday), "jc": fmt.Sprintf("%02d", jc1), "jc2": fmt.Sprintf("%02d", jc2)} {
		values.Set(key, value)
	}
	resultResp, err := c.request(ctx, http.MethodPost, target, values)
	if err != nil {
		return FreeClassroomResult{}, err
	}
	resultRaw, err := readResponse(resultResp)
	if err != nil {
		return FreeClassroomResult{}, err
	}
	if c.isLoginPage(resultResp, resultRaw) {
		return FreeClassroomResult{}, ErrSessionExpired
	}
	rooms, err := parseFreeRooms(resultRaw)
	if err != nil {
		return FreeClassroomResult{}, err
	}
	if building != "" {
		filtered := rooms[:0]
		for _, room := range rooms {
			if strings.HasPrefix(room, building) {
				filtered = append(filtered, room)
			}
		}
		rooms = filtered
	}
	buildingsSet := map[string]bool{}
	for _, room := range rooms {
		if i := strings.IndexAny(room, "-0123456789"); i > 0 {
			buildingsSet[room[:i]] = true
		}
	}
	buildings := sortedKeysLocal(buildingsSet)
	return FreeClassroomResult{rooms, jc1, jc2, building, buildings}, nil
}

func parseFreeRooms(raw []byte) ([]string, error) {
	doc, err := parseDocument(raw)
	if err != nil {
		return nil, fmt.Errorf("解析教室借用结果页: %w", err)
	}
	if doc.Find("form").Length() == 0 || doc.Find("table#dataList").Length() == 0 {
		return nil, fmt.Errorf("教室借用结果缺少表单或表格")
	}
	seen := map[string]bool{}
	var rooms []string
	doc.Find("table#dataList tr").Each(func(_ int, row *goquery.Selection) {
		checkbox := row.Find("input[name='jsids']").First()
		if checkbox.Length() == 0 {
			return
		}
		cells := row.Find("td,th")
		nameIndex := -1
		cells.EachWithBreak(func(i int, cell *goquery.Selection) bool {
			if cell.Find("input[name='jsids']").Length() > 0 {
				nameIndex = i
				return false
			}
			return true
		})
		if nameIndex < 0 {
			return
		}
		texts := selectionTexts(cells)
		for i, text := range texts {
			if i != nameIndex && text != "" && text != "空闲" && text != "空" {
				return
			}
		}
		name := formatRoom(at(texts, nameIndex))
		if name != "" && !seen[name] {
			seen[name] = true
			rooms = append(rooms, name)
		}
	})
	sort.Strings(rooms)
	return rooms, nil
}

var capacitySuffix = regexp.MustCompile(`\(.*?\)`)
var roomMappings = []struct{ Prefix, Label string }{{"江阴大学物理实验中心", "大学物理实验中心"}, {"江阴工训中心阶梯教室", "工程训练中心阶梯教室"}, {"创新创业教育学院", "创新创业教育学院"}, {"基础教学实验楼", "基础教学实验楼"}, {"工程训练中心A", "工程训练中心A"}, {"工程训练中心B", "工程训练中心B"}, {"工程训练中心C", "工程训练中心C"}, {"体育中心健美操房", "体育中心"}, {"体育中心南二层门厅", "体育中心"}, {"体育中心乒乓球馆", "体育中心"}, {"体育中心武术馆", "体育中心"}, {"体育中心训练馆", "体育中心"}, {"物理实验中心", "物理实验中心"}, {"物理实验室", "物理实验中心"}, {"江阴致源B", "致源楼B"}, {"江阴格物A", "格物楼A"}, {"江阴格物B", "格物楼B"}, {"江阴格物C", "格物楼C"}, {"江阴致远A", "致远楼A"}, {"江阴致真A", "致真楼A"}, {"江阴致理A", "致理楼A"}, {"江阴致新B", "致新楼B"}, {"江阴致知B", "致知楼B"}, {"江阴致道A", "致道楼A"}, {"江阴创新港B", "创新港B"}, {"江阴创新港C", "创新港C"}, {"江阴工训中心", "工程训练中心"}, {"江阴图书馆", "图书馆"}, {"江阴至善A", "至善楼A"}, {"逸夫楼", "逸夫教学楼"}, {"兵博", "兵器博物馆"}, {"艺文馆", "艺文馆"}, {"理学院", "理学院"}, {"体育中心", "体育中心"}, {"二运篮球场", "第二运动场篮球场"}, {"345", "东区平房"}, {"Ⅳ", "Ⅳ教学楼"}, {"III", "Ⅲ教学楼"}, {"Ⅲ", "Ⅲ教学楼"}, {"II", "Ⅱ教学楼"}, {"Ⅱ", "Ⅱ教学楼"}, {"IV", "Ⅳ教学楼"}, {"Ⅰ", "Ⅰ教学楼"}, {"I", "Ⅰ教学楼"}}

func formatRoom(raw string) string {
	name := strings.Join(strings.Fields(capacitySuffix.ReplaceAllString(raw, "")), " ")
	if name == "" || name == "线上" || name == "其它教室" {
		return ""
	}
	for _, item := range roomMappings {
		if strings.HasPrefix(name, item.Prefix) {
			rest := strings.TrimPrefix(name, item.Prefix)
			if rest == "" {
				return name
			}
			return item.Label + rest
		}
	}
	return ""
}
func sortedKeysLocal(values map[string]bool) []string {
	out := make([]string, 0, len(values))
	for value := range values {
		out = append(out, value)
	}
	sort.Strings(out)
	return out
}
