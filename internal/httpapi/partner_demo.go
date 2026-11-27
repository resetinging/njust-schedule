package httpapi

import (
	"net/http"
	"time"

	"github.com/resetinging/njust-schedule/internal/store"
)

func writePartnerDemoRefresh(w http.ResponseWriter, label string) {
	writeJSON(w, http.StatusOK, map[string]any{
		"success": true, "refreshed": false, "partner_mode": true, "demo_mode": true,
		"message": "合作商验收账号当前展示" + label + "演示数据，无需刷新",
	})
}

func partnerDemoCourses() []store.Course {
	return []store.Course{
		{
			ID: 910001, Name: "高等数学（Ⅰ）", Teacher: "张老师", Classroom: "Ⅰ-A201",
			Day: 1, Start: 1, End: 2, Weeks: "1-16", WeekType: 0,
			Credits: "5", CourseType: "必修",
		},
		{
			ID: 910002, Name: "大学英语（Ⅲ）", Teacher: "李老师", Classroom: "Ⅱ-B305",
			Day: 2, Start: 3, End: 4, Weeks: "1-16", WeekType: 0,
			Credits: "2", CourseType: "必修",
		},
		{
			ID: 910003, Name: "数据结构", Teacher: "陈老师", Classroom: "Ⅲ-C402",
			Day: 1, Start: 5, End: 6, Weeks: "1-16", WeekType: 0,
			Credits: "4", CourseType: "必修",
		},
		{
			ID: 910004, Name: "大学物理（Ⅱ）", Teacher: "王老师", Classroom: "Ⅰ-B102",
			Day: 2, Start: 7, End: 8, Weeks: "1-16", WeekType: 0,
			Credits: "4", CourseType: "必修",
		},
		{
			ID: 910005, Name: "概率论与数理统计", Teacher: "赵老师", Classroom: "Ⅱ-A210",
			Day: 3, Start: 1, End: 2, Weeks: "1-16", WeekType: 0,
			Credits: "3", CourseType: "必修",
		},
		{
			ID: 910006, Name: "体育（Ⅲ）", Teacher: "周老师", Classroom: "东区体育场",
			Day: 4, Start: 3, End: 4, Weeks: "1-12", WeekType: 0,
			Credits: "1", CourseType: "必修",
		},
	}
}

func partnerDemoExams() []store.Exam {
	now := time.Now().In(beijing)
	return []store.Exam{
		{
			ID: 920001, CourseName: "数据结构", Date: now.AddDate(0, 0, 20).Format("2006-01-02"),
			Time: "09:00~11:00", Location: "Ⅲ-C402", Seat: "示例座位 12", Type: "期末考试",
		},
		{
			ID: 920002, CourseName: "概率论与数理统计", Date: now.AddDate(0, 0, 22).Format("2006-01-02"),
			Time: "14:00~16:00", Location: "Ⅱ-A210", Seat: "示例座位 08", Type: "期末考试",
		},
		{
			ID: 920003, CourseName: "大学英语（Ⅲ）", Date: now.AddDate(0, 0, 24).Format("2006-01-02"),
			Time: "09:00~11:00", Location: "Ⅱ-B305", Seat: "示例座位 21", Type: "期末考试",
		},
	}
}

