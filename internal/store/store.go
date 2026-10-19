package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"
)

type Store struct{ db *sql.DB }

func New(db *sql.DB) *Store { return &Store{db: db} }

func (s *Store) DB() *sql.DB { return s.db }

func (s *Store) Setting(ctx context.Context, key string) (string, error) {
	var value sql.NullString
	err := s.db.QueryRowContext(ctx, "SELECT v FROM settings WHERE k=?", key).Scan(&value)
	if errors.Is(err, sql.ErrNoRows) {
		return "", nil
	}
	return value.String, err
}

func (s *Store) SetSetting(ctx context.Context, key, value string) error {
	_, err := s.db.ExecContext(ctx, `INSERT INTO settings (k,v) VALUES (?,?)
		ON DUPLICATE KEY UPDATE v=VALUES(v)`, key, value)
	return err
}

func (s *Store) Settings(ctx context.Context, keys ...string) (map[string]string, error) {
	out := map[string]string{}
	if len(keys) == 0 {
		return out, nil
	}
	marks := strings.TrimRight(strings.Repeat("?,", len(keys)), ",")
	args := make([]any, len(keys))
	for index, key := range keys {
		args[index] = key
	}
	rows, err := s.db.QueryContext(ctx, "SELECT k,COALESCE(v,'') FROM settings WHERE k IN ("+marks+")", args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var key, value string
		if err = rows.Scan(&key, &value); err != nil {
			return nil, err
		}
		out[key] = value
	}
	return out, rows.Err()
}

func (s *Store) SetSettings(ctx context.Context, values map[string]string) error {
	if len(values) == 0 {
		return nil
	}
	return s.transaction(ctx, func(tx *sql.Tx) error {
		stmt, err := tx.PrepareContext(ctx, `INSERT INTO settings (k,v) VALUES (?,?)
			ON DUPLICATE KEY UPDATE v=VALUES(v)`)
		if err != nil {
			return err
		}
		defer stmt.Close()
		for key, value := range values {
			if _, err = stmt.ExecContext(ctx, key, value); err != nil {
				return err
			}
		}
		return nil
	})
}

func (s *Store) UserSetting(ctx context.Context, sid, key string) (string, error) {
	var value sql.NullString
	err := s.db.QueryRowContext(ctx, "SELECT v FROM user_settings WHERE student_id=? AND k=?", sid, key).Scan(&value)
	if errors.Is(err, sql.ErrNoRows) {
		return "", nil
	}
	return value.String, err
}

func (s *Store) SetUserSetting(ctx context.Context, sid, key, value string) error {
	_, err := s.db.ExecContext(ctx, `INSERT INTO user_settings (student_id,k,v,updated_at)
		VALUES (?,?,?,NOW()) ON DUPLICATE KEY UPDATE v=VALUES(v),updated_at=NOW()`, sid, key, value)
	return err
}

func (s *Store) SetUserSettings(ctx context.Context, sid string, values map[string]string) error {
	if len(values) == 0 {
		return nil
	}
	return s.transaction(ctx, func(tx *sql.Tx) error {
		stmt, err := tx.PrepareContext(ctx, `INSERT INTO user_settings (student_id,k,v,updated_at)
			VALUES (?,?,?,NOW()) ON DUPLICATE KEY UPDATE v=VALUES(v),updated_at=NOW()`)
		if err != nil {
			return err
		}
		defer stmt.Close()
		for key, value := range values {
			if _, err = stmt.ExecContext(ctx, sid, key, value); err != nil {
				return err
			}
		}
		return nil
	})
}

func (s *Store) DeleteUserSetting(ctx context.Context, sid, key string) error {
	_, err := s.db.ExecContext(ctx, "DELETE FROM user_settings WHERE student_id=? AND k=?", sid, key)
	return err
}

func (s *Store) UserSettings(ctx context.Context, sid string, keys ...string) (map[string]string, error) {
	out := map[string]string{}
	if len(keys) == 0 {
		return out, nil
	}
	marks := strings.TrimRight(strings.Repeat("?,", len(keys)), ",")
	args := make([]any, 0, len(keys)+1)
	args = append(args, sid)
	for _, key := range keys {
		args = append(args, key)
	}
	rows, err := s.db.QueryContext(ctx, "SELECT k,COALESCE(v,'') FROM user_settings WHERE student_id=? AND k IN ("+marks+")", args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var key, value string
		if err := rows.Scan(&key, &value); err != nil {
			return nil, err
		}
		out[key] = value
	}
	return out, rows.Err()
}

