package migrate

import (
	"context"
	"errors"
	"regexp"
	"strings"
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
)

func completeSchemaRows() *sqlmock.Rows {
	rows := sqlmock.NewRows([]string{"TABLE_NAME", "COLUMN_NAME"}).AddRow("settings", "k").AddRow("settings", "v").AddRow("schema_migrations", "version")
	seen := map[string]bool{"settings.k": true, "settings.v": true, "schema_migrations.version": true}
	for _, column := range requiredColumns {
		key := column.table + "." + column.name
		if !seen[key] {
			rows.AddRow(column.table, column.name)
			seen[key] = true
		}
	}
	return rows
}

func completeIndexRows() *sqlmock.Rows {
	rows := sqlmock.NewRows([]string{"TABLE_NAME", "INDEX_NAME", "COLUMN_NAME", "NON_UNIQUE"})
	for _, index := range indexes {
		nonUnique := 1
		if strings.HasPrefix(index.name, "uq_") {
			nonUnique = 0
		}
		for _, column := range strings.Split(index.columns, ",") {
			rows.AddRow(index.table, index.name, column, nonUnique)
		}
	}
	return rows
}

func TestVerifyReportsMissingSchema(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	mock.ExpectQuery("SELECT TABLE_NAME,COLUMN_NAME").WillReturnRows(sqlmock.NewRows([]string{"TABLE_NAME", "COLUMN_NAME"}).AddRow("settings", "k"))
	err = Verify(context.Background(), db)
	if err == nil || !strings.Contains(err.Error(), "数据库结构未迁移") || !strings.Contains(err.Error(), "表 courses") {
		t.Fatalf("unexpected error: %v", err)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestVerifyRequiresMigrationVersion(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	mock.ExpectQuery("SELECT TABLE_NAME,COLUMN_NAME").WillReturnRows(completeSchemaRows())
	expectTextColumns(mock)
	mock.ExpectQuery("SELECT TABLE_NAME,INDEX_NAME,COLUMN_NAME,NON_UNIQUE").WillReturnRows(completeIndexRows())
	mock.ExpectQuery(regexp.QuoteMeta("SELECT COUNT(*) FROM schema_migrations WHERE version=?")).WithArgs(Version).WillReturnRows(sqlmock.NewRows([]string{"count"}).AddRow(0))
	err = Verify(context.Background(), db)
	if err == nil || !strings.Contains(err.Error(), "数据库缺少迁移版本") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestVerifyRejectsMalformedUniqueIndex(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	mock.ExpectQuery("SELECT TABLE_NAME,COLUMN_NAME").WillReturnRows(completeSchemaRows())
	expectTextColumns(mock)
	rows := completeIndexRows()
	rows.AddRow("usage_events", "uq_usage_events_event_key", "extra_column", 0)
	mock.ExpectQuery("SELECT TABLE_NAME,INDEX_NAME,COLUMN_NAME,NON_UNIQUE").WillReturnRows(rows)
	err = Verify(context.Background(), db)
	if err == nil || !strings.Contains(err.Error(), "数据库索引未迁移或定义不匹配") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestUniqueKeyCleanupNormalizesAndDeduplicates(t *testing.T) {
	statements := strings.Join(uniqueKeyCleanupStatements(), "\n")
	for _, expected := range []string{
		"DELETE stale FROM `audit_favorites`",
		"COALESCE(stale.`student_id`,'')=COALESCE(fresh.`student_id`,'')",
		"UPDATE `reminder_tasks` SET `student_id`=COALESCE(`student_id`,'')",
		"DELETE stale FROM `usage_events`",
		"UPDATE `usage_events` SET `event_key`=COALESCE(`event_key`,'')",
	} {
		if !strings.Contains(statements, expected) {
			t.Fatalf("cleanup statements missing %q:\n%s", expected, statements)
		}
	}
}

func TestVerifyRejectsNarrowClassInfo(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	mock.ExpectQuery("SELECT TABLE_NAME,COLUMN_NAME").WillReturnRows(completeSchemaRows())
	mock.ExpectQuery("SELECT DATA_TYPE").WithArgs("audit_courses").WillReturnRows(sqlmock.NewRows([]string{"DATA_TYPE"}).AddRow("varchar"))
	err = Verify(context.Background(), db)
	if err == nil || !strings.Contains(err.Error(), "class_info 必须为 TEXT") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func expectTextColumns(mock sqlmock.Sqlmock) {
	for _, table := range []string{"audit_courses", "audit_favorites"} {
		mock.ExpectQuery("SELECT DATA_TYPE").WithArgs(table).WillReturnRows(sqlmock.NewRows([]string{"DATA_TYPE"}).AddRow("text"))
	}
}

func TestRunDoesNotRecordVersionAfterDDLFailure(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	mock.ExpectQuery("SELECT GET_LOCK").WithArgs(lockName).WillReturnRows(sqlmock.NewRows([]string{"lock"}).AddRow(1))
	mock.ExpectExec(regexp.QuoteMeta(createTables[0])).WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectQuery(regexp.QuoteMeta("SELECT COUNT(*) FROM schema_migrations WHERE version=?")).WithArgs(Version).WillReturnRows(sqlmock.NewRows([]string{"count"}).AddRow(0))
	mock.ExpectExec(regexp.QuoteMeta(createTables[0])).WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectExec(regexp.QuoteMeta(createTables[1])).WillReturnError(errors.New("ddl failed"))
	mock.ExpectExec("SELECT RELEASE_LOCK").WithArgs(lockName).WillReturnResult(sqlmock.NewResult(0, 0))

	versions, err := Run(context.Background(), db, nil)
	if err == nil || len(versions) != 0 || !strings.Contains(err.Error(), "建表失败") {
		t.Fatalf("versions=%#v err=%v", versions, err)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}
