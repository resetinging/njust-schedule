package jwc

import (
	"fmt"
	"strings"
	"testing"
)

func TestParseAuditCatalogTable(t *testing.T) {
	var html strings.Builder
	html.WriteString(`<table id="kbtable"><tr><th>课程名称</th>`)
	for day := 1; day <= 7; day++ {
		html.WriteString(fmt.Sprintf(`<th colspan="6">星期%d</th>`, day))
	}
	html.WriteString(`</tr><tr><th>课程</th>`)
	for day := 1; day <= 7; day++ {
		for _, period := range []string{"1-3", "4-5", "6-7", "8-10", "11-13", "中午"} {
			html.WriteString(fmt.Sprintf(`<th>%s</th>`, period))
		}
	}
	html.WriteString(`</tr><tr><td>高等数学</td>`)
	html.WriteString(`<td><div class="kbcontent">9241011701,9241011702<br/>陈刚<br/>(2,5-6周)<br/>Ⅳ-A303</div><div class="kbcontent1">9241011701,9241011702<br/>陈刚<br/>(2,5-6周)<br/>Ⅳ-A303</div></td>`)
	for index := 1; index < 42; index++ {
		html.WriteString(`<td></td>`)
	}
	html.WriteString(`</tr></table>`)
	doc, err := parseDocument([]byte(html.String()))
	if err != nil {
		t.Fatal(err)
	}
	values := parseAuditTable(doc.Find("table#kbtable").First())
	if len(values) != 1 {
		t.Fatalf("catalog rows = %d, want 1: %#v", len(values), values)
	}
	value := values[0]
	if value.Name != "高等数学" || value.ClassInfo != "9241011701,9241011702" ||
		value.Teacher != "陈刚" || value.Classroom != "Ⅳ-A303" ||
		value.Day != 1 || value.Start != 1 || value.End != 3 || value.Weeks != "2,5-6" {
		t.Fatalf("catalog course = %#v", value)
	}
}
