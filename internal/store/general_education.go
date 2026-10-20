package store

import (
	"context"
	"database/sql"
	"fmt"
	"strings"
	"time"
)

func (s *Store) ReplaceGeneralEducationCourses(ctx context.Context, semester string, values []GeneralEducationCourse) error {
	return s.transaction(ctx, func(tx *sql.Tx) error {
		existing, err := generalEducationDetails(ctx, tx, semester)
		if err != nil {
			return err
		}
		if _, err = tx.ExecContext(ctx, "DELETE FROM general_education_syllabi WHERE semester=?", semester); err != nil {
			return err
		}
		stmt, err := tx.PrepareContext(ctx, `INSERT INTO general_education_syllabi
			(semester,course_code,course_name,department,credit,hours,assessment,attribute,syllabus_id,has_syllabus,detail_json,detail_fetched_at,updated_at)
			VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NOW())`)
		if err != nil {
			return err
		}
		defer stmt.Close()
		for _, value := range values {
			value.CourseCode = strings.TrimSpace(value.CourseCode)
			if value.CourseCode == "" {
				continue
			}
			if !value.HasSyllabus {
				value.SyllabusID = ""
			}
			if old, ok := existing[value.CourseCode]; ok && value.HasSyllabus &&
				value.SyllabusID != "" && old.SyllabusID == value.SyllabusID {
				value.DetailJSON = old.DetailJSON
				if old.DetailFetchedAt > 0 {
					value.DetailFetchedAt = old.DetailFetchedAt
				}
			}
			var detailAt any
			if value.DetailFetchedAt > 0 {
				detailAt = time.Unix(value.DetailFetchedAt, 0)
			}
			if _, err = stmt.ExecContext(ctx,
				semester, value.CourseCode, value.CourseName, value.Department,
				value.Credit, value.Hours, value.Assessment, value.Attribute,
				value.SyllabusID, boolInt(value.HasSyllabus), value.DetailJSON, detailAt,
			); err != nil {
				return err
			}
		}
		return nil
	})
}

func generalEducationDetails(ctx context.Context, tx *sql.Tx, semester string) (map[string]GeneralEducationCourse, error) {
	rows, err := tx.QueryContext(ctx, `SELECT course_code,COALESCE(syllabus_id,''),COALESCE(has_syllabus,0),
		COALESCE(detail_json,''),detail_fetched_at
		FROM general_education_syllabi WHERE semester=? FOR UPDATE`, semester)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	values := map[string]GeneralEducationCourse{}
	for rows.Next() {
		var value GeneralEducationCourse
		var hasSyllabus int
		var fetched sql.NullTime
		if err = rows.Scan(&value.CourseCode, &value.SyllabusID, &hasSyllabus, &value.DetailJSON, &fetched); err != nil {
			return nil, err
		}
		value.HasSyllabus = hasSyllabus != 0
		if fetched.Valid {
			value.DetailFetchedAt = fetched.Time.Unix()
		}
		values[value.CourseCode] = value
	}
	return values, rows.Err()
}

func (s *Store) GeneralEducationCourses(ctx context.Context, semester, keyword string, limit, offset int) ([]GeneralEducationCourse, int, error) {
	where := "semester=?"
	args := []any{semester}
	if keyword = strings.TrimSpace(keyword); keyword != "" {
		pattern := "%" + keyword + "%"
		where += " AND (course_code LIKE ? OR course_name LIKE ? OR department LIKE ? OR attribute LIKE ?)"
		args = append(args, pattern, pattern, pattern, pattern)
	}
	var total int
	if err := s.db.QueryRowContext(ctx, "SELECT COUNT(*) FROM general_education_syllabi WHERE "+where, args...).Scan(&total); err != nil {
		return nil, 0, err
	}
	queryArgs := append(append([]any(nil), args...), limit, offset)
	rows, err := s.db.QueryContext(ctx, `SELECT id,semester,course_code,course_name,department,credit,hours,
		assessment,attribute,syllabus_id,has_syllabus,
		COALESCE(UNIX_TIMESTAMP(detail_fetched_at),0)
		FROM general_education_syllabi WHERE `+where+`
		ORDER BY course_code LIMIT ? OFFSET ?`, queryArgs...)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()
	values := make([]GeneralEducationCourse, 0, min(limit, total))
	for rows.Next() {
		var value GeneralEducationCourse
		var hasSyllabus int
		if err = rows.Scan(
			&value.ID, &value.Semester, &value.CourseCode, &value.CourseName,
			&value.Department, &value.Credit, &value.Hours, &value.Assessment,
			&value.Attribute, &value.SyllabusID, &hasSyllabus, &value.DetailFetchedAt,
		); err != nil {
			return nil, 0, err
		}
		value.HasSyllabus = hasSyllabus != 0
		values = append(values, value)
	}
	return values, total, rows.Err()
}

func (s *Store) GeneralEducationCourseByCode(ctx context.Context, semester, courseCode string) (GeneralEducationCourse, error) {
	var value GeneralEducationCourse
	var hasSyllabus int
	err := s.db.QueryRowContext(ctx, `SELECT id,semester,course_code,course_name,department,credit,hours,
		assessment,attribute,syllabus_id,has_syllabus,COALESCE(detail_json,''),
		COALESCE(UNIX_TIMESTAMP(detail_fetched_at),0)
		FROM general_education_syllabi WHERE semester=? AND course_code=?`,
		semester, courseCode,
	).Scan(
		&value.ID, &value.Semester, &value.CourseCode, &value.CourseName,
		&value.Department, &value.Credit, &value.Hours, &value.Assessment,
		&value.Attribute, &value.SyllabusID, &hasSyllabus, &value.DetailJSON,
		&value.DetailFetchedAt,
	)
	value.HasSyllabus = hasSyllabus != 0
	return value, err
}

func (s *Store) SaveGeneralEducationDetail(ctx context.Context, semester, courseCode, detailJSON string, fetchedAt time.Time) error {
	result, err := s.db.ExecContext(ctx, `UPDATE general_education_syllabi SET detail_json=?,detail_fetched_at=?,updated_at=NOW()
		WHERE semester=? AND course_code=?`, detailJSON, fetchedAt, semester, courseCode)
	if err != nil {
		return err
	}
	affected, err := result.RowsAffected()
	if err != nil {
		return err
	}
	if affected == 0 {
		return fmt.Errorf("课程不存在或大纲记录未更新")
	}
	return nil
}

func (s *Store) GeneralEducationCount(ctx context.Context, semester string) (int, error) {
	var count int
	err := s.db.QueryRowContext(ctx, "SELECT COUNT(*) FROM general_education_syllabi WHERE semester=?", semester).Scan(&count)
	return count, err
}

func boolInt(value bool) int {
	if value {
		return 1
	}
	return 0
}
