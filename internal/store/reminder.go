package store

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"
)

type ReminderTask struct {
	ID                                                 int64
	StudentID, Semester, Kind, CourseKey, CourseName   string
	TeacherKey, Teacher, AssessmentType, Stage         string
	CourseEndAt, ExamWaitStartedAt, GradeWaitStartedAt *time.Time
	ExamAt, ExamFinishedAt, GradeFirstSeenAt           *time.Time
	NextCheckAt, LastCheckAt, SentAt, ExpiresAt        *time.Time
	FailCount                                          int
	Status                                             string
}

type ReminderTaskInput struct {
	StudentID, Semester, Kind, CourseKey, CourseName   string
	TeacherKey, Teacher, AssessmentType, Stage         string
	CourseEndAt, ExamWaitStartedAt, GradeWaitStartedAt *time.Time
	NextCheckAt                                        *time.Time
	Status                                             string
}

const reminderColumns = `id,COALESCE(student_id,''),COALESCE(semester,''),COALESCE(kind,'grade'),
	COALESCE(course_key,''),COALESCE(course_name,''),COALESCE(teacher_key,''),COALESCE(teacher_snapshot,''),
	COALESCE(assessment_type,''),COALESCE(stage,'scheduled'),course_end_at,exam_wait_started_at,
	grade_wait_started_at,exam_at,exam_finished_at,grade_first_seen_at,next_check_at,last_check_at,sent_at,
	expires_at,COALESCE(fail_count,0),COALESCE(status,'active')`

func scanReminder(scanner interface{ Scan(...any) error }) (ReminderTask, error) {
	var item ReminderTask
	var courseEnd, examWait, gradeWait, examAt, examFinished, gradeFirst, next, last, sent, expires sql.NullTime
	err := scanner.Scan(&item.ID, &item.StudentID, &item.Semester, &item.Kind, &item.CourseKey, &item.CourseName, &item.TeacherKey, &item.Teacher, &item.AssessmentType, &item.Stage, &courseEnd, &examWait, &gradeWait, &examAt, &examFinished, &gradeFirst, &next, &last, &sent, &expires, &item.FailCount, &item.Status)
	item.CourseEndAt, item.ExamWaitStartedAt, item.GradeWaitStartedAt = nullableTime(courseEnd), nullableTime(examWait), nullableTime(gradeWait)
	item.ExamAt, item.ExamFinishedAt, item.GradeFirstSeenAt = nullableTime(examAt), nullableTime(examFinished), nullableTime(gradeFirst)
	item.NextCheckAt, item.LastCheckAt, item.SentAt, item.ExpiresAt = nullableTime(next), nullableTime(last), nullableTime(sent), nullableTime(expires)
	return item, err
}

func (s *Store) UpsertReminderTask(ctx context.Context, value ReminderTaskInput) error {
	_, err := s.db.ExecContext(ctx, `INSERT INTO reminder_tasks
		(student_id,semester,kind,course_key,course_name,teacher_key,teacher_snapshot,assessment_type,stage,course_end_at,exam_wait_started_at,grade_wait_started_at,next_check_at,status,fail_count,updated_at)
		VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,NOW()) ON DUPLICATE KEY UPDATE
		course_name=IF(sent_at IS NULL,VALUES(course_name),course_name),teacher_snapshot=IF(sent_at IS NULL,VALUES(teacher_snapshot),teacher_snapshot),
		assessment_type=IF(sent_at IS NULL,VALUES(assessment_type),assessment_type),stage=IF(sent_at IS NULL,VALUES(stage),stage),
		course_end_at=IF(sent_at IS NULL,VALUES(course_end_at),course_end_at),exam_wait_started_at=IF(sent_at IS NULL,VALUES(exam_wait_started_at),exam_wait_started_at),
		grade_wait_started_at=IF(sent_at IS NULL,VALUES(grade_wait_started_at),grade_wait_started_at),next_check_at=IF(sent_at IS NULL,VALUES(next_check_at),next_check_at),
		status=IF(sent_at IS NULL,VALUES(status),status),updated_at=NOW()`,
		value.StudentID, value.Semester, value.Kind, value.CourseKey, value.CourseName, value.TeacherKey, value.Teacher,
		value.AssessmentType, value.Stage, value.CourseEndAt, value.ExamWaitStartedAt, value.GradeWaitStartedAt, value.NextCheckAt, value.Status)
	return err
}

