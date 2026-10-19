package store

import (
	"context"
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
)

func TestSubscriptionStatusRejectsCorruptJSON(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	mock.ExpectQuery("SELECT v FROM user_settings").WithArgs("924101960000", "subscribe").WillReturnRows(sqlmock.NewRows([]string{"v"}).AddRow("{"))
	if _, err = New(db).SubscriptionStatus(context.Background(), "924101960000"); err == nil {
		t.Fatal("corrupt subscription JSON should fail")
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestDecodeSubscriptionsTreatsNullAsEmpty(t *testing.T) {
	values, err := decodeSubscriptions("null")
	if err != nil {
		t.Fatal(err)
	}
	values["exam"] = SubscriptionItem{Count: 1}
	if values["exam"].Count != 1 {
		t.Fatalf("unexpected values: %#v", values)
	}
}

func TestAuditFavoritesRejectsCorruptSchedules(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	columns := []string{"id", "semester", "favorite_key", "course_name", "class_info", "teacher", "classroom", "schedules_json", "created_at"}
	mock.ExpectQuery("SELECT id,COALESCE\\(semester").WithArgs("924101960000", "", "").WillReturnRows(
		sqlmock.NewRows(columns).AddRow(1, "2026-2027-1", "key", "课程", "班级", "教师", "教室", "{", nil),
	)
	if _, err = New(db).AuditFavorites(context.Background(), "924101960000", ""); err == nil {
		t.Fatal("corrupt favorite schedules should fail")
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestEvaluationsRejectsCorruptItems(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	columns := []string{"id", "semester", "category", "batch", "start_date", "end_date", "is_done", "items_json"}
	mock.ExpectQuery("SELECT id,COALESCE\\(semester").WithArgs("924101960000").WillReturnRows(
		sqlmock.NewRows(columns).AddRow(1, "2026-2027-1", "分类", "批次", "2026-01-01", "2026-01-02", 0, "{"),
	)
	if _, err = New(db).Evaluations(context.Background(), "924101960000"); err == nil {
		t.Fatal("corrupt evaluation items should fail")
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}
