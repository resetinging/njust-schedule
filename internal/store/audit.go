package store

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"sort"
	"strconv"
	"strings"
)

type AuditQuery struct {
	Semester                                string
	Names, Teachers, Classrooms             []string
	Keyword                                 string
	Weekday, Start, End, Limit, Offset      int
	NameExact, TeacherExact, ClassroomExact bool
}

func splitValues(raw string) []string {
	raw = strings.NewReplacer("，", ",", "、", ",", ";", ",", "；", ",").Replace(raw)
	seen := map[string]bool{}
	var out []string
	for _, part := range strings.Split(raw, ",") {
		part = strings.TrimSpace(part)
		if part != "" && !seen[part] {
			seen[part] = true
			out = append(out, part)
		}
	}
	return out
}

func addDimension(where *[]string, args *[]any, column string, values []string, exact bool) {
	if len(values) == 0 {
		return
	}
	var ors []string
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value == "" {
			continue
		}
		if exact {
			ors = append(ors, "FIND_IN_SET(?, REPLACE(REPLACE(REPLACE(REPLACE("+column+", '，', ','), '、', ','), '；', ','), ';', ',')) > 0")
			*args = append(*args, value)
		} else {
			ors = append(ors, column+" LIKE ?")
			*args = append(*args, "%"+value+"%")
		}
	}
	if len(ors) > 0 {
		*where = append(*where, "("+strings.Join(ors, " OR ")+")")
	}
}

func auditFilter(q AuditQuery) (string, []any) {
	where := []string{"semester=?"}
	args := []any{q.Semester}
	addDimension(&where, &args, "course_name", q.Names, q.NameExact)
	addDimension(&where, &args, "teacher", q.Teachers, q.TeacherExact)
	addDimension(&where, &args, "classroom", q.Classrooms, q.ClassroomExact)
	if q.Keyword != "" {
		where = append(where, "(course_name LIKE ? OR class_info LIKE ? OR teacher LIKE ? OR classroom LIKE ?)")
		like := "%" + q.Keyword + "%"
		args = append(args, like, like, like, like)
	}
	if q.Weekday > 0 {
		where = append(where, "day_of_week=?")
		args = append(args, q.Weekday)
	}
	if q.Start > 0 {
		where = append(where, "end_period>=?")
		args = append(args, q.Start)
	}
	if q.End > 0 {
		where = append(where, "start_period<=?")
		args = append(args, q.End)
	}
	return strings.Join(where, " AND "), args
}

