package store

import (
	"context"
	"database/sql"
	"fmt"
	"sort"
	"strings"
)

type AdminUser struct {
	StudentID string   `json:"student_id"`
	Name      string   `json:"name"`
	Semester  string   `json:"semester"`
	Courses   int      `json:"courses"`
	Exams     int      `json:"exams"`
	Grades    int      `json:"grades"`
	BestGPA   *float64 `json:"best_gpa"`
}

type AdminCourse struct {
	Course
	Semester string `json:"semester"`
}

type AdminExam struct {
	Exam
	Semester string `json:"semester"`
}

func (s *Store) AdminCounts(ctx context.Context) (map[string]int64, error) {
	tables := map[string]string{"courses": "courses", "exams": "exams", "evaluations": "evaluations", "grades": "grades", "cet": "cet_scores"}
	out := make(map[string]int64, len(tables))
	for key, table := range tables {
		var count int64
		if err := s.db.QueryRowContext(ctx, "SELECT COUNT(*) FROM "+table).Scan(&count); err != nil {
			return nil, err
		}
		out[key] = count
	}
	return out, nil
}

func (s *Store) AdminUsers(ctx context.Context) ([]AdminUser, error) {
	const query = `SELECT ids.sid,
		COALESCE(meta.name,''),COALESCE(meta.semester,''),
		COALESCE(c.cnt,0),COALESCE(e.cnt,0),COALESCE(g.cnt,0),g.best_gpa
	FROM (
		SELECT TRIM(student_id) sid FROM user_settings WHERE TRIM(student_id)<>''
		UNION SELECT TRIM(student_id) FROM courses WHERE TRIM(student_id)<>''
		UNION SELECT TRIM(student_id) FROM exams WHERE TRIM(student_id)<>''
		UNION SELECT TRIM(student_id) FROM evaluations WHERE TRIM(student_id)<>''
		UNION SELECT TRIM(student_id) FROM grades WHERE TRIM(student_id)<>''
		UNION SELECT TRIM(student_id) FROM cet_scores WHERE TRIM(student_id)<>''
	) ids
	LEFT JOIN (
		SELECT TRIM(student_id) sid,
		MAX(CASE WHEN k='name' THEN v ELSE '' END) name,
		MAX(CASE WHEN k='semester' THEN v ELSE '' END) semester
		FROM user_settings WHERE k IN ('name','semester') GROUP BY TRIM(student_id)
	) meta ON meta.sid=ids.sid
	LEFT JOIN (SELECT TRIM(student_id) sid,COUNT(*) cnt FROM courses GROUP BY TRIM(student_id)) c ON c.sid=ids.sid
	LEFT JOIN (SELECT TRIM(student_id) sid,COUNT(*) cnt FROM exams GROUP BY TRIM(student_id)) e ON e.sid=ids.sid
	LEFT JOIN (SELECT TRIM(student_id) sid,COUNT(*) cnt,MAX(NULLIF(grade_point,0)) best_gpa FROM grades GROUP BY TRIM(student_id)) g ON g.sid=ids.sid
	ORDER BY ids.sid`
	rows, err := s.db.QueryContext(ctx, query)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []AdminUser
	for rows.Next() {
		var item AdminUser
		var best sql.NullFloat64
		if err = rows.Scan(&item.StudentID, &item.Name, &item.Semester, &item.Courses, &item.Exams, &item.Grades, &best); err != nil {
			return nil, err
		}
		if best.Valid {
			value := best.Float64
			item.BestGPA = &value
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (s *Store) AdminCourses(ctx context.Context, sid string) ([]AdminCourse, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT id,COALESCE(name,''),COALESCE(teacher,''),COALESCE(classroom,''),
		COALESCE(day_of_week,0),COALESCE(start_period,0),COALESCE(end_period,0),COALESCE(weeks,''),
		COALESCE(week_type,0),COALESCE(credits,''),COALESCE(course_type,''),COALESCE(raw_data,''),COALESCE(semester,'')
		FROM courses WHERE TRIM(student_id)=? ORDER BY semester,day_of_week,start_period`, strings.TrimSpace(sid))
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []AdminCourse
	for rows.Next() {
		var item AdminCourse
		if err = rows.Scan(&item.ID, &item.Name, &item.Teacher, &item.Classroom, &item.Day, &item.Start, &item.End, &item.Weeks, &item.WeekType, &item.Credits, &item.CourseType, &item.RawData, &item.Semester); err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (s *Store) AdminExams(ctx context.Context, sid string) ([]AdminExam, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT id,COALESCE(course_name,''),COALESCE(exam_date,''),COALESCE(exam_time,''),
		COALESCE(location,''),COALESCE(seat,''),COALESCE(exam_type,'期末考试'),COALESCE(semester,'')
		FROM exams WHERE TRIM(student_id)=? ORDER BY exam_date`, strings.TrimSpace(sid))
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []AdminExam
	for rows.Next() {
		var item AdminExam
		if err = rows.Scan(&item.ID, &item.CourseName, &item.Date, &item.Time, &item.Location, &item.Seat, &item.Type, &item.Semester); err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

type GradeStatRow struct {
	StudentID, Score, AcademicYear, Semester string
	Credit, GradePoint                       float64
}

func (s *Store) AllGradeStats(ctx context.Context) ([]GradeStatRow, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT COALESCE(TRIM(student_id),''),COALESCE(score,''),COALESCE(credit,0),COALESCE(grade_point,0),COALESCE(academic_year,''),COALESCE(semester,'') FROM grades`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []GradeStatRow
	for rows.Next() {
		var item GradeStatRow
		if err = rows.Scan(&item.StudentID, &item.Score, &item.Credit, &item.GradePoint, &item.AcademicYear, &item.Semester); err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

type UsageSummary struct {
	ActiveDays int
	LastActive string
}

func (s *Store) UsageSummaries(ctx context.Context, analyticsToSID map[string]string, days int) (map[string]UsageSummary, error) {
	out := map[string]UsageSummary{}
	if len(analyticsToSID) == 0 {
		return out, nil
	}
	keys := make([]string, 0, len(analyticsToSID))
	for key := range analyticsToSID {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	marks := strings.TrimRight(strings.Repeat("?,", len(keys)), ",")
	args := make([]any, 0, len(keys)+1)
	args = append(args, days-1)
	for _, key := range keys {
		args = append(args, key)
	}
	query := fmt.Sprintf(`SELECT COALESCE(analytics_id,''),COUNT(date),DATE_FORMAT(MAX(last_seen_at),'%%Y-%%m-%%d %%H:%%i') FROM usage_user_daily WHERE date>=DATE_SUB(CURDATE(),INTERVAL ? DAY) AND analytics_id IN (%s) GROUP BY analytics_id`, marks)
	rows, err := s.db.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var value UsageSummary
		var last sql.NullString
		if err = rows.Scan(&id, &value.ActiveDays, &last); err != nil {
			return nil, err
		}
		value.LastActive = last.String
		out[analyticsToSID[id]] = value
	}
	return out, rows.Err()
}
