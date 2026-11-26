package httpapi

import (
	"crypto/hmac"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/naughtygopher/webgo/v7"
	"github.com/resetinging/njust-schedule/internal/campus"
	"github.com/resetinging/njust-schedule/internal/store"
)

const (
	campusServiceDefaultPageSize = 20
	campusServiceMaxPageSize     = 50
	campusServiceLeadRetention   = 30
)

func (s *Server) campusServices(w http.ResponseWriter, r *http.Request) {
	query := r.URL.Query()
	category := strings.ToLower(strings.TrimSpace(query.Get("category")))
	if category != "" && !campus.ValidCategory(category) {
		writeError(w, http.StatusBadRequest, "服务分类无效")
		return
	}
	scope := strings.ToLower(strings.TrimSpace(query.Get("campus")))
	if scope != "" && !campus.ValidCampusScope(scope) {
		writeError(w, http.StatusBadRequest, "校区筛选无效")
		return
	}
	page := parseInt(query.Get("page"), 1, 1, 10000)
	pageSize := parseInt(query.Get("page_size"), campusServiceDefaultPageSize, 1, campusServiceMaxPageSize)
	items, total, err := s.store.PublicCampusServices(
		r.Context(), category, scope, time.Now().In(beijing).Format("2006-01-02"),
		(page-1)*pageSize, pageSize,
	)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "校园服务读取失败")
		return
	}
	public := make([]campus.PublicService, 0, len(items))
	for _, item := range items {
		public = append(public, item.PublicSummary())
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"success": true, "services": public, "page": page, "page_size": pageSize,
		"total": total, "has_more": page*pageSize < total,
	})
}

