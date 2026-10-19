package store

import (
	"context"
	"regexp"
	"testing"
	"time"

	"github.com/DATA-DOG/go-sqlmock"
)

func TestSettingsReturnsRequestedValues(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	mock.ExpectQuery(regexp.QuoteMeta("SELECT k,COALESCE(v,'') FROM settings WHERE k IN (?,?)")).
		WithArgs("a", "b").
		WillReturnRows(sqlmock.NewRows([]string{"k", "v"}).AddRow("a", "1"))
	values, err := New(db).Settings(context.Background(), "a", "b")
	if err != nil {
		t.Fatal(err)
	}
	if values["a"] != "1" || values["b"] != "" {
		t.Fatalf("unexpected settings: %#v", values)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestSetSettingsUsesTransaction(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	mock.ExpectBegin()
	prepared := mock.ExpectPrepare("INSERT INTO settings")
	prepared.ExpectExec().WithArgs("announcement_enabled", "1").WillReturnResult(sqlmock.NewResult(1, 1))
	mock.ExpectCommit()
	if err = New(db).SetSettings(context.Background(), map[string]string{"announcement_enabled": "1"}); err != nil {
		t.Fatal(err)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestCountUserDataUsesSingleRoundTrip(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	mock.ExpectQuery("SELECT\\s+\\(SELECT COUNT\\(\\*\\) FROM courses").
		WithArgs("sid", "2026-2027-1", "sid", "2026-2027-1").
		WillReturnRows(sqlmock.NewRows([]string{"courses", "exams"}).AddRow(9, 2))
	courses, exams, err := New(db).CountUserData(context.Background(), "sid", "2026-2027-1")
	if err != nil {
		t.Fatal(err)
	}
	if courses != 9 || exams != 2 {
		t.Fatalf("courses=%d exams=%d", courses, exams)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestDataVersionsUsesSingleRoundTrip(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	updated := time.Unix(1_800_000_000, 0)
	mock.ExpectQuery("SELECT 'courses' AS domain").
		WithArgs("sid", "2026-2027-1", "sid", "2026-2027-1", "sid", "sid", "sid").
		WillReturnRows(sqlmock.NewRows([]string{"domain", "row_count", "latest_id", "latest_at"}).
			AddRow("courses", 2, 9, updated).
			AddRow("exams", 0, 0, nil).
			AddRow("evaluations", 1, 4, updated).
			AddRow("grades", 3, 8, updated).
			AddRow("cet_scores", 0, 0, nil))
	versions, err := New(db).DataVersions(context.Background(), "sid", "2026-2027-1")
	if err != nil {
		t.Fatal(err)
	}
	if versions["courses"] != "2:9:1800000000" || versions["exams"] != "0" || versions["grades"] != "3:8:1800000000" {
		t.Fatalf("unexpected versions: %#v", versions)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}
