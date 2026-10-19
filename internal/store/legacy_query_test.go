package store

import (
	"context"
	"regexp"
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
)

func TestGradeSemestersUsesDistinctAliases(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	query := regexp.QuoteMeta(`SELECT DISTINCT COALESCE(academic_year,'') AS academic_year,COALESCE(semester,'') AS semester FROM grades WHERE student_id=? ORDER BY academic_year DESC,semester DESC`)
	mock.ExpectQuery(query).
		WithArgs("sid").
		WillReturnRows(sqlmock.NewRows([]string{"academic_year", "semester"}).
			AddRow("2026-2027", "1"))
	values, err := New(db).GradeSemesters(context.Background(), "sid")
	if err != nil {
		t.Fatal(err)
	}
	if len(values) != 1 || values[0] != "2026-2027-1" {
		t.Fatalf("GradeSemesters() = %#v", values)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestAuditGroupsUsesDistinctAliases(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	mock.ExpectQuery(regexp.QuoteMeta(`SELECT COUNT(*) FROM (SELECT DISTINCT COALESCE(course_name,''),COALESCE(class_info,'') FROM audit_courses WHERE semester=?) x`)).
		WithArgs("2026-2027-1").
		WillReturnRows(sqlmock.NewRows([]string{"count"}).AddRow(0))
	mock.ExpectQuery(regexp.QuoteMeta(`SELECT DISTINCT COALESCE(course_name,'') AS course_name,COALESCE(class_info,'') AS class_info FROM audit_courses WHERE semester=? ORDER BY course_name,class_info LIMIT ? OFFSET ?`)).
		WithArgs("2026-2027-1", 20, 0).
		WillReturnRows(sqlmock.NewRows([]string{"course_name", "class_info"}))
	groups, total, err := New(db).AuditGroups(context.Background(), AuditQuery{Semester: "2026-2027-1", Limit: 20})
	if err != nil {
		t.Fatal(err)
	}
	if total != 0 || len(groups) != 0 {
		t.Fatalf("AuditGroups() total=%d groups=%#v", total, groups)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}
