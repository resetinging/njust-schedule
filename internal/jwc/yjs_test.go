package jwc

import "testing"

func TestParseGraduateCoursesPreservesMultipleCourses(t *testing.T) {
	raw := []byte(`
<html><body>
<select><option>2026-2027第一学期</option></select>
<table id="ctl00_ContentPlaceHolder1_dgData">
  <tr><th>时段</th><th>节次</th><th>星期一</th><th>星期二</th></tr>
  <tr>
    <td rowspan="2">上午</td><td>1</td>
    <td rowspan="2">算法设计 1班 {1-8周 [教师:张三、李四, 地点:Ⅳ-A303]}<br/>机器学习 {9－16周 [教师:王五,地点:Ⅱ-201]}</td>
    <td></td>
  </tr>
  <tr><td>2</td><td></td></tr>
</table>
</body></html>`)

	courses, semesters, err := ParseGraduateCourses(raw)
	if err != nil {
		t.Fatal(err)
	}
	if len(semesters) != 1 || semesters[0] != "2026-2027第一学期" {
		t.Fatalf("unexpected semesters: %#v", semesters)
	}
	if len(courses) != 2 {
		t.Fatalf("courses = %#v", courses)
	}
	if courses[0].Name != "算法设计" || courses[0].Teacher != "张三、李四" || courses[0].Classroom != "Ⅳ-A303" {
		t.Fatalf("unexpected first course: %#v", courses[0])
	}
	if courses[0].Start != 1 || courses[0].End != 2 || courses[0].Day != 1 || courses[0].Weeks != "1-8" {
		t.Fatalf("unexpected first schedule: %#v", courses[0])
	}
	if courses[1].Name != "机器学习" || courses[1].Weeks != "9-16" {
		t.Fatalf("unexpected second course: %#v", courses[1])
	}
}

func TestSplitCellLinesSupportsBlockElements(t *testing.T) {
	raw := []byte(`<table id="x_dgData"><tr><th>时段</th><th>节次</th><th>星期一</th></tr><tr><td>上午</td><td>1</td><td><div>课程甲 {1周 [教师:甲,地点:A101]}</div><div>课程乙 {2周 [教师:乙,地点:A102]}</div></td></tr></table>`)
	courses, _, err := ParseGraduateCourses(raw)
	if err != nil {
		t.Fatal(err)
	}
	if len(courses) != 2 {
		t.Fatalf("courses = %#v", courses)
	}
}