func partnerDemoGrades() []store.Grade {
	return []store.Grade{
		{
			ID: 930001, AcademicYear: "2025-2026", Semester: "1",
			CourseCode: "MATH1001", CourseName: "高等数学（Ⅰ）", Score: "89",
			Credit: 5, GradePoint: 3.8, CourseType: "考试", CourseNature: "必修", ExamType: "期末考试",
		},
		{
			ID: 930002, AcademicYear: "2025-2026", Semester: "1",
			CourseCode: "ENG1001", CourseName: "大学英语（Ⅰ）", Score: "86",
			Credit: 3, GradePoint: 3.6, CourseType: "考试", CourseNature: "必修", ExamType: "期末考试",
		},
		{
			ID: 930003, AcademicYear: "2025-2026", Semester: "1",
			CourseCode: "CS1001", CourseName: "程序设计基础", Score: "92",
			Credit: 3, GradePoint: 4.0, CourseType: "考试", CourseNature: "必修", ExamType: "期末考试",
		},
		{
			ID: 930004, AcademicYear: "2025-2026", Semester: "1",
			CourseCode: "PHY1001", CourseName: "大学物理（Ⅰ）", Score: "84",
			Credit: 4, GradePoint: 3.3, CourseType: "考试", CourseNature: "必修", ExamType: "期末考试",
		},
		{
			ID: 930005, AcademicYear: "2025-2026", Semester: "1",
			CourseCode: "PE1001", CourseName: "体育（Ⅰ）", Score: "90",
			Credit: 1, GradePoint: 4.0, CourseType: "考查", CourseNature: "必修", ExamType: "考查",
		},
		{
			ID: 930006, AcademicYear: "2025-2026", Semester: "2",
			CourseCode: "MATH1002", CourseName: "线性代数", Score: "88",
			Credit: 3, GradePoint: 3.7, CourseType: "考试", CourseNature: "必修", ExamType: "期末考试",
		},
		{
			ID: 930007, AcademicYear: "2025-2026", Semester: "2",
			CourseCode: "CS1002", CourseName: "数据结构", Score: "91",
			Credit: 4, GradePoint: 4.0, CourseType: "考试", CourseNature: "必修", ExamType: "期末考试",
		},
		{
			ID: 930008, AcademicYear: "2025-2026", Semester: "2",
			CourseCode: "ENG1002", CourseName: "大学英语（Ⅱ）", Score: "85",
			Credit: 3, GradePoint: 3.5, CourseType: "考试", CourseNature: "必修", ExamType: "期末考试",
		},
		{
			ID: 930009, AcademicYear: "2025-2026", Semester: "2",
			CourseCode: "PHY1002", CourseName: "大学物理（Ⅱ）", Score: "83",
			Credit: 4, GradePoint: 3.3, CourseType: "考试", CourseNature: "必修", ExamType: "期末考试",
		},
		{
			ID: 930010, AcademicYear: "2025-2026", Semester: "2",
			CourseCode: "PE1002", CourseName: "体育（Ⅱ）", Score: "92",
			Credit: 1, GradePoint: 4.0, CourseType: "考查", CourseNature: "必修", ExamType: "考查",
		},
	}
}

func partnerDemoCETScores() []store.CETScore {
	return []store.CETScore{
		{Type: "CET4", Score: 528, ExamDate: "2025-06"},
		{Type: "CET6", Score: 486, ExamDate: "2025-12"},
	}
}

func partnerDemoAvailableSemesters() []string {
	return []string{"2025-2026-2", "2025-2026-1"}
}

func partnerDemoProgramme() map[string]any {
	current := currentSemester()
	courses := []map[string]any{
		{"code": "MATH1001", "name": "高等数学（Ⅰ）", "credit": 5, "semester": "2025-2026-1", "attribute": "必修"},
		{"code": "ENG1001", "name": "大学英语（Ⅰ）", "credit": 3, "semester": "2025-2026-1", "attribute": "必修"},
		{"code": "CS1001", "name": "程序设计基础", "credit": 3, "semester": "2025-2026-1", "attribute": "必修"},
		{"code": "PHY1001", "name": "大学物理（Ⅰ）", "credit": 4, "semester": "2025-2026-1", "attribute": "必修"},
		{"code": "PE1001", "name": "体育（Ⅰ）", "credit": 1, "semester": "2025-2026-1", "attribute": "必修"},
		{"code": "MATH1002", "name": "线性代数", "credit": 3, "semester": "2025-2026-2", "attribute": "必修"},
		{"code": "CS1002", "name": "数据结构", "credit": 4, "semester": "2025-2026-2", "attribute": "必修"},
		{"code": "ENG1002", "name": "大学英语（Ⅱ）", "credit": 3, "semester": "2025-2026-2", "attribute": "必修"},
		{"code": "PHY1002", "name": "大学物理（Ⅱ）", "credit": 4, "semester": "2025-2026-2", "attribute": "必修"},
		{"code": "PE1002", "name": "体育（Ⅱ）", "credit": 1, "semester": "2025-2026-2", "attribute": "必修"},
		{"code": "MATH2001", "name": "概率论与数理统计", "credit": 3, "semester": current, "attribute": "必修"},
		{"code": "CS2003", "name": "操作系统", "credit": 4, "semester": current, "attribute": "必修"},
		{"code": "ENG2002", "name": "大学英语（Ⅲ）", "credit": 2, "semester": current, "attribute": "必修"},
		{"code": "PE2001", "name": "体育（Ⅲ）", "credit": 1, "semester": current, "attribute": "必修"},
		{"code": "GE2001", "name": "通识教育选修课（示例）", "credit": 2, "semester": current, "attribute": "任选"},
	}
	return map[string]any{
		"success": true, "supported": true, "partner_mode": true, "demo_mode": true,
		"courses": courses, "count": len(courses), "fetched_at": time.Now().Unix(),
	}
}