func (s *Store) DisableUnseenReminderTasks(ctx context.Context, sid, semester, kind string, seen map[string]bool) (int, error) {
	rows, err := s.db.QueryContext(ctx, "SELECT id,COALESCE(course_key,''),COALESCE(teacher_key,'') FROM reminder_tasks WHERE student_id=? AND semester=? AND kind=? AND status='active'", sid, semester, kind)
	if err != nil {
		return 0, err
	}
	type row struct {
		id  int64
		key string
	}
	var stale []row
	for rows.Next() {
		var id int64
		var course, teacher string
		if err = rows.Scan(&id, &course, &teacher); err != nil {
			_ = rows.Close()
			return 0, err
		}
		key := course + "|" + teacher
		if !seen[key] {
			stale = append(stale, row{id, key})
		}
	}
	if err = rows.Err(); err != nil {
		_ = rows.Close()
		return 0, err
	}
	if err = rows.Close(); err != nil {
		return 0, err
	}
	for _, item := range stale {
		if _, err = s.db.ExecContext(ctx, "UPDATE reminder_tasks SET status='disabled',stage='stale',next_check_at=NULL,updated_at=NOW() WHERE id=?", item.id); err != nil {
			return 0, err
		}
	}
	return len(stale), nil
}

func (s *Store) DisableReminderKind(ctx context.Context, sid, semester, kind string) (int64, error) {
	result, err := s.db.ExecContext(ctx, "UPDATE reminder_tasks SET status='disabled',next_check_at=NULL,updated_at=NOW() WHERE student_id=? AND semester=? AND kind=? AND status='active'", sid, semester, kind)
	if err != nil {
		return 0, err
	}
	return result.RowsAffected()
}

