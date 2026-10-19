package store

import (
	"context"
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
)

func TestLegacyNullableStudentDataUsesSQLDefaults(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	ctx := context.Background()
	s := New(db)

	mock.ExpectQuery("SELECT id,COALESCE\\(name").WithArgs("sid", "semester").WillReturnRows(
		sqlmock.NewRows([]string{"id", "name", "teacher", "classroom", "day", "start", "end", "weeks", "week_type", "credits", "course_type", "raw_data"}).
			AddRow(1, "", "", "", 0, 0, 0, "", 0, "", "", ""),
	)
	if values, queryErr := s.Courses(ctx, "sid", "semester"); queryErr != nil || len(values) != 1 {
		t.Fatalf("courses=%#v err=%v", values, queryErr)
	}

	mock.ExpectQuery("SELECT id,COALESCE\\(course_name").WithArgs("sid", "semester").WillReturnRows(
		sqlmock.NewRows([]string{"id", "course_name", "exam_date", "exam_time", "location", "seat", "exam_type"}).
			AddRow(1, "", "", "", "", "", "期末考试"),
	)
	if values, queryErr := s.Exams(ctx, "sid", "semester"); queryErr != nil || len(values) != 1 {
		t.Fatalf("exams=%#v err=%v", values, queryErr)
	}

	mock.ExpectQuery("SELECT id,COALESCE\\(academic_year").WithArgs("sid").WillReturnRows(
		sqlmock.NewRows([]string{"id", "academic_year", "semester", "course_code", "course_name", "score", "credit", "grade_point", "course_type", "course_nature", "exam_type"}).
			AddRow(1, "", "", "", "", "", 0, 0, "", "", "正常考试"),
	)
	if values, queryErr := s.Grades(ctx, "sid", "", ""); queryErr != nil || len(values) != 1 {
		t.Fatalf("grades=%#v err=%v", values, queryErr)
	}

	mock.ExpectQuery("SELECT COALESCE\\(cet_type").WithArgs("sid").WillReturnRows(
		sqlmock.NewRows([]string{"cet_type", "total_score", "exam_date"}).AddRow("", 0, ""),
	)
	if values, queryErr := s.CETScores(ctx, "sid"); queryErr != nil || len(values) != 1 {
		t.Fatalf("cet=%#v err=%v", values, queryErr)
	}

	mock.ExpectQuery("SELECT id,COALESCE\\(semester").WithArgs("sid").WillReturnRows(
		sqlmock.NewRows([]string{"id", "semester", "category", "batch", "start_date", "end_date", "is_done", "items_json"}).
			AddRow(1, "", "", "", "", "", 0, ""),
	)
	if values, queryErr := s.Evaluations(ctx, "sid"); queryErr != nil || len(values) != 1 {
		t.Fatalf("evaluations=%#v err=%v", values, queryErr)
	}

	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestLegacyNullableAuxiliaryDataUsesSQLDefaults(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	ctx := context.Background()
	s := New(db)

	mock.ExpectQuery("SELECT id,COALESCE\\(semester").WithArgs("sid", "", "").WillReturnRows(
		sqlmock.NewRows([]string{"id", "semester", "favorite_key", "course_name", "class_info", "teacher", "classroom", "schedules_json", "created_at"}).
			AddRow(1, "", "", "", "", "", "", "", nil),
	)
	if values, queryErr := s.AuditFavorites(ctx, "sid", ""); queryErr != nil || len(values) != 1 || values[0].Schedules == nil {
		t.Fatalf("favorites=%#v err=%v", values, queryErr)
	}

	mock.ExpectQuery("SELECT id,COALESCE\\(student_id").WithArgs("sid", 50).WillReturnRows(
		sqlmock.NewRows([]string{"id", "student_id", "student_name", "type", "content", "status", "reply", "replied_at", "reply_read", "created_at"}).
			AddRow(1, "", "", "other", "", "pending", "", nil, 0, nil),
	)
	if values, queryErr := s.FeedbackByUser(ctx, "sid", 50); queryErr != nil || len(values) != 1 {
		t.Fatalf("feedback=%#v err=%v", values, queryErr)
	}

	mock.ExpectQuery("SELECT id,COALESCE\\(student_id").WithArgs("sid", "grade").WillReturnRows(
		sqlmock.NewRows([]string{"id", "student_id", "semester", "kind", "course_key", "course_name", "teacher_key", "teacher", "assessment_type", "stage", "course_end_at", "exam_wait_started_at", "grade_wait_started_at", "exam_at", "exam_finished_at", "grade_first_seen_at", "next_check_at", "last_check_at", "sent_at", "expires_at", "fail_count", "status"}).
			AddRow(1, "", "", "grade", "", "", "", "", "", "scheduled", nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, 0, "active"),
	)
	if values, queryErr := s.ActiveReminderTasks(ctx, "sid", "grade"); queryErr != nil || len(values) != 1 {
		t.Fatalf("reminders=%#v err=%v", values, queryErr)
	}

	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestReplaceCETScoresKeepsSnapshotOnEmptyResult(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()

	if err = New(db).ReplaceCETScores(context.Background(), "sid", nil); err != nil {
		t.Fatal(err)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}