func (s *Store) CountUserData(ctx context.Context, sid, semester string) (courses, exams int, err error) {
	err = s.db.QueryRowContext(ctx, `SELECT
		(SELECT COUNT(*) FROM courses WHERE student_id=? AND semester=?),
		(SELECT COUNT(*) FROM exams WHERE student_id=? AND semester=?)`,
		sid, semester, sid, semester).Scan(&courses, &exams)
	return
}

func (s *Store) DataVersions(ctx context.Context, sid, semester string) (map[string]string, error) {
	rows, err := s.db.QueryContext(ctx, `
		SELECT 'courses' AS domain,COUNT(*) AS row_count,COALESCE(MAX(id),0) AS latest_id,MAX(created_at) AS latest_at FROM courses WHERE student_id=? AND semester=?
		UNION ALL
		SELECT 'exams',COUNT(*),COALESCE(MAX(id),0),MAX(created_at) FROM exams WHERE student_id=? AND semester=?
		UNION ALL
		SELECT 'evaluations',COUNT(*),COALESCE(MAX(id),0),MAX(created_at) FROM evaluations WHERE student_id=?
		UNION ALL
		SELECT 'grades',COUNT(*),COALESCE(MAX(id),0),MAX(created_at) FROM grades WHERE student_id=?
		UNION ALL
		SELECT 'cet_scores',COUNT(*),COALESCE(MAX(id),0),MAX(created_at) FROM cet_scores WHERE student_id=?`,
		sid, semester, sid, semester, sid, sid, sid)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[string]string{}
	for rows.Next() {
		var name string
		var count, latestID int64
		var latest sql.NullTime
		if err := rows.Scan(&name, &count, &latestID, &latest); err != nil {
			return nil, err
		}
		if count == 0 {
			out[name] = "0"
			continue
		}
		stamp := int64(0)
		if latest.Valid {
			stamp = latest.Time.Unix()
		}
		out[name] = fmt.Sprintf("%d:%d:%d", count, latestID, stamp)
	}
	return out, rows.Err()
}

func (s *Store) UserIDsForSetting(ctx context.Context, key string) ([]string, error) {
	rows, err := s.db.QueryContext(ctx, "SELECT COALESCE(student_id,'') FROM user_settings WHERE k=? AND COALESCE(v,'')<>''", key)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var sid string
		if err := rows.Scan(&sid); err != nil {
			return nil, err
		}
		out = append(out, strings.TrimSpace(sid))
	}
	return out, rows.Err()
}

func (s *Store) Courses(ctx context.Context, sid, semester string) ([]Course, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT id,COALESCE(name,''),COALESCE(teacher,''),COALESCE(classroom,''),
		COALESCE(day_of_week,0),COALESCE(start_period,0),COALESCE(end_period,0),COALESCE(weeks,''),
		COALESCE(week_type,0),COALESCE(credits,''),COALESCE(course_type,''),COALESCE(raw_data,'')
		FROM courses WHERE student_id=? AND semester=?
		ORDER BY day_of_week,start_period`, sid, semester)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Course
	for rows.Next() {
		var v Course
		if err := rows.Scan(&v.ID, &v.Name, &v.Teacher, &v.Classroom, &v.Day, &v.Start, &v.End, &v.Weeks, &v.WeekType, &v.Credits, &v.CourseType, &v.RawData); err != nil {
			return nil, err
		}
		out = append(out, v)
	}
	return out, rows.Err()
}

func (s *Store) ReplaceCourses(ctx context.Context, sid, semester string, values []Course) error {
	return s.transaction(ctx, func(tx *sql.Tx) error {
		if _, err := tx.ExecContext(ctx, "DELETE FROM courses WHERE student_id=? AND semester=?", sid, semester); err != nil {
			return err
		}
		stmt, err := tx.PrepareContext(ctx, `INSERT INTO courses (student_id,name,teacher,classroom,day_of_week,start_period,end_period,weeks,week_type,semester,credits,course_type,raw_data,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,NOW())`)
		if err != nil {
			return err
		}
		defer stmt.Close()
		for _, v := range values {
			if _, err := stmt.ExecContext(ctx, sid, v.Name, v.Teacher, v.Classroom, v.Day, v.Start, v.End, v.Weeks, v.WeekType, semester, v.Credits, v.CourseType, v.RawData); err != nil {
				return err
			}
		}
		return nil
	})
}

func (s *Store) Exams(ctx context.Context, sid, semester string) ([]Exam, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT id,COALESCE(course_name,''),COALESCE(exam_date,''),
		COALESCE(exam_time,''),COALESCE(location,''),COALESCE(seat,''),COALESCE(exam_type,'期末考试')
		FROM exams WHERE student_id=? AND semester=? ORDER BY exam_date`, sid, semester)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Exam
	for rows.Next() {
		var v Exam
		if err := rows.Scan(&v.ID, &v.CourseName, &v.Date, &v.Time, &v.Location, &v.Seat, &v.Type); err != nil {
			return nil, err
		}
		out = append(out, v)
	}
	return out, rows.Err()
}

