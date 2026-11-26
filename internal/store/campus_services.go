package store

import (
	"context"
	"database/sql"
	"errors"
	"strings"

	"github.com/resetinging/njust-schedule/internal/campus"
)

const campusServiceColumns = `id,COALESCE(category,''),COALESCE(provider_name,''),
	COALESCE(title,''),COALESCE(summary,''),COALESCE(details,''),COALESCE(audience,''),
	COALESCE(price_label,''),COALESCE(campus_scope,'all'),COALESCE(qualification_note,''),
	COALESCE(sponsored,0),COALESCE(verified,0),COALESCE(enabled,0),COALESCE(priority,0),
	DATE_FORMAT(start_at,'%Y-%m-%d'),COALESCE(DATE_FORMAT(end_at,'%Y-%m-%d'),'')`

type CampusServiceLead struct {
	ID                int64  `json:"id"`
	ServiceID         string `json:"service_id"`
	ServiceTitle      string `json:"service_title"`
	ProviderName      string `json:"provider_name"`
	ContactType       string `json:"contact_type"`
	ContactMask       string `json:"contact_mask"`
	ContactCiphertext string `json:"-"`
	Note              string `json:"note"`
	ConsentVersion    string `json:"consent_version"`
	ConsentedAt       string `json:"consented_at"`
	Status            string `json:"status"`
	AdminNote         string `json:"admin_note"`
	CreatedAt         string `json:"created_at"`
	ExpiresAt         string `json:"expires_at"`
}

type CampusServiceLeadInput struct {
	ServiceID         string
	StudentKey        string
	ContactType       string
	ContactCiphertext string
	ContactMask       string
	DedupeKey         string
	Note              string
	ConsentVersion    string
	RetentionDays     int
}

func scanCampusService(scanner interface{ Scan(...any) error }) (campus.Service, error) {
	var item campus.Service
	err := scanner.Scan(
		&item.ID, &item.Category, &item.ProviderName, &item.Title, &item.Summary,
		&item.Details, &item.Audience, &item.PriceLabel, &item.CampusScope,
		&item.QualificationNote, &item.Sponsored, &item.Verified, &item.Enabled,
		&item.Priority, &item.StartDate, &item.EndDate,
	)
	return item, err
}

func (s *Store) PublicCampusServices(
	ctx context.Context,
	category, scope, today string,
	offset, limit int,
) ([]campus.Service, int, error) {
	where := []string{
		"enabled=1", "verified=1", "start_at<=?", "(end_at IS NULL OR end_at>=?)",
	}
	args := []any{today, today}
	if category != "" {
		where = append(where, "category=?")
		args = append(args, category)
	}
	if scope != "" {
		where = append(where, "campus_scope IN (?,?)")
		args = append(args, campus.CampusAll, scope)
	}
	condition := strings.Join(where, " AND ")
	var total int
	if err := s.db.QueryRowContext(ctx,
		"SELECT COUNT(*) FROM campus_services WHERE "+condition,
		args...,
	).Scan(&total); err != nil {
		return nil, 0, err
	}
	queryArgs := append(append([]any(nil), args...), limit, offset)
	rows, err := s.db.QueryContext(ctx,
		"SELECT "+campusServiceColumns+" FROM campus_services WHERE "+condition+
			" ORDER BY priority DESC,start_at DESC,id LIMIT ? OFFSET ?",
		queryArgs...,
	)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()
	items := make([]campus.Service, 0, min(limit, total))
	for rows.Next() {
		item, scanErr := scanCampusService(rows)
		if scanErr != nil {
			return nil, 0, scanErr
		}
		items = append(items, item)
	}
	return items, total, rows.Err()
}

func (s *Store) PublicCampusService(ctx context.Context, id, today string) (campus.Service, error) {
	return scanCampusService(s.db.QueryRowContext(ctx,
		"SELECT "+campusServiceColumns+` FROM campus_services
		 WHERE id=? AND enabled=1 AND verified=1 AND start_at<=?
		   AND (end_at IS NULL OR end_at>=?)`,
		strings.TrimSpace(id), today, today,
	))
}

