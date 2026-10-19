package store

import "time"

type Course struct {
	ID         int64  `json:"id"`
	Name       string `json:"name"`
	Teacher    string `json:"teacher"`
	Classroom  string `json:"classroom"`
	Day        int    `json:"day"`
	Start      int    `json:"start"`
	End        int    `json:"end"`
	Weeks      string `json:"weeks"`
	WeekType   int    `json:"week_type"`
	Credits    string `json:"credits"`
	CourseType string `json:"course_type"`
	RawData    string `json:"-"`
}

type Exam struct {
	ID         int64  `json:"id"`
	CourseName string `json:"course_name"`
	Date       string `json:"date"`
	Time       string `json:"time"`
	Location   string `json:"location"`
	Seat       string `json:"seat"`
	Type       string `json:"type"`
}

type Grade struct {
	ID           int64   `json:"id"`
	AcademicYear string  `json:"academic_year"`
	Semester     string  `json:"semester"`
	CourseCode   string  `json:"course_code"`
	CourseName   string  `json:"course_name"`
	Score        string  `json:"score"`
	Credit       float64 `json:"credit"`
	GradePoint   float64 `json:"grade_point"`
	CourseType   string  `json:"course_type"`
	CourseNature string  `json:"course_nature"`
	ExamType     string  `json:"exam_type"`
}

type CETScore struct {
	Type     string  `json:"type"`
	Score    float64 `json:"score"`
	ExamDate string  `json:"exam_date"`
}

type Evaluation struct {
	ID        int64            `json:"id"`
	Semester  string           `json:"semester"`
	Category  string           `json:"category"`
	Batch     string           `json:"batch"`
	StartDate string           `json:"start_date"`
	EndDate   string           `json:"end_date"`
	IsDone    bool             `json:"is_done"`
	Items     []map[string]any `json:"items"`
}

type AuditCourse struct {
	Name      string `json:"name"`
	ClassInfo string `json:"class_info"`
	Teacher   string `json:"teacher"`
	Classroom string `json:"classroom"`
	Day       int    `json:"day"`
	Start     int    `json:"start"`
	End       int    `json:"end"`
	Weeks     string `json:"weeks"`
}

type AuditSchedule struct {
	Day       int    `json:"day"`
	Start     int    `json:"start"`
	End       int    `json:"end"`
	Weeks     string `json:"weeks"`
	Teacher   string `json:"teacher"`
	Classroom string `json:"classroom"`
}

type AuditGroup struct {
	Name          string          `json:"name"`
	ClassInfo     string          `json:"class_info"`
	Teacher       string          `json:"teacher"`
	Classroom     string          `json:"classroom"`
	Schedules     []AuditSchedule `json:"schedules"`
	ScheduleCount int             `json:"schedule_count"`
}

type AuditFavorite struct {
	ID          int64           `json:"id"`
	Semester    string          `json:"semester"`
	FavoriteKey string          `json:"favorite_key"`
	Name        string          `json:"name"`
	ClassInfo   string          `json:"class_info"`
	Teacher     string          `json:"teacher"`
	Classroom   string          `json:"classroom"`
	Schedules   []AuditSchedule `json:"schedules"`
	CreatedAt   string          `json:"created_at"`
}

type Feedback struct {
	ID          int64      `json:"id"`
	StudentID   string     `json:"student_id"`
	StudentName string     `json:"student_name"`
	Type        string     `json:"type"`
	Content     string     `json:"content"`
	Status      string     `json:"status"`
	Reply       string     `json:"reply"`
	RepliedAt   *time.Time `json:"-"`
	ReplyRead   bool       `json:"reply_read"`
	CreatedAt   *time.Time `json:"-"`
}

func (f Feedback) JSON() map[string]any {
	format := func(value *time.Time) string {
		if value == nil {
			return ""
		}
		return value.Format("2006-01-02 15:04")
	}
	return map[string]any{
		"id": f.ID, "student_id": f.StudentID, "student_name": f.StudentName,
		"type": f.Type, "content": f.Content, "status": f.Status,
		"reply": f.Reply, "replied_at": format(f.RepliedAt),
		"reply_read": f.ReplyRead, "created_at": format(f.CreatedAt),
	}
}

type Cookie struct {
	Name   string `json:"name"`
	Value  string `json:"value"`
	Domain string `json:"domain"`
	Path   string `json:"path"`
}

type PersistentSession struct {
	Timestamp   int64    `json:"ts"`
	Cookies     []Cookie `json:"cookies"`
	AccountType string   `json:"account_type"`
}