func (s *Store) ReplaceExams(ctx context.Context, sid, semester string, values []Exam) error {
	return s.transaction(ctx, func(tx *sql.Tx) error {
		if _, err := tx.ExecContext(ctx, "DELETE FROM exams WHERE student_id=? AND semester=?", sid, semester); err != nil {
			return err
		}
		stmt, err := tx.PrepareContext(ctx, `INSERT INTO exams (student_id,course_name,exam_date,exam_time,location,seat,exam_type,semester,created_at) VALUES (?,?,?,?,?,?,?,?,NOW())`)
		if err != nil {
			return err
		}
		defer stmt.Close()
		for _, v := range values {
			if _, err := stmt.ExecContext(ctx, sid, v.CourseName, v.Date, v.Time, v.Location, v.Seat, v.Type, semester); err != nil {
				return err
			}
		}
		return nil
	})
}

func (s *Store) Grades(ctx context.Context, sid, academicYear, semester string) ([]Grade, error) {
	query := `SELECT id,COALESCE(academic_year,''),COALESCE(semester,''),COALESCE(course_code,''),
		COALESCE(course_name,''),COALESCE(score,''),COALESCE(credit,0),COALESCE(grade_point,0),
		COALESCE(course_type,''),COALESCE(course_nature,''),COALESCE(exam_type,'正常考试')
		FROM grades WHERE student_id=?`
	args := []any{sid}
	if academicYear != "" {
		query += " AND academic_year=?"
		args = append(args, academicYear)
	}
	if semester != "" {
		query += " AND semester=?"
		args = append(args, semester)
	}
	query += " ORDER BY academic_year DESC,semester DESC,course_type,course_name"
	rows, err := s.db.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Grade
	for rows.Next() {
		var v Grade
		if err := rows.Scan(&v.ID, &v.AcademicYear, &v.Semester, &v.CourseCode, &v.CourseName, &v.Score, &v.Credit, &v.GradePoint, &v.CourseType, &v.CourseNature, &v.ExamType); err != nil {
			return nil, err
		}
		out = append(out, v)
	}
	return out, rows.Err()
}

