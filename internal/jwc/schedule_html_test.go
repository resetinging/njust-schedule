package jwc

import "testing"

func TestParseMergedScheduleKeepsWeekAndRoomVariants(t *testing.T) {
	html := `<table id="kbtable">
<tr><th>节次</th><th>星期一</th><th>星期二</th><th>星期三</th><th>星期四</th><th>星期五</th></tr>
<tr><td>第四大节</td><td></td><td></td><td></td><td></td><td>
<div class="kbcontent">机器人结构设计及分析<br/><font title="老师">谢中取</font><br/><font title="周次(节次)">3,5,7-10(周)</font><br/><font title="教室">Ⅳ-C201</font><br/></div>
<div class="kbcontent">机器人结构设计及分析<br/><font title="老师">谢中取</font><br/><font title="周次(节次)">18(周)</font><br/><font title="教室">Ⅳ-C203</font><br/></div>
</td></tr>
<tr><td>中午</td><td></td><td>
<div class="kbcontent">模拟与数字电路综合实验<br/><font title="老师">刘学敏</font><br/><font title="周次(节次)">15-16(周)</font><br/></div>
</td><td></td><td></td><td></td></tr>
</table>
<table id="dataList">
<tr><td>序号</td><td>课程</td><td>编号</td><td>课程名称</td><td>教师</td><td>时间</td><td>学分</td><td>地点</td><td>类型</td></tr>
<tr><td>1</td><td></td><td></td><td>机器人结构设计及分析</td><td>谢中取</td><td>星期一(08-09小节)<br/>星期一(08-09小节)</td><td>2</td><td></td><td>专业必修课</td></tr>
<tr><td>2</td><td></td><td></td><td>模拟与数字电路综合实验</td><td>刘学敏</td><td>星期二(14-14小节)</td><td>1</td><td></td><td>实践课</td></tr>
</table>`
	doc, err := parseDocument([]byte(html))
	if err != nil {
		t.Fatal(err)
	}
	values := parseScheduleDocument(doc)
	if len(values) != 3 {
		t.Fatalf("course count = %d, want 3: %#v", len(values), values)
	}
	if values[0].Classroom != "Ⅳ-C201" || values[0].Weeks != "3,5,7-10" {
		t.Fatalf("first course = %#v", values[0])
	}
	if values[1].Classroom != "Ⅳ-C203" || values[1].Weeks != "18" {
		t.Fatalf("second course = %#v", values[1])
	}
	if values[2].Classroom != "" || values[2].Weeks != "15-16" {
		t.Fatalf("course without classroom = %#v", values[2])
	}
}