func (s *Store) AdminCampusServices(ctx context.Context) ([]campus.Service, error) {
	rows, err := s.db.QueryContext(ctx,
		"SELECT "+campusServiceColumns+
			" FROM campus_services ORDER BY priority DESC,start_at DESC,id",
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []campus.Service{}
	for rows.Next() {
		item, scanErr := scanCampusService(rows)
		if scanErr != nil {
			return nil, scanErr
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (s *Store) ReplaceCampusServices(ctx context.Context, services []campus.Service) error {
	return s.transaction(ctx, func(tx *sql.Tx) error {
		stmt, err := tx.PrepareContext(ctx, `INSERT INTO campus_services
			(id,category,provider_name,title,summary,details,audience,price_label,
			 campus_scope,qualification_note,sponsored,verified,enabled,priority,start_at,end_at)
			VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULLIF(?, ''))
			ON DUPLICATE KEY UPDATE
			 category=VALUES(category),provider_name=VALUES(provider_name),title=VALUES(title),
			 summary=VALUES(summary),details=VALUES(details),audience=VALUES(audience),
			 price_label=VALUES(price_label),campus_scope=VALUES(campus_scope),
			 qualification_note=VALUES(qualification_note),sponsored=VALUES(sponsored),
			 verified=VALUES(verified),enabled=VALUES(enabled),priority=VALUES(priority),
			 start_at=VALUES(start_at),end_at=VALUES(end_at),updated_at=NOW()`)
		if err != nil {
			return err
		}
		defer stmt.Close()
		ids := make([]any, 0, len(services))
		for _, item := range services {
			if _, err = stmt.ExecContext(ctx,
				item.ID, item.Category, item.ProviderName, item.Title, item.Summary,
				item.Details, item.Audience, item.PriceLabel, item.CampusScope,
				item.QualificationNote, item.Sponsored, item.Verified, item.Enabled,
				item.Priority, item.StartDate, item.EndDate,
			); err != nil {
				return err
			}
			ids = append(ids, item.ID)
		}
		if len(ids) == 0 {
			_, err = tx.ExecContext(ctx, "DELETE FROM campus_services")
			return err
		}
		marks := strings.TrimRight(strings.Repeat("?,", len(ids)), ",")
		_, err = tx.ExecContext(ctx, "DELETE FROM campus_services WHERE id NOT IN ("+marks+")", ids...)
		return err
	})
}

func (s *Store) CreateCampusServiceLead(
	ctx context.Context,
	input CampusServiceLeadInput,
) (int64, bool, error) {
	if input.RetentionDays <= 0 {
		input.RetentionDays = 30
	}
	result, err := s.db.ExecContext(ctx, `INSERT INTO campus_service_leads
		(service_id,student_key,contact_type,contact_ciphertext,contact_mask,dedupe_key,
		 note,consent_version,consented_at,status,admin_note,created_at,updated_at,expires_at)
		VALUES (?,?,?,?,?,?,?,?,NOW(),'new','',NOW(),NOW(),DATE_ADD(NOW(), INTERVAL ? DAY))
		ON DUPLICATE KEY UPDATE id=id`,
		input.ServiceID, input.StudentKey, input.ContactType, input.ContactCiphertext,
		input.ContactMask, input.DedupeKey, input.Note, input.ConsentVersion,
		input.RetentionDays,
	)
	if err != nil {
		return 0, false, err
	}
	affected, err := result.RowsAffected()
	if err != nil {
		return 0, false, err
	}
	if affected == 0 {
		return 0, false, nil
	}
	id, err := result.LastInsertId()
	return id, true, err
}

const campusServiceLeadColumns = `l.id,COALESCE(l.service_id,''),COALESCE(s.title,''),
	COALESCE(s.provider_name,''),COALESCE(l.contact_type,''),COALESCE(l.contact_mask,''),
	COALESCE(l.contact_ciphertext,''),COALESCE(l.note,''),COALESCE(l.consent_version,''),
	COALESCE(DATE_FORMAT(l.consented_at,'%Y-%m-%d %H:%i:%s'),''),COALESCE(l.status,'new'),
	COALESCE(l.admin_note,''),COALESCE(DATE_FORMAT(l.created_at,'%Y-%m-%d %H:%i:%s'),''),
	COALESCE(DATE_FORMAT(l.expires_at,'%Y-%m-%d %H:%i:%s'),'')`

func scanCampusServiceLead(scanner interface{ Scan(...any) error }) (CampusServiceLead, error) {
	var item CampusServiceLead
	err := scanner.Scan(
		&item.ID, &item.ServiceID, &item.ServiceTitle, &item.ProviderName,
		&item.ContactType, &item.ContactMask, &item.ContactCiphertext, &item.Note,
		&item.ConsentVersion, &item.ConsentedAt, &item.Status, &item.AdminNote,
		&item.CreatedAt, &item.ExpiresAt,
	)
	return item, err
}

func (s *Store) AdminCampusServiceLeads(
	ctx context.Context,
	status string,
	limit int,
) ([]CampusServiceLead, error) {
	if limit < 1 || limit > 1000 {
		limit = 500
	}
	query := "SELECT " + campusServiceLeadColumns +
		" FROM campus_service_leads l LEFT JOIN campus_services s ON s.id=l.service_id"
	args := []any{}
	if status != "" {
		query += " WHERE l.status=?"
		args = append(args, status)
	}
	query += " ORDER BY l.id DESC LIMIT ?"
	args = append(args, limit)
	rows, err := s.db.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []CampusServiceLead{}
	for rows.Next() {
		item, scanErr := scanCampusServiceLead(rows)
		if scanErr != nil {
			return nil, scanErr
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (s *Store) CampusServiceLead(ctx context.Context, id int64) (CampusServiceLead, error) {
	return scanCampusServiceLead(s.db.QueryRowContext(ctx,
		"SELECT "+campusServiceLeadColumns+
			" FROM campus_service_leads l LEFT JOIN campus_services s ON s.id=l.service_id WHERE l.id=?",
		id,
	))
}

func (s *Store) UpdateCampusServiceLeadStatus(
	ctx context.Context,
	id int64,
	status, note string,
) (bool, error) {
	result, err := s.db.ExecContext(ctx,
		"UPDATE campus_service_leads SET status=?,admin_note=?,updated_at=NOW() WHERE id=?",
		status, note, id,
	)
	if err != nil {
		return false, err
	}
	affected, err := result.RowsAffected()
	if err != nil {
		return false, err
	}
	if affected > 0 {
		return true, nil
	}
	var existing int64
	if err = s.db.QueryRowContext(ctx,
		"SELECT id FROM campus_service_leads WHERE id=?",
		id,
	).Scan(&existing); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return false, nil
		}
		return false, err
	}
	return existing == id, nil
}

func (s *Store) PurgeExpiredCampusServiceLeads(ctx context.Context) (int64, error) {
	result, err := s.db.ExecContext(ctx,
		"DELETE FROM campus_service_leads WHERE expires_at IS NOT NULL AND expires_at<=NOW()",
	)
	if err != nil {
		return 0, err
	}
	return result.RowsAffected()
}

func CampusServiceNotFound(err error) bool {
	return errors.Is(err, sql.ErrNoRows)
}
