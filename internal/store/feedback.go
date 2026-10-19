package store

import (
	"context"
	"database/sql"
	"strings"
)

func scanFeedback(scanner interface{ Scan(...any) error }) (Feedback, error) {
	var v Feedback
	var replied, created sql.NullTime
	err := scanner.Scan(&v.ID, &v.StudentID, &v.StudentName, &v.Type, &v.Content, &v.Status, &v.Reply, &replied, &v.ReplyRead, &created)
	v.RepliedAt = nullableTime(replied)
	v.CreatedAt = nullableTime(created)
	return v, err
}

const feedbackColumns = "id,COALESCE(student_id,''),COALESCE(student_name,''),COALESCE(fb_type,'other'),COALESCE(content,''),COALESCE(status,'pending'),COALESCE(reply,''),replied_at,COALESCE(reply_read,0),created_at"

func (s *Store) CreateFeedback(ctx context.Context, sid, name, kind, content string) (Feedback, error) {
	result, err := s.db.ExecContext(ctx, `INSERT INTO feedback (student_id,student_name,fb_type,content,contact,status,reply,reply_read,created_at) VALUES (?,?,?,?,?,'pending','',0,NOW())`, sid, name, kind, content, "")
	if err != nil {
		return Feedback{}, err
	}
	id, err := result.LastInsertId()
	if err != nil {
		return Feedback{}, err
	}
	return scanFeedback(s.db.QueryRowContext(ctx, "SELECT "+feedbackColumns+" FROM feedback WHERE id=?", id))
}

func (s *Store) FeedbackByUser(ctx context.Context, sid string, limit int) ([]Feedback, error) {
	if limit < 1 || limit > 500 {
		limit = 50
	}
	rows, err := s.db.QueryContext(ctx, "SELECT "+feedbackColumns+" FROM feedback WHERE student_id=? ORDER BY id DESC LIMIT ?", sid, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Feedback
	for rows.Next() {
		v, err := scanFeedback(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, v)
	}
	return out, rows.Err()
}

func (s *Store) FeedbackList(ctx context.Context, status string, limit int) ([]Feedback, error) {
	if limit < 1 || limit > 1000 {
		limit = 500
	}
	query := "SELECT " + feedbackColumns + " FROM feedback"
	args := []any{}
	if status != "" {
		query += " WHERE status=?"
		args = append(args, status)
	}
	query += " ORDER BY id DESC LIMIT ?"
	args = append(args, limit)
	rows, err := s.db.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Feedback
	for rows.Next() {
		v, err := scanFeedback(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, v)
	}
	return out, rows.Err()
}

func (s *Store) MarkRepliesRead(ctx context.Context, sid string) (int64, error) {
	result, err := s.db.ExecContext(ctx, `UPDATE feedback SET reply_read=1 WHERE student_id=? AND COALESCE(reply,'')<>'' AND reply_read=0`, sid)
	if err != nil {
		return 0, err
	}
	return result.RowsAffected()
}

func (s *Store) FeedbackUnread(ctx context.Context, sid string) (int, error) {
	var count int
	err := s.db.QueryRowContext(ctx, `SELECT COUNT(*) FROM feedback WHERE student_id=? AND COALESCE(reply,'')<>'' AND reply_read=0`, sid).Scan(&count)
	return count, err
}

func (s *Store) SetFeedbackStatus(ctx context.Context, id int64, status string) (bool, error) {
	result, err := s.db.ExecContext(ctx, "UPDATE feedback SET status=? WHERE id=?", status, id)
	if err != nil {
		return false, err
	}
	n, err := result.RowsAffected()
	return n > 0, err
}

func (s *Store) DeleteFeedback(ctx context.Context, id int64) (bool, error) {
	result, err := s.db.ExecContext(ctx, "DELETE FROM feedback WHERE id=?", id)
	if err != nil {
		return false, err
	}
	n, err := result.RowsAffected()
	return n > 0, err
}

func (s *Store) ReplyFeedback(ctx context.Context, id int64, reply string) (Feedback, error) {
	reply = strings.TrimSpace(reply)
	if len([]rune(reply)) > 500 {
		reply = string([]rune(reply)[:500])
	}
	if reply == "" {
		_, err := s.db.ExecContext(ctx, "UPDATE feedback SET reply='',replied_at=NULL WHERE id=?", id)
		if err != nil {
			return Feedback{}, err
		}
	} else {
		_, err := s.db.ExecContext(ctx, "UPDATE feedback SET reply=?,replied_at=NOW(),status='done',reply_read=0 WHERE id=?", reply, id)
		if err != nil {
			return Feedback{}, err
		}
	}
	return scanFeedback(s.db.QueryRowContext(ctx, "SELECT "+feedbackColumns+" FROM feedback WHERE id=?", id))
}
