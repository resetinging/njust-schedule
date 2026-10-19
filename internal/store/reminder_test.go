package store

import (
	"context"
	"regexp"
	"strconv"
	"testing"
	"time"

	"github.com/DATA-DOG/go-sqlmock"
)

func TestTryClaimUserSettingCreatesClaim(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	mock.ExpectBegin()
	mock.ExpectExec("INSERT IGNORE INTO user_settings").WithArgs("sid", "claim", "pending:1").WillReturnResult(sqlmock.NewResult(1, 1))
	mock.ExpectCommit()
	claimed, err := New(db).TryClaimUserSetting(context.Background(), "sid", "claim", "pending:1")
	if err != nil || !claimed {
		t.Fatalf("claimed=%v err=%v", claimed, err)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestTryClaimUserSettingTakesOverExpiredPendingClaim(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	old := "pending:" + strconv.FormatInt(time.Now().Add(-time.Hour).Unix(), 10)
	mock.ExpectBegin()
	mock.ExpectExec("INSERT IGNORE INTO user_settings").WithArgs("sid", "claim", "pending:2").WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectQuery(regexp.QuoteMeta("SELECT COALESCE(v,'') FROM user_settings WHERE student_id=? AND k=? FOR UPDATE")).WithArgs("sid", "claim").WillReturnRows(sqlmock.NewRows([]string{"v"}).AddRow(old))
	mock.ExpectExec("UPDATE user_settings SET v=").WithArgs("pending:2", "sid", "claim").WillReturnResult(sqlmock.NewResult(0, 1))
	mock.ExpectCommit()
	claimed, err := New(db).TryClaimUserSetting(context.Background(), "sid", "claim", "pending:2")
	if err != nil || !claimed {
		t.Fatalf("claimed=%v err=%v", claimed, err)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestTryClaimUserSettingDoesNotTakeSentClaim(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	mock.ExpectBegin()
	mock.ExpectExec("INSERT IGNORE INTO user_settings").WithArgs("sid", "claim", "pending:2").WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectQuery(regexp.QuoteMeta("SELECT COALESCE(v,'') FROM user_settings WHERE student_id=? AND k=? FOR UPDATE")).WithArgs("sid", "claim").WillReturnRows(sqlmock.NewRows([]string{"v"}).AddRow("sent:1"))
	mock.ExpectCommit()
	claimed, err := New(db).TryClaimUserSetting(context.Background(), "sid", "claim", "pending:2")
	if err != nil || claimed {
		t.Fatalf("claimed=%v err=%v", claimed, err)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestCompleteReminderTaskUpdatesTaskAndClaimAtomically(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	now := time.Unix(1_800_000_000, 0)
	task := ReminderTask{ID: 7, StudentID: "sid", Stage: "done", Status: "done", SentAt: &now}
	mock.ExpectBegin()
	mock.ExpectExec("UPDATE reminder_tasks SET stage=").WillReturnResult(sqlmock.NewResult(0, 1))
	mock.ExpectExec("UPDATE user_settings SET v=").WithArgs("sent:"+strconv.FormatInt(now.Unix(), 10), "sid", "claim").WillReturnResult(sqlmock.NewResult(0, 1))
	mock.ExpectCommit()
	if err = New(db).CompleteReminderTask(context.Background(), task, "claim", now); err != nil {
		t.Fatal(err)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestSetUserSettingsUsesTransaction(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	mock.ExpectBegin()
	prepared := mock.ExpectPrepare("INSERT INTO user_settings")
	prepared.ExpectExec().WithArgs("sid", "semester", "2026-2027-1").WillReturnResult(sqlmock.NewResult(1, 1))
	mock.ExpectCommit()
	if err = New(db).SetUserSettings(context.Background(), "sid", map[string]string{"semester": "2026-2027-1"}); err != nil {
		t.Fatal(err)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}
