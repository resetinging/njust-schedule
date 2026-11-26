package store

import (
	"context"
	"regexp"
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/resetinging/njust-schedule/internal/campus"
)

func TestPublicCampusServicesFiltersAndPaginates(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()

	mock.ExpectQuery(regexp.QuoteMeta("SELECT COUNT(*) FROM campus_services")).
		WithArgs("2026-11-24", "2026-11-24", campus.CategoryGraduate, campus.CampusAll, campus.CampusJiangyin).
		WillReturnRows(sqlmock.NewRows([]string{"count"}).AddRow(1))
	mock.ExpectQuery("SELECT id,COALESCE").
		WithArgs("2026-11-24", "2026-11-24", campus.CategoryGraduate, campus.CampusAll, campus.CampusJiangyin, 20, 0).
		WillReturnRows(sqlmock.NewRows([]string{
			"id", "category", "provider_name", "title", "summary", "details", "audience",
			"price_label", "campus_scope", "qualification_note", "sponsored", "verified",
			"enabled", "priority", "start_at", "end_at",
		}).AddRow(
			"campus-1", campus.CategoryGraduate, "机构", "保研咨询", "摘要", "",
			"大三学生", "按次", campus.CampusJiangyin, "已审核", true, true, true,
			10, "2026-11-01", "2026-12-31",
		))

	items, total, err := New(db).PublicCampusServices(
		context.Background(), campus.CategoryGraduate, campus.CampusJiangyin,
		"2026-11-24", 0, 20,
	)
	if err != nil {
		t.Fatal(err)
	}
	if total != 1 || len(items) != 1 || items[0].ID != "campus-1" || !items[0].Verified {
		t.Fatalf("items=%+v total=%d", items, total)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestCreateCampusServiceLeadHandlesDuplicate(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()

	input := CampusServiceLeadInput{
		ServiceID: "campus-1", StudentKey: "student", ContactType: campus.ContactPhone,
		ContactCiphertext: "cipher", ContactMask: "138****8000", DedupeKey: "dedupe",
		ConsentVersion: campus.ConsentVersion, RetentionDays: 30,
	}
	mock.ExpectExec("INSERT INTO campus_service_leads").
		WithArgs(
			input.ServiceID, input.StudentKey, input.ContactType, input.ContactCiphertext,
			input.ContactMask, input.DedupeKey, input.Note, input.ConsentVersion,
			input.RetentionDays,
		).
		WillReturnResult(sqlmock.NewResult(0, 0))
	id, inserted, err := New(db).CreateCampusServiceLead(context.Background(), input)
	if err != nil {
		t.Fatal(err)
	}
	if id != 0 || inserted {
		t.Fatalf("id=%d inserted=%v", id, inserted)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

func TestPurgeExpiredCampusServiceLeads(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	mock.ExpectExec("DELETE FROM campus_service_leads WHERE expires_at").
		WillReturnResult(sqlmock.NewResult(0, 3))
	removed, err := New(db).PurgeExpiredCampusServiceLeads(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if removed != 3 {
		t.Fatalf("removed=%d", removed)
	}
}

func TestUpdateCampusServiceLeadStatusTreatsUnchangedRowAsSuccess(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	mock.ExpectExec("UPDATE campus_service_leads SET status").
		WithArgs("new", "", int64(9)).
		WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectQuery("SELECT id FROM campus_service_leads WHERE id=?").
		WithArgs(int64(9)).
		WillReturnRows(sqlmock.NewRows([]string{"id"}).AddRow(9))
	ok, err := New(db).UpdateCampusServiceLeadStatus(context.Background(), 9, "new", "")
	if err != nil || !ok {
		t.Fatalf("ok=%v err=%v", ok, err)
	}
}

func TestReplaceCampusServicesUpsertsAndPrunes(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	item := campus.Service{
		ID: "campus-1", Category: campus.CategoryExam, ProviderName: "机构",
		Title: "咨询", Summary: "摘要", Audience: "在校生", PriceLabel: "面议",
		CampusScope: campus.CampusAll, Sponsored: true, Verified: true, Enabled: true,
		Priority: 10, StartDate: "2026-11-24",
	}
	mock.ExpectBegin()
	prepared := mock.ExpectPrepare("INSERT INTO campus_services")
	prepared.ExpectExec().WithArgs(
		item.ID, item.Category, item.ProviderName, item.Title, item.Summary,
		item.Details, item.Audience, item.PriceLabel, item.CampusScope,
		item.QualificationNote, item.Sponsored, item.Verified, item.Enabled,
		item.Priority, item.StartDate, item.EndDate,
	).WillReturnResult(sqlmock.NewResult(1, 1))
	mock.ExpectExec("DELETE FROM campus_services WHERE id NOT IN").
		WithArgs(item.ID).
		WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectCommit()
	if err = New(db).ReplaceCampusServices(context.Background(), []campus.Service{item}); err != nil {
		t.Fatal(err)
	}
	if err = mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}
