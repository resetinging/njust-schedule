package migrate

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
)

func completeSchemaRows() *sqlmock.Rows {
	return schemaRowsForVersion(Version)
}

func schemaRowsForVersion(version string) *sqlmock.Rows {
	rows := sqlmock.NewRows([]string{"TABLE_NAME", "COLUMN_NAME"}).AddRow("settings", "k").AddRow("settings", "v").AddRow("schema_migrations", "version")
	seen := map[string]bool{"settings.k": true, "settings.v": true, "schema_migrations.version": true}
	for _, column := range requiredColumns {
		if version == BaselineVersion && column.table == generalEducationTable {
			continue
		}
		key := column.table + "." + column.name
		if !seen[key] {
			rows.AddRow(column.table, column.name)
			seen[key] = true
		}
	}
	return rows
}

func completeIndexRows() *sqlmock.Rows {
	return indexRowsForVersion(Version)
}

func indexRowsForVersion(version string) *sqlmock.Rows {
	rows := sqlmock.NewRows([]string{"TABLE_NAME", "INDEX_NAME", "COLUMN_NAME", "NON_UNIQUE"})
	for _, index := range indexes {
		if version == BaselineVersion && index.table == generalEducationTable {
			continue
		}
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
	} {
		if !strings.Contains(statements, expected) {
			t.Fatalf("cleanup statements missing %q:\n%s", expected, statements)
		}
	}
	if strings.Contains(statements, "usage_events") {
		t.Fatalf("usage_events must use indexed temporary-table cleanup:\n%s", statements)
	}
}

func TestUsageEventDedupeUsesIndexedTemporaryTable(t *testing.T) {
	statements := strings.Join(usageEventDedupeStatements(), "\n")
	for _, expected := range []string{
		"DROP TEMPORARY TABLE IF EXISTS `usage_event_key_duplicates`",
		"SET `event_key`=CONCAT('legacy-',`id`)",
		"CREATE TEMPORARY TABLE `usage_event_key_duplicates`",
		"HAVING COUNT(*)>1",
		"JOIN `usage_event_key_duplicates` fresh",
		"stale.`id`<fresh.`keep_id`",
	} {
		if !strings.Contains(statements, expected) {
			t.Fatalf("dedupe statements missing %q:\n%s", expected, statements)
		}
	}
	if strings.Contains(statements, "`usage_events` stale JOIN `usage_events` fresh") {
		t.Fatalf("unsafe unindexed self join returned:\n%s", statements)
	}
}

