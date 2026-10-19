package migrate

import (
	"context"
	"database/sql"
	"fmt"
	"log/slog"
	"sort"
	"strings"
	"time"
)

const Version = "1000_webgo_schema_v1"
const lockName = "njust_schedule_schema_migration"

type columnSpec struct {
	table, name, definition string
}

type queryer interface {
	QueryContext(context.Context, string, ...any) (*sql.Rows, error)
	QueryRowContext(context.Context, string, ...any) *sql.Row
}

var requiredColumns = []columnSpec{
	{"courses", "student_id", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"courses", "name", "VARCHAR(200) NOT NULL DEFAULT ''"}, {"courses", "teacher", "VARCHAR(100) NOT NULL DEFAULT ''"}, {"courses", "classroom", "VARCHAR(100) NOT NULL DEFAULT ''"}, {"courses", "day_of_week", "INT NOT NULL DEFAULT 0"}, {"courses", "start_period", "INT NOT NULL DEFAULT 0"}, {"courses", "end_period", "INT NOT NULL DEFAULT 0"}, {"courses", "weeks", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"courses", "week_type", "INT NOT NULL DEFAULT 0"}, {"courses", "semester", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"courses", "credits", "VARCHAR(20) NOT NULL DEFAULT ''"}, {"courses", "course_type", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"courses", "raw_data", "TEXT NULL"}, {"courses", "created_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"},
	{"exams", "student_id", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"exams", "course_name", "VARCHAR(200) NOT NULL DEFAULT ''"}, {"exams", "exam_date", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"exams", "exam_time", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"exams", "location", "VARCHAR(100) NOT NULL DEFAULT ''"}, {"exams", "seat", "VARCHAR(20) NOT NULL DEFAULT ''"}, {"exams", "exam_type", "VARCHAR(50) NOT NULL DEFAULT '期末考试'"}, {"exams", "semester", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"exams", "created_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"},
	{"evaluations", "student_id", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"evaluations", "semester", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"evaluations", "category", "VARCHAR(100) NOT NULL DEFAULT ''"}, {"evaluations", "batch", "VARCHAR(200) NOT NULL DEFAULT ''"}, {"evaluations", "start_date", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"evaluations", "end_date", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"evaluations", "is_done", "INT NOT NULL DEFAULT 0"}, {"evaluations", "items_json", "TEXT NULL"}, {"evaluations", "created_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"},
	{"grades", "student_id", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"grades", "academic_year", "VARCHAR(20) NOT NULL DEFAULT ''"}, {"grades", "semester", "VARCHAR(10) NOT NULL DEFAULT ''"}, {"grades", "course_code", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"grades", "course_name", "VARCHAR(200) NOT NULL DEFAULT ''"}, {"grades", "score", "VARCHAR(20) NOT NULL DEFAULT ''"}, {"grades", "credit", "DOUBLE NOT NULL DEFAULT 0"}, {"grades", "grade_point", "DOUBLE NOT NULL DEFAULT 0"}, {"grades", "course_type", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"grades", "course_nature", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"grades", "exam_type", "VARCHAR(50) NOT NULL DEFAULT '正常考试'"}, {"grades", "created_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"},
	{"cet_scores", "student_id", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"cet_scores", "cet_type", "VARCHAR(10) NOT NULL DEFAULT ''"}, {"cet_scores", "total_score", "DOUBLE NOT NULL DEFAULT 0"}, {"cet_scores", "exam_date", "VARCHAR(20) NOT NULL DEFAULT ''"}, {"cet_scores", "created_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"},
	{"feedback", "student_id", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"feedback", "student_name", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"feedback", "fb_type", "VARCHAR(20) NOT NULL DEFAULT 'other'"}, {"feedback", "content", "VARCHAR(500) NOT NULL DEFAULT ''"}, {"feedback", "contact", "VARCHAR(100) NOT NULL DEFAULT ''"}, {"feedback", "status", "VARCHAR(20) NOT NULL DEFAULT 'pending'"}, {"feedback", "reply", "VARCHAR(500) NOT NULL DEFAULT ''"}, {"feedback", "replied_at", "TIMESTAMP NULL"}, {"feedback", "reply_read", "TINYINT(1) NOT NULL DEFAULT 0"}, {"feedback", "created_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"},
	{"audit_courses", "semester", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"audit_courses", "course_name", "VARCHAR(200) NOT NULL DEFAULT ''"}, {"audit_courses", "class_info", "TEXT NULL"}, {"audit_courses", "teacher", "VARCHAR(200) NOT NULL DEFAULT ''"}, {"audit_courses", "classroom", "VARCHAR(200) NOT NULL DEFAULT ''"}, {"audit_courses", "day_of_week", "INT NOT NULL DEFAULT 0"}, {"audit_courses", "start_period", "INT NOT NULL DEFAULT 0"}, {"audit_courses", "end_period", "INT NOT NULL DEFAULT 0"}, {"audit_courses", "weeks", "VARCHAR(100) NOT NULL DEFAULT ''"}, {"audit_courses", "updated_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"},
	{"audit_favorites", "student_id", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"audit_favorites", "semester", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"audit_favorites", "favorite_key", "VARCHAR(64) NOT NULL DEFAULT ''"}, {"audit_favorites", "course_name", "VARCHAR(200) NOT NULL DEFAULT ''"}, {"audit_favorites", "class_info", "TEXT NULL"}, {"audit_favorites", "teacher", "VARCHAR(200) NOT NULL DEFAULT ''"}, {"audit_favorites", "classroom", "VARCHAR(200) NOT NULL DEFAULT ''"}, {"audit_favorites", "schedules_json", "TEXT NULL"}, {"audit_favorites", "created_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"}, {"audit_favorites", "updated_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"},
	{"user_settings", "student_id", "VARCHAR(50) NOT NULL"}, {"user_settings", "k", "VARCHAR(100) NOT NULL"}, {"user_settings", "v", "TEXT NULL"}, {"user_settings", "updated_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"},
	{"reminder_tasks", "student_id", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"reminder_tasks", "semester", "VARCHAR(50) NOT NULL DEFAULT ''"}, {"reminder_tasks", "kind", "VARCHAR(20) NOT NULL DEFAULT 'grade'"}, {"reminder_tasks", "course_key", "VARCHAR(64) NOT NULL DEFAULT ''"}, {"reminder_tasks", "course_name", "VARCHAR(200) NOT NULL DEFAULT ''"}, {"reminder_tasks", "teacher_key", "VARCHAR(64) NOT NULL DEFAULT ''"}, {"reminder_tasks", "teacher_snapshot", "VARCHAR(200) NOT NULL DEFAULT ''"}, {"reminder_tasks", "assessment_type", "VARCHAR(20) NOT NULL DEFAULT ''"}, {"reminder_tasks", "stage", "VARCHAR(30) NOT NULL DEFAULT 'scheduled'"}, {"reminder_tasks", "course_end_at", "DATETIME NULL"}, {"reminder_tasks", "exam_wait_started_at", "DATETIME NULL"}, {"reminder_tasks", "grade_wait_started_at", "DATETIME NULL"}, {"reminder_tasks", "exam_at", "DATETIME NULL"}, {"reminder_tasks", "exam_finished_at", "DATETIME NULL"}, {"reminder_tasks", "grade_first_seen_at", "DATETIME NULL"}, {"reminder_tasks", "next_check_at", "DATETIME NULL"}, {"reminder_tasks", "last_check_at", "DATETIME NULL"}, {"reminder_tasks", "sent_at", "DATETIME NULL"}, {"reminder_tasks", "expires_at", "DATETIME NULL"}, {"reminder_tasks", "fail_count", "INT NOT NULL DEFAULT 0"}, {"reminder_tasks", "status", "VARCHAR(20) NOT NULL DEFAULT 'active'"}, {"reminder_tasks", "updated_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"},
	{"usage_events", "event_key", "VARCHAR(96) NOT NULL"}, {"usage_events", "analytics_id", "VARCHAR(64) NOT NULL DEFAULT ''"}, {"usage_events", "visitor_hash", "VARCHAR(64) NOT NULL DEFAULT ''"}, {"usage_events", "session_id", "VARCHAR(64) NOT NULL DEFAULT ''"}, {"usage_events", "event_name", "VARCHAR(40) NOT NULL DEFAULT ''"}, {"usage_events", "page", "VARCHAR(40) NOT NULL DEFAULT ''"}, {"usage_events", "feature", "VARCHAR(40) NOT NULL DEFAULT ''"}, {"usage_events", "slot_id", "VARCHAR(64) NOT NULL DEFAULT ''"}, {"usage_events", "ad_type", "VARCHAR(24) NOT NULL DEFAULT ''"}, {"usage_events", "visible_ms", "INT NOT NULL DEFAULT 0"}, {"usage_events", "properties_json", "TEXT NULL"}, {"usage_events", "app_version", "VARCHAR(40) NOT NULL DEFAULT ''"}, {"usage_events", "platform", "VARCHAR(24) NOT NULL DEFAULT ''"}, {"usage_events", "client_ts", "DATETIME NULL"}, {"usage_events", "created_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"},
	{"usage_user_daily", "date", "DATE NOT NULL"}, {"usage_user_daily", "analytics_id", "VARCHAR(64) NOT NULL"}, {"usage_user_daily", "open_count", "INT NOT NULL DEFAULT 0"}, {"usage_user_daily", "session_count", "INT NOT NULL DEFAULT 0"}, {"usage_user_daily", "active_seconds", "INT NOT NULL DEFAULT 0"}, {"usage_user_daily", "page_views", "INT NOT NULL DEFAULT 0"}, {"usage_user_daily", "event_count", "INT NOT NULL DEFAULT 0"}, {"usage_user_daily", "feature_actions", "INT NOT NULL DEFAULT 0"}, {"usage_user_daily", "first_seen_at", "DATETIME NULL"}, {"usage_user_daily", "last_seen_at", "DATETIME NULL"}, {"usage_user_daily", "updated_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"},
	{"usage_slot_user_daily", "date", "DATE NOT NULL"}, {"usage_slot_user_daily", "analytics_id", "VARCHAR(64) NOT NULL"}, {"usage_slot_user_daily", "slot_id", "VARCHAR(64) NOT NULL"}, {"usage_slot_user_daily", "ad_type", "VARCHAR(24) NOT NULL DEFAULT ''"}, {"usage_slot_user_daily", "page", "VARCHAR(40) NOT NULL DEFAULT ''"}, {"usage_slot_user_daily", "views", "INT NOT NULL DEFAULT 0"}, {"usage_slot_user_daily", "visible_count", "INT NOT NULL DEFAULT 0"}, {"usage_slot_user_daily", "visible_ms", "INT NOT NULL DEFAULT 0"}, {"usage_slot_user_daily", "requests", "INT NOT NULL DEFAULT 0"}, {"usage_slot_user_daily", "impressions", "INT NOT NULL DEFAULT 0"}, {"usage_slot_user_daily", "clicks", "INT NOT NULL DEFAULT 0"}, {"usage_slot_user_daily", "closes", "INT NOT NULL DEFAULT 0"}, {"usage_slot_user_daily", "first_seen_at", "DATETIME NULL"}, {"usage_slot_user_daily", "last_seen_at", "DATETIME NULL"}, {"usage_slot_user_daily", "updated_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"},
}

