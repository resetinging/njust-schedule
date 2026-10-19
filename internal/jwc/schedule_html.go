package jwc

import (
	"fmt"
	stdhtml "html"
	"strconv"
	"strings"

	"github.com/PuerkitoBio/goquery"
	"github.com/resetinging/njust-schedule/internal/store"
)

var weekdayRunes = []rune{'一', '二', '三', '四', '五', '六', '日'}

var bigPeriodRanges = []struct {
	label string
	start int
	end   int
}{
	{"第一", 1, 3},
	{"第二", 4, 5},
	{"第三", 6, 7},
	{"第四", 8, 10},
	{"第五", 11, 13},
	{"中午", 14, 14},
}

type scheduleSlot struct {
	start      int
	end        int
	credits    string
	courseType string
}

func parseScheduleDocument(doc *goquery.Document) []store.Course {
	grid := doc.Find("table#kbtable").First()
	dataTable := doc.Find("table#dataList").First()
	if grid.Length() > 0 && dataTable.Length() > 0 {
		if courses := parseMergedSchedule(grid, dataTable); len(courses) > 0 {
			return courses
		}
	}
	if dataTable.Length() > 0 {
		if courses := parseDataListSchedule(dataTable); len(courses) > 0 {
			return courses
		}
	}
	if grid.Length() > 0 {
		return parseScheduleGrid(grid, nil)
	}
	return nil
}

func parseMergedSchedule(grid, dataTable *goquery.Selection) []store.Course {
	periodInfo := map[string][]scheduleSlot{}
	dataTable.Find("tr").Each(func(index int, row *goquery.Selection) {
		if index == 0 {
			return
		}
		cells := row.Find("td")
		if cells.Length() < 9 {
			return
		}
		name := strings.TrimSpace(cells.Eq(3).Text())
		if name == "" {
			return
		}
		credits := strings.TrimSpace(cells.Eq(6).Text())
		courseType := strings.TrimSpace(cells.Eq(8).Text())
		timeHTML, _ := cells.Eq(5).Html()
		for _, match := range timePattern.FindAllStringSubmatch(timeHTML, -1) {
			day := dayNumber[match[1]]
			start, _ := strconv.Atoi(match[2])
			end, _ := strconv.Atoi(match[3])
			key := scheduleKey(name, day)
			periodInfo[key] = append(periodInfo[key], scheduleSlot{
				start: start, end: end, credits: credits, courseType: courseType,
			})
		}
	})
	return parseScheduleGrid(grid, periodInfo)
}

func parseScheduleGrid(grid *goquery.Selection, periodInfo map[string][]scheduleSlot) []store.Course {
	rows := grid.Find("tr")
	if rows.Length() < 2 {
		return nil
	}
	columns := map[int]int{}
	rows.First().Find("td,th").Each(func(index int, cell *goquery.Selection) {
		text := strings.TrimSpace(cell.Text())
		day := 0
		for offset, weekday := range weekdayRunes {
			if strings.ContainsRune(text, weekday) {
				day = offset + 1
				break
			}
		}
		if day == 0 {
			return
		}
		colspan := 1
		if raw, ok := cell.Attr("colspan"); ok {
			if parsed, err := strconv.Atoi(strings.TrimSpace(raw)); err == nil && parsed > 0 {
				colspan = parsed
			}
		}
		for offset := 0; offset < colspan; offset++ {
			columns[index+offset] = day
		}
	})

	var courses []store.Course
	rows.Slice(1, rows.Length()).Each(func(_ int, row *goquery.Selection) {
		cells := row.Find("td,th")
		if cells.Length() < 2 {
			return
		}
		label := strings.TrimSpace(cells.Eq(0).Text())
		rough := [2]int{}
		found := false
		for _, period := range bigPeriodRanges {
			if strings.Contains(label, period.label) {
				rough = [2]int{period.start, period.end}
				found = true
				break
			}
		}
		if !found {
			return
		}
		cells.Each(func(index int, cell *goquery.Selection) {
			if index == 0 {
				return
			}
			day := columns[index]
			if day == 0 {
				return
			}
			cell.Find("div.kbcontent").Each(func(_ int, detail *goquery.Selection) {
				raw, _ := detail.Html()
				for _, fragment := range hyphenPattern.Split(raw, -1) {
					if strings.TrimSpace(fragment) == "" || strings.Contains(fragment, "&nbsp;") {
						continue
					}
					entry, err := goquery.NewDocumentFromReader(strings.NewReader(fragment))
					if err != nil {
						continue
					}
					lines := fragmentLines(fragment)
					if len(lines) < 2 {
						continue
					}
					name := strings.TrimSpace(lines[0])
					if name == "" || name == "\u00a0" {
						continue
					}
					teacher, weeks, classroom := "", "", ""
					entry.Find("font").Each(func(_ int, font *goquery.Selection) {
						title, _ := font.Attr("title")
						value := strings.TrimSpace(font.Text())
						switch {
						case strings.Contains(title, "老师") || strings.Contains(title, "教师"):
							teacher = value
						case strings.Contains(title, "周次"):
							weeks = cleanWeeks(value)
						case strings.Contains(title, "教室"):
							classroom = value
						case strings.Contains(title, "分组名") && teacher == "":
							teacher = value
						}
					})
					if periodInfo == nil {
						if teacher == "" && len(lines) > 1 {
							teacher = lines[1]
						}
						if weeks == "" {
							for _, line := range lines[1:] {
								if looksLikeScheduleWeek(line) {
									weeks = cleanWeeks(line)
									break
								}
							}
						}
						if classroom == "" && len(lines) > 1 {
							classroom = lines[len(lines)-1]
						}
					}
					start, end := rough[0], rough[1]
					slot := pickPeriodSlot(periodInfo[scheduleKey(name, day)], rough)
					if slot != nil {
						start, end = slot.start, slot.end
					}
					courses = append(courses, store.Course{
						Name: name, Teacher: teacher, Classroom: classroom,
						Day: day, Start: start, End: end, Weeks: weeks,
						WeekType: 0, Credits: slotValue(slot, true), CourseType: slotValue(slot, false),
						RawData: "{}",
					})
				}
			})
		})
	})
	return courses
}