func (s *Server) campusServiceDetail(w http.ResponseWriter, r *http.Request) {
	id := webgo.Context(r).Params()["serviceID"]
	if !campus.ValidID(id) {
		writeError(w, http.StatusBadRequest, "服务编号无效")
		return
	}
	item, err := s.store.PublicCampusService(
		r.Context(), id, time.Now().In(beijing).Format("2006-01-02"),
	)
	if store.CampusServiceNotFound(err) {
		writeError(w, http.StatusNotFound, "服务不存在、已下架或已过期")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "校园服务读取失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "service": item.Public()})
}

func (s *Server) createCampusServiceLead(w http.ResponseWriter, r *http.Request) {
	sess, ok := s.requireSession(w, r)
	if !ok {
		return
	}
	serviceID := strings.TrimSpace(webgo.Context(r).Params()["serviceID"])
	if !campus.ValidID(serviceID) {
		writeError(w, http.StatusBadRequest, "服务编号无效")
		return
	}
	var body struct {
		ContactType string `json:"contact_type"`
		Contact     string `json:"contact"`
		Note        string `json:"note"`
		Consent     bool   `json:"consent"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if !body.Consent {
		writeError(w, http.StatusBadRequest, "请先同意将联系方式提供给该服务商")
		return
	}
	note := strings.TrimSpace(body.Note)
	if len([]rune(note)) > 300 {
		writeError(w, http.StatusBadRequest, "补充说明不能超过 300 字")
		return
	}
	contactType := strings.ToLower(strings.TrimSpace(body.ContactType))
	normalized, masked, err := campus.NormalizeContact(contactType, body.Contact)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if s.rateLimited("campus-lead:user:"+sess.StudentID, 3, time.Hour) ||
		s.rateLimited("campus-lead:ip:"+s.clientIP(r), 10, time.Hour) {
		writeError(w, http.StatusTooManyRequests, "咨询提交过于频繁，请稍后再试")
		return
	}
	service, err := s.store.PublicCampusService(
		r.Context(), serviceID, time.Now().In(beijing).Format("2006-01-02"),
	)
	if store.CampusServiceNotFound(err) {
		writeError(w, http.StatusNotFound, "服务不存在、已下架或已过期")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "校园服务读取失败")
		return
	}
	ciphertext, err := s.crypto.Encrypt("campus-service-lead-v1|"+service.ID, normalized)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "联系方式保存失败")
		return
	}
	leadID, inserted, err := s.store.CreateCampusServiceLead(r.Context(), store.CampusServiceLeadInput{
		ServiceID:         service.ID,
		StudentKey:        s.campusLeadHash("student|" + sess.StudentID),
		ContactType:       contactType,
		ContactCiphertext: ciphertext,
		ContactMask:       masked,
		DedupeKey: s.campusLeadHash(strings.Join([]string{
			sess.StudentID, service.ID, contactType, normalized,
		}, "|")),
		Note:           note,
		ConsentVersion: campus.ConsentVersion,
		RetentionDays:  campusServiceLeadRetention,
	})
	if err != nil {
		writeError(w, http.StatusInternalServerError, "咨询提交失败，请稍后再试")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"success": true, "lead_id": leadID, "duplicate": !inserted,
		"message": "咨询已提交，服务商将按你授权的联系方式跟进",
	})
}

func (s *Server) adminCampusServices(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	items, err := s.store.AdminCampusServices(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "校园服务读取失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "services": items})
}

func (s *Server) adminSaveCampusServices(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	var body struct {
		Services []campus.Service `json:"services"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if len(body.Services) > campus.MaxServices {
		writeError(w, http.StatusBadRequest, "校园服务最多 200 条")
		return
	}
	today := time.Now().In(beijing).Format("2006-01-02")
	seen := map[string]bool{}
	for index := range body.Services {
		item := &body.Services[index]
		if strings.TrimSpace(item.ID) == "" {
			item.ID = "campus-" + randomToken(10)
		}
		campus.NormalizeService(item, today)
		if seen[item.ID] {
			writeError(w, http.StatusBadRequest, "校园服务 ID 重复")
			return
		}
		seen[item.ID] = true
		if err := campus.ValidateService(*item); err != nil {
			writeError(w, http.StatusBadRequest, err.Error())
			return
		}
	}
	if err := s.store.ReplaceCampusServices(r.Context(), body.Services); err != nil {
		writeError(w, http.StatusInternalServerError, "校园服务保存失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "services": body.Services})
}

func (s *Server) adminCampusServiceLeads(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	status := strings.ToLower(strings.TrimSpace(r.URL.Query().Get("status")))
	if status != "" && !campus.ValidLeadStatus(status) {
		writeError(w, http.StatusBadRequest, "线索状态无效")
		return
	}
	items, err := s.store.AdminCampusServiceLeads(r.Context(), status, 500)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "咨询线索读取失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "leads": items})
}

func (s *Server) adminRevealCampusServiceLead(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	if s.rateLimited("campus-lead-reveal:"+s.clientIP(r), 60, time.Hour) {
		writeError(w, http.StatusTooManyRequests, "查看联系方式过于频繁，请稍后再试")
		return
	}
	id, err := parseCampusLeadID(r)
	if err != nil {
		writeError(w, http.StatusBadRequest, "线索编号无效")
		return
	}
	item, err := s.store.CampusServiceLead(r.Context(), id)
	if errors.Is(err, sql.ErrNoRows) {
		writeError(w, http.StatusNotFound, "咨询线索不存在")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "咨询线索读取失败")
		return
	}
	var contact string
	if err = s.crypto.Decrypt(
		"campus-service-lead-v1|"+item.ServiceID,
		item.ContactCiphertext,
		&contact,
	); err != nil {
		writeError(w, http.StatusInternalServerError, "联系方式解密失败")
		return
	}
	rid, _ := r.Context().Value(requestIDKey).(string)
	s.logger.Info("管理员查看校园服务联系方式", "rid", rid, "lead_id", item.ID)
	writeJSON(w, http.StatusOK, map[string]any{
		"success": true, "id": item.ID, "contact_type": item.ContactType,
		"contact": contact,
	})
}

func (s *Server) adminUpdateCampusServiceLead(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	id, err := parseCampusLeadID(r)
	if err != nil {
		writeError(w, http.StatusBadRequest, "线索编号无效")
		return
	}
	var body struct {
		Status    string `json:"status"`
		AdminNote string `json:"admin_note"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	body.Status = strings.ToLower(strings.TrimSpace(body.Status))
	body.AdminNote = strings.TrimSpace(body.AdminNote)
	if !campus.ValidLeadStatus(body.Status) {
		writeError(w, http.StatusBadRequest, "线索状态无效")
		return
	}
	if len([]rune(body.AdminNote)) > 300 {
		writeError(w, http.StatusBadRequest, "管理员备注不能超过 300 字")
		return
	}
	updated, err := s.store.UpdateCampusServiceLeadStatus(
		r.Context(), id, body.Status, body.AdminNote,
	)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "咨询线索更新失败")
		return
	}
	if !updated {
		writeError(w, http.StatusNotFound, "咨询线索不存在")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true})
}

func parseCampusLeadID(r *http.Request) (int64, error) {
	raw := webgo.Context(r).Params()["leadID"]
	id, err := strconv.ParseInt(strings.TrimSpace(raw), 10, 64)
	if err != nil || id <= 0 {
		return 0, errors.New("invalid lead id")
	}
	return id, nil
}

func (s *Server) campusLeadHash(value string) string {
	mac := hmac.New(sha256.New, s.cfg.SessionKey)
	_, _ = mac.Write([]byte("campus-lead-v1|" + value))
	return hex.EncodeToString(mac.Sum(nil))
}
