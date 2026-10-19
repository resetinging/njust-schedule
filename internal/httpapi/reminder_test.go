package httpapi

import (
	"testing"
	"time"

	"github.com/resetinging/njust-schedule/internal/store"
)

func bjTime(day, hour, minute int) time.Time {
	return time.Date(2026, time.October, day, hour, minute, 0, 0, beijing)
}

func TestGradeNextCheckPhases(t *testing.T) {
	started := bjTime(1, 0, 0)
	tests := []struct {
		name string
		now  time.Time
		want *time.Time
	}{
		{"first-week-morning", bjTime(1, 9, 0), timePtr(bjTime(1, 10, 0))},
		{"first-week-after-ten", bjTime(1, 10, 0), timePtr(bjTime(1, 14, 0))},
		{"middle-phase-start", bjTime(8, 5, 30), timePtr(bjTime(8, 6, 0))},
		{"middle-phase-next-day", bjTime(8, 23, 0), timePtr(bjTime(9, 6, 0))},
		{"last-phase", bjTime(22, 9, 0), timePtr(bjTime(22, 10, 0))},
		{"last-slot", bjTime(28, 17, 0), timePtr(bjTime(28, 18, 0))},
		{"expired", bjTime(28, 18, 0), nil},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got := gradeNextCheck(test.now, started)
			if test.want == nil {
				if got != nil {
					t.Fatalf("got %s, want nil", got)
				}
				return
			}
			if got == nil || !got.Equal(*test.want) {
				t.Fatalf("got %v, want %s", got, test.want)
			}
		})
	}
}

func TestReminderCourseTeacherIsolation(t *testing.T) {
	tasks := []store.ReminderTask{
		{CourseName: "高等数学（Ⅰ）", TeacherKey: "teacher-a"},
		{CourseName: "高等数学(I)", TeacherKey: "teacher-b"},
		{CourseName: "大学物理", TeacherKey: "teacher-c"},
	}
	ambiguous := ambiguousReminderNames(tasks)
	if !ambiguous[normalizeCourseName("高等数学（Ⅰ）")] || ambiguous[normalizeCourseName("大学物理")] {
		t.Fatalf("unexpected ambiguity map: %#v", ambiguous)
	}
	if _, ok := findExamForTask(tasks[0], []store.Exam{{CourseName: "高等数学（Ⅰ）"}}, ambiguous); ok {
		t.Fatal("same course with different teachers must not be auto-matched")
	}
	if exam, ok := findExamForTask(tasks[2], []store.Exam{{CourseName: "大学物理"}}, ambiguous); !ok || exam.CourseName != "大学物理" {
		t.Fatalf("unambiguous course did not match: %#v, %v", exam, ok)
	}
}

func TestReminderTasksForSemesterIsolatesAmbiguity(t *testing.T) {
	tasks := []store.ReminderTask{
		{Semester: "2026-2027-1", CourseName: "高等数学", TeacherKey: "teacher-a"},
		{Semester: "2025-2026-1", CourseName: "高等数学", TeacherKey: "teacher-b"},
	}
	current := reminderTasksForSemester(tasks, "2026-2027-第一学期")
	if len(current) != 1 || current[0].TeacherKey != "teacher-a" {
		t.Fatalf("unexpected semester tasks: %#v", current)
	}
	if ambiguousReminderNames(current)[normalizeCourseName("高等数学")] {
		t.Fatal("same course in a different semester caused a false ambiguity")
	}
}

func TestReminderExamGroupsSeparateSemesters(t *testing.T) {
	examTasks := []store.ReminderTask{
		{ID: 1, Semester: "2026-2027-1", Kind: "exam"},
		{ID: 2, Semester: "2025-2026-2", Kind: "exam"},
	}
	gradeTasks := []store.ReminderTask{
		{ID: 3, Semester: "2026-2027-第一学期", Kind: "grade", Stage: "pending_exam"},
		{ID: 4, Semester: "2025-2026-2", Kind: "grade", Stage: "wait_grade"},
		{ID: 5, Semester: "2024-2025-1", Kind: "grade", Stage: "pending_exam"},
	}
	groups := reminderExamGroups(examTasks, gradeTasks)
	if len(groups) != 3 {
		t.Fatalf("got %d groups, want 3: %#v", len(groups), groups)
	}
	if len(groups[0].examIndexes) != 1 || groups[0].examIndexes[0] != 0 || len(groups[0].pendingGradeIndexes) != 1 || groups[0].pendingGradeIndexes[0] != 0 {
		t.Fatalf("equivalent semester formats were not grouped: %#v", groups[0])
	}
	if len(groups[1].examIndexes) != 1 || len(groups[1].pendingGradeIndexes) != 0 {
		t.Fatalf("wait-grade task entered exam lookup group: %#v", groups[1])
	}
	if len(groups[2].examIndexes) != 0 || len(groups[2].pendingGradeIndexes) != 1 {
		t.Fatalf("pending task was not isolated by semester: %#v", groups[2])
	}
}

func TestGradeMatchesSemester(t *testing.T) {
	tests := []struct {
		name      string
		task      string
		gradeYear string
		gradeTerm string
		want      bool
	}{
		{name: "current numeric term", task: "2026-2027-1", gradeYear: "2026-2027", gradeTerm: "1", want: true},
		{name: "old academic year", task: "2026-2027-1", gradeYear: "2025-2026", gradeTerm: "1", want: false},
		{name: "first semester text", task: "2026-2027-1", gradeYear: "2026-2027学年", gradeTerm: "第一学期", want: true},
		{name: "second semester text", task: "2026-2027-2", gradeYear: "2026/2027", gradeTerm: "第二学期", want: true},
		{name: "different term", task: "2026-2027-1", gradeYear: "2026-2027", gradeTerm: "第二学期", want: false},
		{name: "missing term is ambiguous", task: "2026-2027-1", gradeYear: "2026-2027", gradeTerm: "", want: false},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			grade := store.Grade{AcademicYear: test.gradeYear, Semester: test.gradeTerm}
			if got := gradeMatchesSemester(test.task, grade); got != test.want {
				t.Fatalf("gradeMatchesSemester() = %v, want %v", got, test.want)
			}
		})
	}
}

func TestGradesForReminderTaskFiltersSameCourseAcrossSemesters(t *testing.T) {
	task := store.ReminderTask{Semester: "2026-2027-1", CourseName: "高等数学（Ⅰ）"}
	grades := []store.Grade{
		{AcademicYear: "2025-2026", Semester: "1", CourseName: "高等数学（Ⅰ）", Score: "82"},
		{AcademicYear: "2026-2027", Semester: "第一学期", CourseName: "高等数学(I)", Score: "91"},
		{AcademicYear: "2026-2027", Semester: "1", CourseName: "大学物理", Score: "88"},
	}
	matches := gradesForReminderTask(task, grades)
	if len(matches) != 1 || matches[0].Score != "91" {
		t.Fatalf("unexpected matches: %#v", matches)
	}
}

func timePtr(value time.Time) *time.Time { return &value }