func (s *Store) AuditGroups(ctx context.Context, q AuditQuery) ([]AuditGroup, int, error) {
	where, args := auditFilter(q)
	var total int
	countSQL := "SELECT COUNT(*) FROM (SELECT DISTINCT COALESCE(course_name,''),COALESCE(class_info,'') FROM audit_courses WHERE " + where + ") x"
	if err := s.db.QueryRowContext(ctx, countSQL, args...).Scan(&total); err != nil {
		return nil, 0, err
	}
	limit := q.Limit
	if limit < 1 {
		limit = 20
	}
	if limit > 200 {
		limit = 200
	}
	offset := q.Offset
	if offset < 0 {
		offset = 0
	}
	keySQL := "SELECT DISTINCT COALESCE(course_name,'') AS course_name,COALESCE(class_info,'') AS class_info FROM audit_courses WHERE " + where + " ORDER BY course_name,class_info LIMIT ? OFFSET ?"
	keyArgs := append(append([]any{}, args...), limit, offset)
	rows, err := s.db.QueryContext(ctx, keySQL, keyArgs...)
	if err != nil {
		return nil, 0, err
	}
	type key struct{ name, classInfo string }
	var keys []key
	for rows.Next() {
		var k key
		if err := rows.Scan(&k.name, &k.classInfo); err != nil {
			rows.Close()
			return nil, 0, err
		}
		keys = append(keys, k)
	}
	if err = rows.Err(); err != nil {
		_ = rows.Close()
		return nil, 0, err
	}
	if err = rows.Close(); err != nil {
		return nil, 0, err
	}
	if len(keys) == 0 {
		return []AuditGroup{}, total, nil
	}
	var ors []string
	queryArgs := []any{q.Semester}
	for _, k := range keys {
		ors = append(ors, "(COALESCE(course_name,'')=? AND COALESCE(class_info,'')=?)")
		queryArgs = append(queryArgs, k.name, k.classInfo)
	}
	query := "SELECT COALESCE(course_name,''),COALESCE(class_info,''),COALESCE(teacher,''),COALESCE(classroom,''),COALESCE(day_of_week,0),COALESCE(start_period,0),COALESCE(end_period,0),COALESCE(weeks,'') FROM audit_courses WHERE semester=? AND (" + strings.Join(ors, " OR ") + ") ORDER BY course_name,class_info,day_of_week,start_period"
	all, err := s.db.QueryContext(ctx, query, queryArgs...)
	if err != nil {
		return nil, 0, err
	}
	defer all.Close()
	groups := map[string]*AuditGroup{}
	seenSchedule := map[string]bool{}
	for all.Next() {
		var name, info string
		var item AuditSchedule
		if err := all.Scan(&name, &info, &item.Teacher, &item.Classroom, &item.Day, &item.Start, &item.End, &item.Weeks); err != nil {
			return nil, 0, err
		}
		groupKey := name + "\x00" + info
		g := groups[groupKey]
		if g == nil {
			g = &AuditGroup{Name: name, ClassInfo: info, Schedules: []AuditSchedule{}}
			groups[groupKey] = g
		}
		sig := groupKey + "\x00" + strconv.Itoa(item.Day) + "|" + strconv.Itoa(item.Start) + "|" + strconv.Itoa(item.End) + "|" + item.Weeks + "|" + item.Teacher + "|" + item.Classroom
		if !seenSchedule[sig] {
			seenSchedule[sig] = true
			g.Schedules = append(g.Schedules, item)
		}
	}
	result := make([]AuditGroup, 0, len(keys))
	for _, k := range keys {
		g := groups[k.name+"\x00"+k.classInfo]
		if g == nil {
			continue
		}
		teachers, rooms := []string{}, []string{}
		seenT, seenR := map[string]bool{}, map[string]bool{}
		for _, item := range g.Schedules {
			for _, v := range splitValues(item.Teacher) {
				if !seenT[v] {
					seenT[v] = true
					teachers = append(teachers, v)
				}
			}
			for _, v := range splitValues(item.Classroom) {
				if !seenR[v] {
					seenR[v] = true
					rooms = append(rooms, v)
				}
			}
		}
		g.Teacher = strings.Join(teachers, ",")
		g.Classroom = strings.Join(rooms, ",")
		g.ScheduleCount = len(g.Schedules)
		result = append(result, *g)
	}
	return result, total, all.Err()
}

func (s *Store) AuditOptions(ctx context.Context, semester string) (map[string]any, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT COALESCE(course_name,''),COALESCE(teacher,''),COALESCE(classroom,''),
		COALESCE(day_of_week,0),COALESCE(start_period,0),COALESCE(end_period,0)
		FROM audit_courses WHERE semester=? ORDER BY course_name,class_info`, semester)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	namesSet := map[string]bool{}
	teachersSet := map[string]bool{}
	roomsSet := map[string]bool{}
	type relation struct {
		name            string
		teachers, rooms []string
		day, start, end int
	}
	var rels []relation
	for rows.Next() {
		var name, teacher, room string
		var day, start, end int
		if err := rows.Scan(&name, &teacher, &room, &day, &start, &end); err != nil {
			return nil, err
		}
		if name != "" {
			namesSet[name] = true
		}
		ts := splitValues(teacher)
		rs := splitValues(room)
		for _, v := range ts {
			teachersSet[v] = true
		}
		for _, v := range rs {
			roomsSet[v] = true
		}
		rels = append(rels, relation{name, ts, rs, day, start, end})
	}
	names := sortedKeys(namesSet)
	teachers := sortedKeys(teachersSet)
	rooms := sortedKeys(roomsSet)
	ni := indexMap(names)
	ti := indexMap(teachers)
	ri := indexMap(rooms)
	seen := map[string]bool{}
	relations := make([][]any, 0)
	for _, r := range rels {
		n, ok := ni[r.name]
		if !ok {
			continue
		}
		tis := indices(r.teachers, ti)
		ris := indices(r.rooms, ri)
		raw, err := json.Marshal([]any{n, tis, ris, r.day, r.start, r.end})
		if err != nil {
			return nil, err
		}
		sig := string(raw)
		if seen[sig] {
			continue
		}
		seen[sig] = true
		relations = append(relations, []any{n, tis, ris, r.day, r.start, r.end})
	}
	return map[string]any{"names": names, "teachers": teachers, "classrooms": rooms, "relations": relations}, rows.Err()
}

func sortedKeys(values map[string]bool) []string {
	out := make([]string, 0, len(values))
	for v := range values {
		out = append(out, v)
	}
	sort.Strings(out)
	return out
}
func indexMap(values []string) map[string]int {
	out := map[string]int{}
	for i, v := range values {
		out[v] = i
	}
	return out
}
func indices(values []string, index map[string]int) []int {
	out := []int{}
	seen := map[int]bool{}
	for _, v := range values {
		if n, ok := index[v]; ok && !seen[n] {
			seen[n] = true
			out = append(out, n)
		}
	}
	sort.Ints(out)
	return out
}

func favoriteKey(name, classInfo string) string {
	sum := sha256.Sum256([]byte(strings.TrimSpace(name) + "\x00" + strings.TrimSpace(classInfo)))
	return hex.EncodeToString(sum[:])
}

func (s *Store) AuditFavorites(ctx context.Context, sid, semester string) ([]AuditFavorite, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT id,COALESCE(semester,''),COALESCE(favorite_key,''),
		COALESCE(course_name,''),COALESCE(class_info,''),COALESCE(teacher,''),COALESCE(classroom,''),
		COALESCE(schedules_json,''),created_at FROM audit_favorites
		WHERE student_id=? AND (?='' OR semester=?) ORDER BY id DESC`, sid, semester, semester)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []AuditFavorite
	for rows.Next() {
		var v AuditFavorite
		var raw string
		var created sql.NullTime
		if err := rows.Scan(&v.ID, &v.Semester, &v.FavoriteKey, &v.Name, &v.ClassInfo, &v.Teacher, &v.Classroom, &raw, &created); err != nil {
			return nil, err
		}
		if raw != "" {
			if err := json.Unmarshal([]byte(raw), &v.Schedules); err != nil {
				return nil, err
			}
		}
		if v.Schedules == nil {
			v.Schedules = []AuditSchedule{}
		}
		if created.Valid {
			v.CreatedAt = created.Time.Format("2006-01-02 15:04")
		}
		out = append(out, v)
	}
	return out, rows.Err()
}

