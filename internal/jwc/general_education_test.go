package jwc

import (
	"strings"
	"testing"
)

func TestParseGeneralEducationCatalogPage(t *testing.T) {
	raw := `<html><body>
<div>共13页</div>
<table id="dataList">
<tr><th>序号</th><th>开课学期</th><th>课程编号</th><th>课程名称</th><th>开课单位</th><th>学分</th><th>总学时</th><th>考核方式</th><th>课程属性</th><th>操作列</th></tr>
<tr><td>1</td><td></td><td>00010192</td><td>绿色生活与绿色技术</td><td>环境与生物工程学院</td><td>1</td><td>32</td><td>考查</td><td>任选</td><td><a onclick="kcdgView('ABC123')">课程大纲查看</a></td></tr>
<tr><td>2</td><td></td><td>00010195</td><td>智慧与成功</td><td>化学与化工学院</td><td>1</td><td>32</td><td>考查</td><td>公选</td><td></td></tr>
</table>
</body></html>`
	doc, err := parseDocument([]byte(raw))
	if err != nil {
		t.Fatal(err)
	}
	pages, err := generalEducationTotalPages(doc)
	if err != nil {
		t.Fatal(err)
	}
	if pages != 13 {
		t.Fatalf("pages = %d", pages)
	}
	values, err := parseGeneralEducationCatalogPage(doc, "2026-2027-1")
	if err != nil {
		t.Fatal(err)
	}
	if len(values) != 2 {
		t.Fatalf("courses = %#v", values)
	}
	if values[0].CourseCode != "00010192" || !values[0].HasSyllabus || values[0].SyllabusID != "ABC123" {
		t.Fatalf("first course = %#v", values[0])
	}
	if values[1].HasSyllabus || values[1].SyllabusID != "" {
		t.Fatalf("second course = %#v", values[1])
	}
}

func TestParseGeneralEducationSyllabus(t *testing.T) {
	raw := `<html><head><title>课程大纲查看</title></head><body>
<table id="dataList">
<tr><td>课程编号</td><td>00010192</td><td>课程名称(中)</td><td>绿色生活与绿色技术</td></tr>
<tr><td>开课单位</td><td>环境与生物工程学院</td><td>学分</td><td>1</td></tr>
<tr><td>课程介绍【课程背景】</td></tr>
<tr><td>课程围绕绿色生活与绿色技术展开。</td></tr>
<tr><td>教学目标</td></tr>
<tr><td>掌握绿色技术的基本方法。</td></tr>
</table>
</body></html>`
	doc, err := parseDocument([]byte(raw))
	if err != nil {
		t.Fatal(err)
	}
	value, err := parseGeneralEducationSyllabus(doc, "ABC123")
	if err != nil {
		t.Fatal(err)
	}
	if value.SyllabusID != "ABC123" || value.Title != "课程大纲查看" {
		t.Fatalf("syllabus = %#v", value)
	}
	if value.Fields["课程编号"] != "00010192" || value.Fields["学分"] != "1" {
		t.Fatalf("fields = %#v", value.Fields)
	}
	if !strings.Contains(value.RawText, "掌握绿色技术的基本方法") {
		t.Fatalf("raw text = %q", value.RawText)
	}
}
