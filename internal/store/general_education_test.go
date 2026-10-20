package store

import (
	"context"
	"database/sql/driver"
	"regexp"
	"testing"
	"time"

	"github.com/DATA-DOG/go-sqlmock"
)

func TestReplaceGeneralEducationCoursesPreservesDetailForSameSyllabus(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	fetched := time.Date(2026, 10, 21, 8, 0, 0, 0, time.Local)
	mock.ExpectBegin()
	mock.ExpectQuery(regexp.QuoteMeta("SELECT course_code,COALESCE(syllabus_id,''),COALESCE(has_syllabus,0)")).
		WithArgs("2026-2027-1").
		WillReturnRows(sqlmock.NewRows([]string{"course_code", "syllabus_id", "has_syllabus", "detail_json", "detail_fetched_at"}).
			AddRow("00010192", "ABC123", 1, `{"raw_text":"cached"}`, fetched))
	mock.ExpectExec(regexp.QuoteMeta("DELETE FROM general_education_syllabi WHERE semester=?")).
		WithArgs("2026-2027-1").
		WillReturnResult(sqlmock.NewResult(0, 1))
	insert := mock.ExpectPrepare(regexp.QuoteMeta("INSERT INTO general_education_syllabi"))
	insert.ExpectExec().
		WithArgs("2026-2027-1", "00010192", "绿色生活与绿色技术", "环境与生物工程学院", "1", "32", "考查", "任选", "ABC123", 1, `{"raw_text":"cached"}`, driver.Value(fetched)).
		WillReturnResult(sqlmock.NewResult(1, 1))
	mock.ExpectCommit()

	err = New(db).ReplaceGeneralEducationCourses(context.Background(), "2026-2027-1", []GeneralEducationCourse{{
		CourseCode: "00010192", CourseName: "绿色生活与绿色技术", Department: "环境与生物工程学院",
		Credit: "1", Hours: "32", Assessment: "考查", Attribute: "任选",
		SyllabusID: "ABC123", HasSyllabus: true,
	}})
	if err != nil {
		t.Fatal(err)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}