func (s *Store) DueReminderTasks(ctx context.Context, now time.Time, limit int) ([]ReminderTask, error) {
	rows, err := s.db.QueryContext(ctx, "SELECT "+reminderColumns+" FROM reminder_tasks WHERE status='active' AND next_check_at IS NOT NULL AND next_check_at<=? ORDER BY next_check_at,id LIMIT ?", now, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []ReminderTask
	for rows.Next() {
		item, err := scanReminder(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (s *Store) ActiveReminderTasks(ctx context.Context, sid, kind string) ([]ReminderTask, error) {
	rows, err := s.db.QueryContext(ctx, "SELECT "+reminderColumns+" FROM reminder_tasks WHERE student_id=? AND kind=? AND status='active'", sid, kind)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []ReminderTask
	for rows.Next() {
		item, err := scanReminder(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (s *Store) DisableOtherReminderTasks(ctx context.Context, sid, kind string, keepID int64) error {
	_, err := s.db.ExecContext(ctx, `UPDATE reminder_tasks SET status='disabled',next_check_at=NULL,updated_at=NOW()
		WHERE student_id=? AND kind=? AND status='active' AND id<>?`, sid, kind, keepID)
	return err
}

func (s *Store) BoostReminderGroup(ctx context.Context, semester, courseKey, teacherKey, excludeSID string, now time.Time) error {
	_, err := s.db.ExecContext(ctx, `UPDATE reminder_tasks SET next_check_at=?,updated_at=NOW()
		WHERE semester=? AND kind='grade' AND course_key=? AND teacher_key=? AND student_id<>?
		AND status='active' AND stage='wait_grade' AND (next_check_at IS NULL OR next_check_at>?)`,
		now, semester, courseKey, teacherKey, excludeSID, now)
	return err
}

func (s *Store) SaveReminderTask(ctx context.Context, item ReminderTask) error {
	_, err := s.db.ExecContext(ctx, `UPDATE reminder_tasks SET stage=?,exam_at=?,exam_finished_at=?,grade_first_seen_at=?,next_check_at=?,last_check_at=?,sent_at=?,expires_at=?,fail_count=?,status=?,grade_wait_started_at=?,updated_at=NOW() WHERE id=?`, item.Stage, item.ExamAt, item.ExamFinishedAt, item.GradeFirstSeenAt, item.NextCheckAt, item.LastCheckAt, item.SentAt, item.ExpiresAt, item.FailCount, item.Status, item.GradeWaitStartedAt, item.ID)
	return err
}

type DueExam struct {
	Exam
	StudentID string
	Semester  string
}

func (s *Store) DueExams(ctx context.Context, dates ...string) ([]DueExam, error) {
	if len(dates) == 0 {
		return nil, nil
	}
	query := `SELECT id,COALESCE(course_name,''),COALESCE(exam_date,''),COALESCE(exam_time,''),
		COALESCE(location,''),COALESCE(seat,''),COALESCE(exam_type,'期末考试'),
		COALESCE(TRIM(student_id),''),COALESCE(semester,'') FROM exams WHERE `
	args := make([]any, 0, len(dates))
	for i, date := range dates {
		if i > 0 {
			query += " OR "
		}
		query += "exam_date LIKE ?"
		args = append(args, date+"%")
	}
	query += " ORDER BY exam_date,exam_time,id"
	rows, err := s.db.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []DueExam
	for rows.Next() {
		var item DueExam
		if err = rows.Scan(&item.ID, &item.CourseName, &item.Date, &item.Time, &item.Location, &item.Seat, &item.Type, &item.StudentID, &item.Semester); err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (s *Store) TryClaimUserSetting(ctx context.Context, sid, key, value string) (bool, error) {
	claimed := false
	err := s.transaction(ctx, func(tx *sql.Tx) error {
		result, err := tx.ExecContext(ctx, `INSERT IGNORE INTO user_settings (student_id,k,v,updated_at) VALUES (?,?,?,NOW())`, sid, key, value)
		if err != nil {
			return err
		}
		count, err := result.RowsAffected()
		if err != nil {
			return err
		}
		if count > 0 {
			claimed = true
			return nil
		}
		var current string
		if err = tx.QueryRowContext(ctx, "SELECT COALESCE(v,'') FROM user_settings WHERE student_id=? AND k=? FOR UPDATE", sid, key).Scan(&current); err != nil {
			return err
		}
		const claimLease = 15 * time.Minute
		if strings.HasPrefix(current, "pending:") {
			stamp, parseErr := strconv.ParseInt(strings.TrimPrefix(current, "pending:"), 10, 64)
			if parseErr == nil && time.Since(time.Unix(stamp, 0)) >= claimLease {
				if _, err = tx.ExecContext(ctx, "UPDATE user_settings SET v=?,updated_at=NOW() WHERE student_id=? AND k=?", value, sid, key); err != nil {
					return err
				}
				claimed = true
			}
		}
		return nil
	})
	return claimed, err
}

func (s *Store) ReminderClaimState(ctx context.Context, sid, key string) (string, error) {
	value, err := s.UserSetting(ctx, sid, key)
	if err != nil || value == "" {
		return "", err
	}
	if strings.HasPrefix(value, "pending:") {
		return "pending", nil
	}
	// Legacy claims stored a date. They were only retained after a successful send.
	return "sent", nil
}

func (s *Store) MarkReminderClaimSent(ctx context.Context, sid, key string, sentAt time.Time) error {
	result, err := s.db.ExecContext(ctx, "UPDATE user_settings SET v=?,updated_at=NOW() WHERE student_id=? AND k=?", "sent:"+strconv.FormatInt(sentAt.Unix(), 10), sid, key)
	if err != nil {
		return err
	}
	count, err := result.RowsAffected()
	if err != nil {
		return err
	}
	if count == 0 {
		return fmt.Errorf("提醒占用记录不存在")
	}
	return nil
}

func (s *Store) CompleteReminderTask(ctx context.Context, item ReminderTask, claimKey string, sentAt time.Time) error {
	return s.transaction(ctx, func(tx *sql.Tx) error {
		result, err := tx.ExecContext(ctx, `UPDATE reminder_tasks SET stage=?,exam_at=?,exam_finished_at=?,grade_first_seen_at=?,next_check_at=?,last_check_at=?,sent_at=?,expires_at=?,fail_count=?,status=?,grade_wait_started_at=?,updated_at=NOW() WHERE id=?`, item.Stage, item.ExamAt, item.ExamFinishedAt, item.GradeFirstSeenAt, item.NextCheckAt, item.LastCheckAt, item.SentAt, item.ExpiresAt, item.FailCount, item.Status, item.GradeWaitStartedAt, item.ID)
		if err != nil {
			return err
		}
		count, err := result.RowsAffected()
		if err != nil {
			return err
		}
		if count == 0 {
			return fmt.Errorf("提醒任务 %d 不存在", item.ID)
		}
		result, err = tx.ExecContext(ctx, "UPDATE user_settings SET v=?,updated_at=NOW() WHERE student_id=? AND k=?", "sent:"+strconv.FormatInt(sentAt.Unix(), 10), item.StudentID, claimKey)
		if err != nil {
			return err
		}
		count, err = result.RowsAffected()
		if err != nil {
			return err
		}
		if count == 0 {
			return fmt.Errorf("提醒占用记录不存在")
		}
		return nil
	})
}

func (s *Store) DeleteClaim(ctx context.Context, sid, key string) error {
	_, err := s.db.ExecContext(ctx, "DELETE FROM user_settings WHERE student_id=? AND k=?", sid, key)
	return err
}

func (s *Store) ReminderTaskByID(ctx context.Context, id int64) (ReminderTask, error) {
	item, err := scanReminder(s.db.QueryRowContext(ctx, "SELECT "+reminderColumns+" FROM reminder_tasks WHERE id=?", id))
	if errors.Is(err, sql.ErrNoRows) {
		return ReminderTask{}, sql.ErrNoRows
	}
	return item, err
}
