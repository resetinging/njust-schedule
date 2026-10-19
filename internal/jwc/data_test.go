package jwc

import "testing"

func TestJSONParsersDiscardIncompleteRows(t *testing.T) {
	courses := parseCourseItems([]map[string]any{
		{},
		{"kcmc": "只有名称"},
		{"kcmc": "高等数学", "kcsj": "10102", "jsxm": "教师"},
	})
	if len(courses) != 1 || courses[0].Name != "高等数学" || courses[0].Day != 1 || courses[0].Start != 1 || courses[0].End != 2 {
		t.Fatalf("unexpected courses: %#v", courses)
	}

	exams := parseExamItems([]map[string]any{{}, {"ksrq": "2026-10-14"}, {"kcmc": "大学物理"}})
	if len(exams) != 1 || exams[0].CourseName != "大学物理" {
		t.Fatalf("unexpected exams: %#v", exams)
	}

	grades := parseGradeItems([]map[string]any{{}, {"cj": "90"}, {"kcmc": "大学英语", "cj": "90"}})
	if len(grades) != 1 || grades[0].CourseName != "大学英语" || grades[0].Score != "90" {
		t.Fatalf("unexpected grades: %#v", grades)
	}
}

func TestParseExamTableAcceptsEmptyStandardTable(t *testing.T) {
	doc, err := parseDocument([]byte(`<table id="dataList">
<tr><td>序号</td><td>考试场次</td><td>课程编号</td><td>课程名称</td><td>考试时间</td><td>考场</td><td>座位号</td></tr>
</table>`))
	if err != nil {
		t.Fatal(err)
	}
	values, ok := parseExamTable(doc)
	if !ok || len(values) != 0 {
		t.Fatalf("parseExamTable() ok=%v len=%d", ok, len(values))
	}
}

func TestParseGradeTableReadsLegacyColumns(t *testing.T) {
	doc, err := parseDocument([]byte(`<table id="dataList">
<tr><td>序号</td><td>开课学期</td><td>课程编号</td><td>课程名称</td><td>成绩</td><td>成绩标识</td><td>学分</td><td>总学时</td><td>考核方式</td><td>课程属性</td><td>课程性质</td></tr>
<tr><td>1</td><td>2024-2025-1</td><td>00010701</td><td>劳动教育理论</td><td>81</td><td></td><td>0.5</td><td>8</td><td>考查</td><td>必修</td><td>通识教育课</td></tr>
</table>`))
	if err != nil {
		t.Fatal(err)
	}
	values, ok := parseGradeTable(doc)
	if !ok || len(values) != 1 {
		t.Fatalf("parseGradeTable() ok=%v len=%d", ok, len(values))
	}
	if values[0].AcademicYear != "2024-2025" || values[0].Semester != "1" || values[0].CourseName != "劳动教育理论" {
		t.Fatalf("grade = %#v", values[0])
	}
	if values[0].GradePoint != 0 {
		t.Fatalf("grade point without a 绩点 column = %v, want 0", values[0].GradePoint)
	}
}