func parseDataListSchedule(table *goquery.Selection) []store.Course {
	var courses []store.Course
	table.Find("tr").Each(func(index int, row *goquery.Selection) {
		if index == 0 {
			return
		}
		cells := row.Find("td")
		if cells.Length() < 9 {
			return
		}
		texts := selectionTexts(cells)
		name := at(texts, 3)
		if name == "" {
			return
		}
		teacher := at(texts, 4)
		credits := at(texts, 6)
		courseType := at(texts, 8)
		timeHTML, _ := cells.Eq(5).Html()
		locationHTML, _ := cells.Eq(7).Html()
		locations := splitHTMLLines(locationHTML)
		for index, match := range timePattern.FindAllStringSubmatch(timeHTML, -1) {
			start, _ := strconv.Atoi(match[2])
			end, _ := strconv.Atoi(match[3])
			room := firstStringAt(locations, index)
			courses = append(courses, store.Course{
				Name: name, Teacher: teacher, Classroom: room,
				Day: dayNumber[match[1]], Start: start, End: end,
				Credits: credits, CourseType: courseType, RawData: "{}",
			})
		}
	})
	return courses
}

func fragmentLines(fragment string) []string {
	text := brPattern.ReplaceAllString(fragment, "\n")
	text = tagPattern.ReplaceAllString(text, "\n")
	text = stdhtml.UnescapeString(text)
	text = strings.ReplaceAll(text, "\u00a0", " ")
	parts := strings.Split(text, "\n")
	lines := make([]string, 0, len(parts))
	for _, part := range parts {
		if value := strings.Join(strings.Fields(part), " "); value != "" {
			lines = append(lines, value)
		}
	}
	return lines
}

func scheduleKey(name string, day int) string {
	return fmt.Sprintf("%s\x00%d", name, day)
}

func cleanWeeks(value string) string {
	value = strings.TrimSpace(value)
	value = strings.TrimSuffix(value, "(周)")
	value = strings.TrimSuffix(value, "（周）")
	return strings.TrimSpace(value)
}

func looksLikeScheduleWeek(value string) bool {
	value = strings.TrimSpace(value)
	if value == "" {
		return false
	}
	for _, r := range value {
		if r >= '0' && r <= '9' {
			return strings.Contains(value, "周") || strings.ContainsAny(value, "-~至,")
		}
	}
	return false
}

func pickPeriodSlot(slots []scheduleSlot, rough [2]int) *scheduleSlot {
	if len(slots) == 0 {
		return nil
	}
	for index := range slots {
		if slots[index].start >= rough[0] && slots[index].start <= rough[1] {
			return &slots[index]
		}
	}
	best := 0
	bestOverlap := -1
	for index := range slots {
		overlap := min(slots[index].end, rough[1]) - max(slots[index].start, rough[0])
		if overlap > bestOverlap {
			best = index
			bestOverlap = overlap
		}
	}
	return &slots[best]
}

func slotValue(slot *scheduleSlot, credits bool) string {
	if slot == nil {
		return ""
	}
	if credits {
		return slot.credits
	}
	return slot.courseType
}

func firstStringAt(values []string, index int) string {
	if index < len(values) {
		return values[index]
	}
	if len(values) > 0 {
		return values[0]
	}
	return ""
}