func (s *Store) GradeSemesters(ctx context.Context, sid string) ([]string, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT DISTINCT COALESCE(academic_year,'') AS academic_year,COALESCE(semester,'') AS semester FROM grades WHERE student_id=? ORDER BY academic_year DESC,semester DESC`, sid)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var y, sem string
		if err := rows.Scan(&y, &sem); err != nil {
			return nil, err
		}
		out = append(out, y+"-"+sem)
	}
	return out, rows.Err()
}

func (s *Store) ReplaceGrades(ctx context.Context, sid string, values []Grade) error {
	if len(values) == 0 {
		return nil
	}
	return s.transaction(ctx, func(tx *sql.Tx) error {
		if _, err := tx.ExecContext(ctx, "DELETE FROM grades WHERE student_id=?", sid); err != nil {
			return err
		}
		stmt, err := tx.PrepareContext(ctx, `INSERT INTO grades (student_id,academic_year,semester,course_code,course_name,score,credit,grade_point,course_type,course_nature,exam_type,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,NOW())`)
		if err != nil {
			return err
		}
		defer stmt.Close()
		for _, v := range values {
			if _, err := stmt.ExecContext(ctx, sid, v.AcademicYear, v.Semester, v.CourseCode, v.CourseName, v.Score, v.Credit, v.GradePoint, v.CourseType, v.CourseNature, v.ExamType); err != nil {
				return err
			}
		}
		return nil
	})
}

func (s *Store) CETScores(ctx context.Context, sid string) ([]CETScore, error) {
	rows, err := s.db.QueryContext(ctx, "SELECT COALESCE(cet_type,''),COALESCE(total_score,0),COALESCE(exam_date,'') FROM cet_scores WHERE student_id=?", sid)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	best := map[string]CETScore{}
	for rows.Next() {
		var v CETScore
		if err := rows.Scan(&v.Type, &v.Score, &v.ExamDate); err != nil {
			return nil, err
		}
		if old, ok := best[v.Type]; !ok || v.Score > old.Score {
			best[v.Type] = v
		}
	}
	out := make([]CETScore, 0, len(best))
	for _, v := range best {
		out = append(out, v)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Type < out[j].Type })
	return out, rows.Err()
}

func (s *Store) ReplaceCETScores(ctx context.Context, sid string, values []CETScore) error {
	if len(values) == 0 {
		return nil
	}
	return s.transaction(ctx, func(tx *sql.Tx) error {
		if _, err := tx.ExecContext(ctx, "DELETE FROM cet_scores WHERE student_id=?", sid); err != nil {
			return err
		}
		stmt, err := tx.PrepareContext(ctx, `INSERT INTO cet_scores (student_id,cet_type,total_score,exam_date,created_at) VALUES (?,?,?,?,NOW())`)
		if err != nil {
			return err
		}
		defer stmt.Close()
		for _, v := range values {
			if _, err := stmt.ExecContext(ctx, sid, v.Type, v.Score, v.ExamDate); err != nil {
				return err
			}
		}
		return nil
	})
}

func (s *Store) Evaluations(ctx context.Context, sid string) ([]Evaluation, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT id,COALESCE(semester,''),COALESCE(category,''),COALESCE(batch,''),
		COALESCE(start_date,''),COALESCE(end_date,''),COALESCE(is_done,0),COALESCE(items_json,'')
		FROM evaluations WHERE student_id=? ORDER BY end_date`, sid)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	dedupe := map[string]Evaluation{}
	for rows.Next() {
		var v Evaluation
		var done int
		var raw string
		if err := rows.Scan(&v.ID, &v.Semester, &v.Category, &v.Batch, &v.StartDate, &v.EndDate, &done, &raw); err != nil {
			return nil, err
		}
		v.IsDone = done != 0
		if raw != "" {
			if err := json.Unmarshal([]byte(raw), &v.Items); err != nil {
				return nil, err
			}
		}
		key := v.Batch + "\x00" + v.Category + "\x00" + v.EndDate
		if old, ok := dedupe[key]; !ok || len(v.Items) > len(old.Items) {
			dedupe[key] = v
		}
	}
	out := make([]Evaluation, 0, len(dedupe))
	for _, v := range dedupe {
		out = append(out, v)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].EndDate < out[j].EndDate })
	return out, rows.Err()
}

func (s *Store) ReplaceEvaluations(ctx context.Context, sid string, values []Evaluation) error {
	return s.transaction(ctx, func(tx *sql.Tx) error {
		if _, err := tx.ExecContext(ctx, "DELETE FROM evaluations WHERE student_id=?", sid); err != nil {
			return err
		}
		stmt, err := tx.PrepareContext(ctx, `INSERT INTO evaluations (student_id,semester,category,batch,start_date,end_date,is_done,items_json,created_at) VALUES (?,?,?,?,?,?,?,?,NOW())`)
		if err != nil {
			return err
		}
		defer stmt.Close()
		for _, v := range values {
			raw, err := json.Marshal(v.Items)
			if err != nil {
				return err
			}
			if _, err := stmt.ExecContext(ctx, sid, v.Semester, v.Category, v.Batch, v.StartDate, v.EndDate, v.IsDone, string(raw)); err != nil {
				return err
			}
		}
		return nil
	})
}

func (s *Store) ClearSemester(ctx context.Context, sid, semester string) error {
	return s.transaction(ctx, func(tx *sql.Tx) error {
		for _, table := range []string{"courses", "exams"} {
			if _, err := tx.ExecContext(ctx, fmt.Sprintf("DELETE FROM %s WHERE student_id=? AND semester=?", table), sid, semester); err != nil {
				return err
			}
		}
		_, err := tx.ExecContext(ctx, `UPDATE reminder_tasks SET status='disabled',stage='stale',next_check_at=NULL WHERE student_id=? AND semester=?`, sid, semester)
		return err
	})
}

func (s *Store) transaction(ctx context.Context, fn func(*sql.Tx) error) error {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	if err = fn(tx); err != nil {
		_ = tx.Rollback()
		return err
	}
	return tx.Commit()
}

func nullableTime(v sql.NullTime) *time.Time {
	if !v.Valid {
		return nil
	}
	return &v.Time
}