func TestIndexDefinitionDetectsMismatchedDefinition(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	mock.ExpectQuery("SELECT COLUMN_NAME,NON_UNIQUE").
		WithArgs("usage_events", "uq_usage_events_event_key").
		WillReturnRows(sqlmock.NewRows([]string{"COLUMN_NAME", "NON_UNIQUE"}).
			AddRow("event_key", 1).
			AddRow("event_name", 1))

	exists, matches, err := indexDefinition(
		context.Background(), db, "usage_events",
		"uq_usage_events_event_key", "event_key", true,
	)
	if err != nil {
		t.Fatal(err)
	}
	if !exists || matches {
		t.Fatalf("exists=%v matches=%v, want existing mismatch", exists, matches)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestIndexDefinitionAcceptsExpectedUniqueIndex(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	mock.ExpectQuery("SELECT COLUMN_NAME,NON_UNIQUE").
		WithArgs("usage_events", "uq_usage_events_event_key").
		WillReturnRows(sqlmock.NewRows([]string{"COLUMN_NAME", "NON_UNIQUE"}).
			AddRow("event_key", 0))

	exists, matches, err := indexDefinition(
		context.Background(), db, "usage_events",
		"uq_usage_events_event_key", "event_key", true,
	)
	if err != nil {
		t.Fatal(err)
	}
	if !exists || !matches {
		t.Fatalf("exists=%v matches=%v, want matching unique index", exists, matches)
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

func expectLockRelease(mock sqlmock.Sqlmock) {
	mock.ExpectExec("SELECT RELEASE_LOCK").WithArgs(lockName).WillReturnResult(sqlmock.NewResult(0, 0))
}

func TestEnsureAppliesRegisteredSafeMigrationFromBaseline(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()

	mock.ExpectQuery("SELECT TABLE_NAME,COLUMN_NAME").
		WillReturnRows(schemaRowsForVersion(BaselineVersion))
	mock.ExpectQuery("SELECT GET_LOCK").
		WithArgs(lockName).
		WillReturnRows(sqlmock.NewRows([]string{"lock"}).AddRow(1))
	mock.ExpectQuery(regexp.QuoteMeta("SELECT version FROM schema_migrations")).
		WillReturnRows(sqlmock.NewRows([]string{"version"}).AddRow(BaselineVersion))

	mock.ExpectQuery("SELECT TABLE_NAME,COLUMN_NAME").
		WillReturnRows(schemaRowsForVersion(BaselineVersion))
	expectTextColumns(mock)
	mock.ExpectQuery("SELECT TABLE_NAME,INDEX_NAME,COLUMN_NAME,NON_UNIQUE").
		WillReturnRows(indexRowsForVersion(BaselineVersion))
	mock.ExpectQuery(regexp.QuoteMeta("SELECT COUNT(*) FROM schema_migrations WHERE version=?")).
		WithArgs(BaselineVersion).
		WillReturnRows(sqlmock.NewRows([]string{"count"}).AddRow(1))

	mock.ExpectExec(regexp.QuoteMeta(generalEducationCreateTable)).
		WillReturnResult(sqlmock.NewResult(0, 0))
	for _, index := range indexes {
		if index.table != generalEducationTable {
			continue
		}
		mock.ExpectQuery("SELECT COLUMN_NAME,NON_UNIQUE").
			WithArgs(index.table, index.name).
			WillReturnRows(sqlmock.NewRows([]string{"COLUMN_NAME", "NON_UNIQUE"}))
		kind := "INDEX"
		if strings.HasPrefix(index.name, "uq_") {
			kind = "UNIQUE INDEX"
		}
		statement := fmt.Sprintf("CREATE %s `%s` ON `%s` (%s)", kind, index.name, index.table, quoteColumns(index.columns))
		mock.ExpectExec(regexp.QuoteMeta(statement)).
			WillReturnResult(sqlmock.NewResult(0, 0))
	}
	mock.ExpectExec(regexp.QuoteMeta("INSERT INTO schema_migrations(version,applied_at) VALUES (?,NOW())")).
		WithArgs(Version).
		WillReturnResult(sqlmock.NewResult(0, 1))

	mock.ExpectQuery("SELECT TABLE_NAME,COLUMN_NAME").
		WillReturnRows(schemaRowsForVersion(Version))
	expectTextColumns(mock)
	mock.ExpectQuery("SELECT TABLE_NAME,INDEX_NAME,COLUMN_NAME,NON_UNIQUE").
		WillReturnRows(indexRowsForVersion(Version))
	mock.ExpectQuery(regexp.QuoteMeta("SELECT COUNT(*) FROM schema_migrations WHERE version=?")).
		WithArgs(Version).
		WillReturnRows(sqlmock.NewRows([]string{"count"}).AddRow(1))
	expectLockRelease(mock)

	applied, err := Ensure(context.Background(), db, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(applied) != 1 || applied[0] != Version {
		t.Fatalf("applied = %#v, want %s", applied, Version)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestEnsureSkipsLockWhenSchemaIsReady(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()

	mock.ExpectQuery("SELECT TABLE_NAME,COLUMN_NAME").
		WillReturnRows(schemaRowsForVersion(Version))
	expectTextColumns(mock)
	mock.ExpectQuery("SELECT TABLE_NAME,INDEX_NAME,COLUMN_NAME,NON_UNIQUE").
		WillReturnRows(indexRowsForVersion(Version))
	mock.ExpectQuery(regexp.QuoteMeta("SELECT COUNT(*) FROM schema_migrations WHERE version=?")).
		WithArgs(Version).
		WillReturnRows(sqlmock.NewRows([]string{"count"}).AddRow(1))

	applied, err := Ensure(context.Background(), db, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(applied) != 0 {
		t.Fatalf("applied = %#v, want no migrations", applied)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestEnsureDoesNotRepairBrokenRecordedVersion(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()

	mock.ExpectQuery("SELECT TABLE_NAME,COLUMN_NAME").
		WillReturnRows(schemaRowsForVersion(BaselineVersion))
	mock.ExpectQuery("SELECT GET_LOCK").
		WithArgs(lockName).
		WillReturnRows(sqlmock.NewRows([]string{"lock"}).AddRow(1))
	mock.ExpectQuery(regexp.QuoteMeta("SELECT version FROM schema_migrations")).
		WillReturnRows(sqlmock.NewRows([]string{"version"}).AddRow(Version))
	mock.ExpectQuery("SELECT TABLE_NAME,COLUMN_NAME").
		WillReturnRows(schemaRowsForVersion(BaselineVersion))
	expectLockRelease(mock)

	applied, err := Ensure(context.Background(), db, nil, nil)
	if err == nil || len(applied) != 0 || !strings.Contains(err.Error(), "结构异常") {
		t.Fatalf("applied=%#v err=%v", applied, err)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestEnsureRequiresManualMigrationForUnknownBaseline(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()

	mock.ExpectQuery("SELECT TABLE_NAME,COLUMN_NAME").
		WillReturnRows(sqlmock.NewRows([]string{"TABLE_NAME", "COLUMN_NAME"}).AddRow("settings", "k"))
	mock.ExpectQuery("SELECT GET_LOCK").
		WithArgs(lockName).
		WillReturnRows(sqlmock.NewRows([]string{"lock"}).AddRow(1))
	mock.ExpectQuery(regexp.QuoteMeta("SELECT version FROM schema_migrations")).
		WillReturnRows(sqlmock.NewRows([]string{"version"}).AddRow("0001_student_id"))
	expectLockRelease(mock)

	applied, err := Ensure(context.Background(), db, nil, nil)
	if err == nil || len(applied) != 0 || !strings.Contains(err.Error(), "非安全或未知迁移状态") {
		t.Fatalf("applied=%#v err=%v", applied, err)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestAutoSafeMigrationRequiresKnownBaseline(t *testing.T) {
	if _, ok := nextAutoSafeMigration(map[string]bool{Version: true}); ok {
		t.Fatal("unexpected safe migration after current version")
	}
	if _, ok := nextAutoSafeMigration(map[string]bool{"0001_student_id": true}); ok {
		t.Fatal("unexpected safe migration without baseline")
	}
	if migration, ok := nextAutoSafeMigration(map[string]bool{BaselineVersion: true}); !ok || migration.to != Version {
		t.Fatalf("migration=%#v ok=%v", migration, ok)
	}
}

func TestAutoSafeMigrationRegistryIsContiguous(t *testing.T) {
	current := BaselineVersion
	for _, migration := range autoSafeMigrations {
		if migration.from != current {
			t.Fatalf("migration from %s, want contiguous from %s", migration.from, current)
		}
		if migration.to == "" || migration.apply == nil {
			t.Fatalf("incomplete migration %#v", migration)
		}
		current = migration.to
	}
	if current != Version {
		t.Fatalf("safe migration chain ends at %s, want %s", current, Version)
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