var createTables = []string{
	`CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(64) NOT NULL PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
	`CREATE TABLE IF NOT EXISTS settings (k VARCHAR(100) NOT NULL PRIMARY KEY, v TEXT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
	`CREATE TABLE IF NOT EXISTS user_settings (student_id VARCHAR(50) NOT NULL, k VARCHAR(100) NOT NULL, v TEXT NULL, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(student_id,k), KEY ix_user_settings_student(student_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
	`CREATE TABLE IF NOT EXISTS courses (id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, student_id VARCHAR(50) NOT NULL DEFAULT '', name VARCHAR(200) NOT NULL DEFAULT '', teacher VARCHAR(100) NOT NULL DEFAULT '', classroom VARCHAR(100) NOT NULL DEFAULT '', day_of_week INT NOT NULL DEFAULT 0, start_period INT NOT NULL DEFAULT 0, end_period INT NOT NULL DEFAULT 0, weeks VARCHAR(50) NOT NULL DEFAULT '', week_type INT NOT NULL DEFAULT 0, semester VARCHAR(50) NOT NULL DEFAULT '', credits VARCHAR(20) NOT NULL DEFAULT '', course_type VARCHAR(50) NOT NULL DEFAULT '', raw_data TEXT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
	`CREATE TABLE IF NOT EXISTS exams (id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, student_id VARCHAR(50) NOT NULL DEFAULT '', course_name VARCHAR(200) NOT NULL DEFAULT '', exam_date VARCHAR(50) NOT NULL DEFAULT '', exam_time VARCHAR(50) NOT NULL DEFAULT '', location VARCHAR(100) NOT NULL DEFAULT '', seat VARCHAR(20) NOT NULL DEFAULT '', exam_type VARCHAR(50) NOT NULL DEFAULT '期末考试', semester VARCHAR(50) NOT NULL DEFAULT '', created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
	`CREATE TABLE IF NOT EXISTS evaluations (id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, student_id VARCHAR(50) NOT NULL DEFAULT '', semester VARCHAR(50) NOT NULL DEFAULT '', category VARCHAR(100) NOT NULL DEFAULT '', batch VARCHAR(200) NOT NULL DEFAULT '', start_date VARCHAR(50) NOT NULL DEFAULT '', end_date VARCHAR(50) NOT NULL DEFAULT '', is_done INT NOT NULL DEFAULT 0, items_json TEXT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
	`CREATE TABLE IF NOT EXISTS grades (id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, student_id VARCHAR(50) NOT NULL DEFAULT '', academic_year VARCHAR(20) NOT NULL DEFAULT '', semester VARCHAR(10) NOT NULL DEFAULT '', course_code VARCHAR(50) NOT NULL DEFAULT '', course_name VARCHAR(200) NOT NULL DEFAULT '', score VARCHAR(20) NOT NULL DEFAULT '', credit DOUBLE NOT NULL DEFAULT 0, grade_point DOUBLE NOT NULL DEFAULT 0, course_type VARCHAR(50) NOT NULL DEFAULT '', course_nature VARCHAR(50) NOT NULL DEFAULT '', exam_type VARCHAR(50) NOT NULL DEFAULT '正常考试', created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
	`CREATE TABLE IF NOT EXISTS cet_scores (id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, student_id VARCHAR(50) NOT NULL DEFAULT '', cet_type VARCHAR(10) NOT NULL DEFAULT '', total_score DOUBLE NOT NULL DEFAULT 0, exam_date VARCHAR(20) NOT NULL DEFAULT '', created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
	`CREATE TABLE IF NOT EXISTS feedback (id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, student_id VARCHAR(50) NOT NULL DEFAULT '', student_name VARCHAR(50) NOT NULL DEFAULT '', fb_type VARCHAR(20) NOT NULL DEFAULT 'other', content VARCHAR(500) NOT NULL DEFAULT '', contact VARCHAR(100) NOT NULL DEFAULT '', status VARCHAR(20) NOT NULL DEFAULT 'pending', reply VARCHAR(500) NOT NULL DEFAULT '', replied_at TIMESTAMP NULL, reply_read TINYINT(1) NOT NULL DEFAULT 0, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
	`CREATE TABLE IF NOT EXISTS audit_courses (id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, semester VARCHAR(50) NOT NULL DEFAULT '', course_name VARCHAR(200) NOT NULL DEFAULT '', class_info TEXT NULL, teacher VARCHAR(200) NOT NULL DEFAULT '', classroom VARCHAR(200) NOT NULL DEFAULT '', day_of_week INT NOT NULL DEFAULT 0, start_period INT NOT NULL DEFAULT 0, end_period INT NOT NULL DEFAULT 0, weeks VARCHAR(100) NOT NULL DEFAULT '', updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
	`CREATE TABLE IF NOT EXISTS audit_favorites (id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, student_id VARCHAR(50) NOT NULL DEFAULT '', semester VARCHAR(50) NOT NULL DEFAULT '', favorite_key VARCHAR(64) NOT NULL DEFAULT '', course_name VARCHAR(200) NOT NULL DEFAULT '', class_info TEXT NULL, teacher VARCHAR(200) NOT NULL DEFAULT '', classroom VARCHAR(200) NOT NULL DEFAULT '', schedules_json TEXT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
	`CREATE TABLE IF NOT EXISTS reminder_tasks (id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, student_id VARCHAR(50) NOT NULL DEFAULT '', semester VARCHAR(50) NOT NULL DEFAULT '', kind VARCHAR(20) NOT NULL DEFAULT 'grade', course_key VARCHAR(64) NOT NULL DEFAULT '', course_name VARCHAR(200) NOT NULL DEFAULT '', teacher_key VARCHAR(64) NOT NULL DEFAULT '', teacher_snapshot VARCHAR(200) NOT NULL DEFAULT '', assessment_type VARCHAR(20) NOT NULL DEFAULT '', stage VARCHAR(30) NOT NULL DEFAULT 'scheduled', course_end_at DATETIME NULL, exam_wait_started_at DATETIME NULL, grade_wait_started_at DATETIME NULL, exam_at DATETIME NULL, exam_finished_at DATETIME NULL, grade_first_seen_at DATETIME NULL, next_check_at DATETIME NULL, last_check_at DATETIME NULL, sent_at DATETIME NULL, expires_at DATETIME NULL, fail_count INT NOT NULL DEFAULT 0, status VARCHAR(20) NOT NULL DEFAULT 'active', updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
	`CREATE TABLE IF NOT EXISTS usage_events (id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, event_key VARCHAR(96) NOT NULL, analytics_id VARCHAR(64) NOT NULL DEFAULT '', visitor_hash VARCHAR(64) NOT NULL DEFAULT '', session_id VARCHAR(64) NOT NULL DEFAULT '', event_name VARCHAR(40) NOT NULL DEFAULT '', page VARCHAR(40) NOT NULL DEFAULT '', feature VARCHAR(40) NOT NULL DEFAULT '', slot_id VARCHAR(64) NOT NULL DEFAULT '', ad_type VARCHAR(24) NOT NULL DEFAULT '', visible_ms INT NOT NULL DEFAULT 0, properties_json TEXT NULL, app_version VARCHAR(40) NOT NULL DEFAULT '', platform VARCHAR(24) NOT NULL DEFAULT '', client_ts DATETIME NULL, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
	`CREATE TABLE IF NOT EXISTS usage_user_daily (date DATE NOT NULL, analytics_id VARCHAR(64) NOT NULL, open_count INT NOT NULL DEFAULT 0, session_count INT NOT NULL DEFAULT 0, active_seconds INT NOT NULL DEFAULT 0, page_views INT NOT NULL DEFAULT 0, event_count INT NOT NULL DEFAULT 0, feature_actions INT NOT NULL DEFAULT 0, first_seen_at DATETIME NULL, last_seen_at DATETIME NULL, updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, PRIMARY KEY(date,analytics_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
	`CREATE TABLE IF NOT EXISTS usage_slot_user_daily (date DATE NOT NULL, analytics_id VARCHAR(64) NOT NULL, slot_id VARCHAR(64) NOT NULL, ad_type VARCHAR(24) NOT NULL DEFAULT '', page VARCHAR(40) NOT NULL DEFAULT '', views INT NOT NULL DEFAULT 0, visible_count INT NOT NULL DEFAULT 0, visible_ms INT NOT NULL DEFAULT 0, requests INT NOT NULL DEFAULT 0, impressions INT NOT NULL DEFAULT 0, clicks INT NOT NULL DEFAULT 0, closes INT NOT NULL DEFAULT 0, first_seen_at DATETIME NULL, last_seen_at DATETIME NULL, updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, PRIMARY KEY(date,analytics_id,slot_id,ad_type)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`,
}

var indexes = []struct{ table, name, columns string }{
	{"courses", "ix_courses_student_id", "student_id"}, {"courses", "ix_courses_user_semester_day", "student_id,semester,day_of_week,start_period"},
	{"exams", "ix_exams_student_id", "student_id"}, {"exams", "ix_exams_user_semester_date", "student_id,semester,exam_date"},
	{"evaluations", "ix_evaluations_student_id", "student_id"}, {"evaluations", "ix_evaluations_user_end", "student_id,end_date"},
	{"grades", "ix_grades_student_id", "student_id"}, {"grades", "ix_grades_user_year_semester", "student_id,academic_year,semester"},
	{"cet_scores", "ix_cet_scores_student_id", "student_id"}, {"cet_scores", "ix_cet_user_type_score", "student_id,cet_type,total_score"},
	{"feedback", "ix_feedback_student_id", "student_id"}, {"audit_courses", "ix_audit_courses_semester", "semester"}, {"audit_courses", "ix_audit_courses_semester_name", "semester,course_name"}, {"audit_courses", "ix_audit_courses_semester_teacher", "semester,teacher"},
	{"audit_favorites", "uq_audit_favorite", "student_id,semester,favorite_key"}, {"audit_favorites", "ix_audit_favorites_user_semester", "student_id,semester"},
	{"reminder_tasks", "uq_reminder_task", "student_id,semester,kind,course_key,teacher_key"}, {"reminder_tasks", "ix_reminder_due", "kind,status,next_check_at"}, {"reminder_tasks", "ix_reminder_user", "student_id,semester,kind"},
	{"usage_events", "uq_usage_events_event_key", "event_key"}, {"usage_events", "ix_usage_events_name_time", "event_name,created_at"}, {"usage_events", "ix_usage_events_user_time", "analytics_id,created_at"}, {"usage_events", "ix_usage_events_slot_time", "slot_id,created_at"}, {"usage_events", "ix_usage_events_page_time", "page,created_at"},
	{"usage_user_daily", "ix_usage_user_daily_date", "date"}, {"usage_slot_user_daily", "ix_usage_slot_daily_date", "date"}, {"usage_slot_user_daily", "ix_usage_slot_daily_slot", "slot_id,date"},
}

var uniqueKeys = []struct {
	table   string
	columns []string
}{
	{"audit_favorites", []string{"student_id", "semester", "favorite_key"}},
	{"reminder_tasks", []string{"student_id", "semester", "kind", "course_key", "teacher_key"}},
	{"usage_events", []string{"event_key"}},
}

func Run(ctx context.Context, db *sql.DB, logger *slog.Logger) ([]string, error) {
	conn, err := db.Conn(ctx)
	if err != nil {
		return nil, err
	}
	defer func() {
		if closeErr := conn.Close(); closeErr != nil && logger != nil {
			logger.Warn("关闭数据库迁移连接失败", "error", closeErr)
		}
	}()
	var acquired sql.NullInt64
	if err = conn.QueryRowContext(ctx, "SELECT GET_LOCK(?, 60)", lockName).Scan(&acquired); err != nil || !acquired.Valid || acquired.Int64 != 1 {
		if err == nil {
			err = fmt.Errorf("获取数据库迁移锁超时")
		}
		return nil, err
	}
	defer func() {
		releaseCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if _, releaseErr := conn.ExecContext(releaseCtx, "SELECT RELEASE_LOCK(?)", lockName); releaseErr != nil && logger != nil {
			logger.Warn("释放数据库迁移锁失败", "error", releaseErr)
		}
	}()

	if _, err = conn.ExecContext(ctx, createTables[0]); err != nil {
		return nil, err
	}
	var exists int
	if err = conn.QueryRowContext(ctx, "SELECT COUNT(*) FROM schema_migrations WHERE version=?", Version).Scan(&exists); err != nil {
		return nil, err
	}
	if exists > 0 {
		return nil, verifyApplied(ctx, conn)
	}
	for _, statement := range createTables {
		if _, err = conn.ExecContext(ctx, statement); err != nil {
			return nil, fmt.Errorf("建表失败: %w", err)
		}
	}
	for _, column := range requiredColumns {
		var count int
		if err = conn.QueryRowContext(ctx, `SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=? AND COLUMN_NAME=?`, column.table, column.name).Scan(&count); err != nil {
			return nil, err
		}
		if count == 0 {
			statement := fmt.Sprintf("ALTER TABLE `%s` ADD COLUMN `%s` %s", column.table, column.name, column.definition)
			if _, err = conn.ExecContext(ctx, statement); err != nil {
				return nil, fmt.Errorf("补列 %s.%s 失败: %w", column.table, column.name, err)
			}
		}
	}
	for _, table := range []string{"audit_courses", "audit_favorites"} {
		var dataType string
		if err = conn.QueryRowContext(ctx, `SELECT DATA_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=? AND COLUMN_NAME='class_info'`, table).Scan(&dataType); err != nil {
			return nil, err
		}
		if !strings.Contains(strings.ToLower(dataType), "text") {
			if _, err = conn.ExecContext(ctx, fmt.Sprintf("ALTER TABLE `%s` MODIFY COLUMN class_info TEXT NULL", table)); err != nil {
				return nil, fmt.Errorf("扩展 %s.class_info 失败: %w", table, err)
			}
		}
	}
	for _, statement := range uniqueKeyCleanupStatements() {
		if _, err = conn.ExecContext(ctx, statement); err != nil {
			return nil, fmt.Errorf("唯一键历史数据清理失败: %w", err)
		}
	}
	for _, index := range indexes {
		var count int
		if err = conn.QueryRowContext(ctx, `SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=? AND INDEX_NAME=?`, index.table, index.name).Scan(&count); err != nil {
			return nil, err
		}
		if count == 0 {
			kind := "INDEX"
			if strings.HasPrefix(index.name, "uq_") {
				kind = "UNIQUE INDEX"
			}
			statement := fmt.Sprintf("CREATE %s `%s` ON `%s` (%s)", kind, index.name, index.table, quoteColumns(index.columns))
			if _, err = conn.ExecContext(ctx, statement); err != nil {
				return nil, fmt.Errorf("创建索引 %s 失败: %w", index.name, err)
			}
		}
	}
	dataStatements := []string{
		`INSERT IGNORE INTO settings(k,v) VALUES ('student_id',''),('student_name',''),('semester',''),('auto_refresh','false'),('refresh_interval','3600')`,
		`INSERT IGNORE INTO user_settings(student_id,k,v,updated_at) SELECT SUBSTRING_INDEX(k,':',1),SUBSTRING(k,LOCATE(':',k)+1),COALESCE(v,''),NOW() FROM settings WHERE k REGEXP '^[0-9]{8,20}:'`,
		`DELETE FROM settings WHERE k REGEXP '^[0-9]{8,20}:'`,
		`INSERT INTO settings(k,v) SELECT CONCAT(student_id,':',k),v FROM user_settings WHERE student_id NOT REGEXP '^[0-9]{8,20}$' ON DUPLICATE KEY UPDATE v=VALUES(v)`,
		`DELETE FROM user_settings WHERE student_id NOT REGEXP '^[0-9]{8,20}$'`,
		`UPDATE audit_courses SET classroom=teacher,teacher='' WHERE classroom='' AND teacher REGEXP '^(设传外教|设传教室|设传实验)[[:space:]]*[0-9]+$'`,
	}
	for _, statement := range dataStatements {
		if _, err = conn.ExecContext(ctx, statement); err != nil {
			return nil, fmt.Errorf("数据迁移失败: %w", err)
		}
	}
	if err = verifySchema(ctx, conn); err != nil {
		return nil, err
	}
	if _, err = conn.ExecContext(ctx, "INSERT INTO schema_migrations(version,applied_at) VALUES (?,NOW())", Version); err != nil {
		return nil, err
	}
	if err = verifyApplied(ctx, conn); err != nil {
		return nil, err
	}
	if logger != nil {
		logger.Info("数据库迁移完成", "version", Version)
	}
	return []string{Version}, nil
}

func Verify(ctx context.Context, db *sql.DB) error {
	return verifyApplied(ctx, db)
}

func verifyApplied(ctx context.Context, db queryer) error {
	if err := verifySchema(ctx, db); err != nil {
		return err
	}
	var count int
	if err := db.QueryRowContext(ctx, "SELECT COUNT(*) FROM schema_migrations WHERE version=?", Version).Scan(&count); err != nil {
		return err
	}
	if count != 1 {
		return fmt.Errorf("数据库缺少迁移版本 %s，请先运行 migrate", Version)
	}
	return nil
}

func verifySchema(ctx context.Context, db queryer) error {
	rows, err := db.QueryContext(ctx, `SELECT TABLE_NAME,COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE()`)
	if err != nil {
		return fmt.Errorf("读取数据库结构失败: %w", err)
	}
	defer rows.Close()
	actual := map[string]map[string]bool{}
	for rows.Next() {
		var table, column string
		if err = rows.Scan(&table, &column); err != nil {
			return err
		}
		if actual[table] == nil {
			actual[table] = map[string]bool{}
		}
		actual[table][column] = true
	}
	if err = rows.Err(); err != nil {
		return err
	}
	required := map[string]map[string]bool{"settings": {"k": true, "v": true}, "schema_migrations": {"version": true}}
	for _, column := range requiredColumns {
		if required[column.table] == nil {
			required[column.table] = map[string]bool{}
		}
		required[column.table][column.name] = true
	}
	var missing []string
	for table, columns := range required {
		if actual[table] == nil {
			missing = append(missing, "表 "+table)
			continue
		}
		for column := range columns {
			if !actual[table][column] {
				missing = append(missing, table+"."+column)
			}
		}
	}
	if len(missing) > 0 {
		sort.Strings(missing)
		return fmt.Errorf("数据库结构未迁移，缺少: %s", strings.Join(missing, ", "))
	}
	for _, table := range []string{"audit_courses", "audit_favorites"} {
		var dataType string
		if err = db.QueryRowContext(ctx, `SELECT DATA_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=? AND COLUMN_NAME='class_info'`, table).Scan(&dataType); err != nil {
			return fmt.Errorf("检查 %s.class_info 类型失败: %w", table, err)
		}
		if !strings.Contains(strings.ToLower(dataType), "text") {
			return fmt.Errorf("数据库结构未迁移，%s.class_info 必须为 TEXT，当前为 %s", table, dataType)
		}
	}
	rows, err = db.QueryContext(ctx, `SELECT TABLE_NAME,INDEX_NAME,COLUMN_NAME,NON_UNIQUE FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME,INDEX_NAME,SEQ_IN_INDEX`)
	if err != nil {
		return fmt.Errorf("读取数据库索引失败: %w", err)
	}
	type actualIndex struct {
		columns   []string
		nonUnique int
	}
	actualIndexes := map[string]*actualIndex{}
	for rows.Next() {
		var table, name, column string
		var nonUnique int
		if err = rows.Scan(&table, &name, &column, &nonUnique); err != nil {
			rows.Close()
			return err
		}
		key := table + "." + name
		if actualIndexes[key] == nil {
			actualIndexes[key] = &actualIndex{nonUnique: nonUnique}
		}
		actualIndexes[key].columns = append(actualIndexes[key].columns, column)
	}
	if err = rows.Close(); err != nil {
		return err
	}
	if err = rows.Err(); err != nil {
		return err
	}
	var invalidIndexes []string
	for _, index := range indexes {
		actual := actualIndexes[index.table+"."+index.name]
		expectUnique := strings.HasPrefix(index.name, "uq_")
		if actual == nil || strings.Join(actual.columns, ",") != index.columns || (expectUnique && actual.nonUnique != 0) {
			invalidIndexes = append(invalidIndexes, index.table+"."+index.name)
		}
	}
	if len(invalidIndexes) > 0 {
		sort.Strings(invalidIndexes)
		return fmt.Errorf("数据库索引未迁移或定义不匹配: %s", strings.Join(invalidIndexes, ", "))
	}
	return nil
}

func uniqueKeyCleanupStatements() []string {
	statements := make([]string, 0, len(uniqueKeys)*2)
	for _, key := range uniqueKeys {
		matches := make([]string, 0, len(key.columns))
		assignments := make([]string, 0, len(key.columns))
		nullChecks := make([]string, 0, len(key.columns))
		for _, column := range key.columns {
			quoted := "`" + column + "`"
			matches = append(matches, "COALESCE(stale."+quoted+",'')=COALESCE(fresh."+quoted+",'')")
			assignments = append(assignments, quoted+"=COALESCE("+quoted+",'')")
			nullChecks = append(nullChecks, quoted+" IS NULL")
		}
		statements = append(statements,
			fmt.Sprintf("DELETE stale FROM `%s` stale JOIN `%s` fresh ON stale.id < fresh.id AND %s", key.table, key.table, strings.Join(matches, " AND ")),
			fmt.Sprintf("UPDATE `%s` SET %s WHERE %s", key.table, strings.Join(assignments, ","), strings.Join(nullChecks, " OR ")),
		)
	}
	return statements
}

func quoteColumns(columns string) string {
	parts := strings.Split(columns, ",")
	for i := range parts {
		parts[i] = "`" + strings.TrimSpace(parts[i]) + "`"
	}
	return strings.Join(parts, ",")
}