func (s *Store) SaveAuditFavorite(ctx context.Context, sid, semester string, group AuditGroup) (AuditFavorite, error) {
	key := favoriteKey(group.Name, group.ClassInfo)
	raw, err := json.Marshal(group.Schedules)
	if err != nil {
		return AuditFavorite{}, err
	}
	_, err = s.db.ExecContext(ctx, `INSERT INTO audit_favorites (student_id,semester,favorite_key,course_name,class_info,teacher,classroom,schedules_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,NOW(),NOW()) ON DUPLICATE KEY UPDATE teacher=VALUES(teacher),classroom=VALUES(classroom),schedules_json=VALUES(schedules_json),updated_at=NOW()`, sid, semester, key, group.Name, group.ClassInfo, group.Teacher, group.Classroom, string(raw))
	if err != nil {
		return AuditFavorite{}, err
	}
	rows, err := s.AuditFavorites(ctx, sid, semester)
	if err != nil {
		return AuditFavorite{}, err
	}
	for _, v := range rows {
		if v.FavoriteKey == key {
			return v, nil
		}
	}
	return AuditFavorite{}, sql.ErrNoRows
}

func (s *Store) DeleteAuditFavorite(ctx context.Context, sid string, id int64) (bool, error) {
	result, err := s.db.ExecContext(ctx, "DELETE FROM audit_favorites WHERE id=? AND student_id=?", id, sid)
	if err != nil {
		return false, err
	}
	n, err := result.RowsAffected()
	return n > 0, err
}

func (s *Store) ReplaceAuditCourses(ctx context.Context, semester string, values []AuditCourse) error {
	return s.transaction(ctx, func(tx *sql.Tx) error {
		if _, err := tx.ExecContext(ctx, "DELETE FROM audit_courses WHERE semester=?", semester); err != nil {
			return err
		}
		stmt, err := tx.PrepareContext(ctx, `INSERT INTO audit_courses (semester,course_name,class_info,teacher,classroom,day_of_week,start_period,end_period,weeks,updated_at) VALUES (?,?,?,?,?,?,?,?,?,NOW())`)
		if err != nil {
			return err
		}
		defer stmt.Close()
		for _, v := range values {
			if _, err := stmt.ExecContext(ctx, semester, v.Name, v.ClassInfo, v.Teacher, v.Classroom, v.Day, v.Start, v.End, v.Weeks); err != nil {
				return err
			}
		}
		return nil
	})
}

func (s *Store) AuditCount(ctx context.Context, semester string) (int, error) {
	var count int
	err := s.db.QueryRowContext(ctx, "SELECT COUNT(*) FROM audit_courses WHERE semester=?", semester).Scan(&count)
	return count, err
}
