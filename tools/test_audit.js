/**
 * 蹭课查询页逻辑测试 — 在 Node 中模拟小程序运行时。
 *
 * 运行: node tools/test_audit.js
 */
const assert = require('assert')
const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(process.argv[2] || path.join(__dirname, '..'))
const store = new Map([['semester', '2026-2027-1']])
const toasts = []

global.wx = {
  getStorageSync(key) {
    return store.has(key) ? store.get(key) : ''
  },
  setStorageSync(key, value) {
    store.set(key, value)
  },
  removeStorageSync(key) {
    store.delete(key)
  },
  getStorageInfoSync() {
    return { keys: Array.from(store.keys()) }
  },
  showToast(options) {
    toasts.push(options)
  }
}

let componentConfig = null
global.Component = config => {
  componentConfig = config
}

let pass = 0
const failures = []
async function check(name, fn) {
  try {
    await fn()
    pass++
    console.log('  ✓ ' + name)
  } catch (error) {
    failures.push(name)
    console.log('  ✗ ' + name + '  → ' + error.message)
  }
}

function makeInstance() {
  const instance = {
    data: JSON.parse(JSON.stringify(componentConfig.data)),
    setData(patch, callback) {
      Object.assign(this.data, patch)
      if (callback) callback()
    },
    triggerEvent() {}
  }
  Object.keys(componentConfig.methods).forEach(name => {
    instance[name] = componentConfig.methods[name]
  })
  return instance
}

;(async () => {
  require(path.join(ROOT, 'components', 'audit-course-view', 'index.js'))
  const api = require(path.join(ROOT, 'utils', 'api'))
  const auditCourseUtil = require(path.join(ROOT, 'utils', 'audit-course'))
  const calls = []
  const optionCalls = []
  let optionVersion = 101
  api.searchAuditCourses = params => {
    calls.push(params)
    return Promise.resolve({
      success: true,
      courses: [{
        name: '数据结构',
        class_info: '924101960123',
        teacher: '张老师',
        classroom: 'Ⅳ-A101',
        schedules: [{
          day: 1,
          start: 3,
          end: 5,
          weeks: '1-16',
          teacher: '张老师',
          classroom: 'Ⅳ-A101'
        }],
        schedule_count: 1
      }],
      total: 1,
      page: params.page,
      has_more: false,
      updated_at: 1780000000
    })
  }
  api.listAuditOptions = params => {
    optionCalls.push(params)
    if (params.field === 'all') {
      const part = Number(params.part || 0)
      return Promise.resolve({
        success: true,
        field: 'all',
        catalog_version: optionVersion,
        names: ['数据结构', '高等数学'],
        teachers: ['张老师', '李老师'],
        classrooms: ['Ⅳ-A101', 'Ⅳ-A102', 'Ⅳ-B202'],
        part,
        parts: 2,
        relations_total: 3,
        relations: part === 0
          ? [[0, [0], [0], 1, 1, 3], [0, [1], [1], 3, 4, 5]]
          : [[1, [1], [2], 5, 6, 7]]
      })
    }
    if (params.field === 'version') {
      return Promise.resolve({
        success: true,
        field: 'version',
        catalog_version: optionVersion,
        count: 2
      })
    }
    return Promise.resolve({
      success: true,
      field: params.field,
      options: params.field === 'name'
        ? ['数据结构', '高等数学']
        : ['张老师']
    })
  }
  api.listAuditFavorites = () => Promise.resolve({
    success: true,
    favorites: []
  })
  let favoriteSeq = 0
  api.saveAuditFavorite = params => {
    favoriteSeq += 1
    return Promise.resolve({
      success: true,
      favorite: Object.assign({
        id: favoriteSeq,
        favorite_key: 'saved-' + favoriteSeq,
        semester: params.semester
      }, params.course)
    })
  }
  api.deleteAuditFavorite = () => Promise.resolve({ success: true })

  const instance = makeInstance()
  await check('节次选项覆盖不限和第1-13节', () => {
    assert.strictEqual(instance.data.periodOptions.length, 14)
    assert.strictEqual(instance.data.periodOptions[0], '不限')
    assert.strictEqual(instance.data.periodOptions[13], '第13节')
  })
  await check('冲突判断按星期、节次和周次共同计算', () => {
    const audit = {
      name: '数据结构',
      schedules: [{
        day: 1, start: 1, end: 3, weeks: '1-16'
      }]
    }
    const own = [{
      name: '高等数学',
      day: 1,
      start: 2,
      end: 4,
      weeks: '2-8'
    }]
    const hit = auditCourseUtil.conflictForCourse(audit, own)
    assert.strictEqual(hit.hasConflict, true)
    const miss = auditCourseUtil.conflictForCourse(audit, [{
      name: '大学物理',
      day: 2,
      start: 2,
      end: 4,
      weeks: '2-8'
    }])
    assert.strictEqual(miss.hasConflict, false)
  })
  await check('多时段课程只标记对应的冲突时段', () => {
    const marked = auditCourseUtil.markScheduleConflicts({
      name: 'Python程序设计',
      schedules: [
        { day: 1, start: 4, end: 5, weeks: '4-6,8-10' },
        { day: 3, start: 1, end: 3, weeks: '4-6,8-10' }
      ]
    }, [{
      name: '体育（Ⅴ）',
      day: 1,
      start: 4,
      end: 5,
      weeks: '4-6,8-19'
    }])
    assert.strictEqual(marked.schedules[0]._hasConflict, true)
    assert.strictEqual(marked.schedules[1]._hasConflict, false)
    const blocks = auditCourseUtil.flattenFavorite(marked)
    assert.strictEqual(blocks[0]._hasConflict, true)
    assert.strictEqual(blocks[1]._hasConflict, false)
  })
  await check('收藏课程可展开成课表课程块', () => {
    const rows = auditCourseUtil.flattenFavorite({
      id: 7,
      name: '数据结构',
      class_info: '924101960123',
      teacher: '张老师',
      classroom: 'Ⅳ-A101',
      schedules: [{
        day: 1,
        start: 1,
        end: 3,
        weeks: '1-16',
        teacher: '张老师',
        classroom: 'Ⅳ-A101'
      }]
    })
    assert.strictEqual(rows.length, 1)
    assert.strictEqual(rows[0]._audit, true)
    assert.strictEqual(rows[0]._favoriteId, 7)
  })
  await check('收藏操作会更新蹭课课程状态', async () => {
    store.set('student_id', '924101960123')
    instance.data.ownCoursesLoaded = true
    instance.data.ownCourses = []
    instance._favoriteMap = {}
    instance.setData({
      favorites: [],
      favoriteCount: 0,
      courses: [instance._decorate({
        name: '数据结构',
        class_info: '924101960123',
        teacher: '张老师',
        classroom: 'Ⅳ-A101',
        schedules: [{
          day: 1,
          start: 1,
          end: 3,
          weeks: '1-16',
          teacher: '张老师',
          classroom: 'Ⅳ-A101'
        }]
      })]
    })
    const saved = await instance._toggleFavorite(instance.data.courses[0])
    assert.strictEqual(saved, true)
    assert.strictEqual(instance.data.favoriteCount, 1)
    assert.strictEqual(instance.data.courses[0]._isFavorite, true)
    const removed = await instance._toggleFavorite(instance.data.courses[0])
    assert.strictEqual(removed, true)
    assert.strictEqual(instance.data.favoriteCount, 0)
    assert.strictEqual(instance.data.courses[0]._isFavorite, false)
  })
  await check('收藏视图支持查看和本地筛选', () => {
    instance.onClear()
    instance._favoriteMap = {}
    instance.setData({
      ownCoursesLoaded: true,
      ownCourses: []
    })
    instance._applyFavorites([
      {
        id: 11,
        name: '数据结构',
        class_info: '924101960123',
        teacher: '张老师',
        classroom: 'Ⅳ-A101',
        schedules: [{
          day: 1, start: 1, end: 3, weeks: '1-16'
        }]
      },
      {
        id: 12,
        name: '高等数学',
        class_info: '924101960123',
        teacher: '李老师',
        classroom: 'Ⅰ-201',
        schedules: [{
          day: 2, start: 3, end: 5, weeks: '1-16'
        }]
      }
    ])
    instance.openFavoritesView()
    assert.strictEqual(instance.data.showFavoritesOnly, true)
    assert.strictEqual(instance.data.courses.length, 2)
    instance.setData({ courseName: '数据结构' })
    instance._renderFavoriteCourses()
    assert.strictEqual(instance.data.courses.length, 1)
    assert.strictEqual(instance.data.courses[0].name, '数据结构')
    instance.toggleFavorites()
    assert.strictEqual(instance.data.showFavoritesOnly, false)
  })
  await check('课表页提供收藏查询入口', () => {
    const scheduleWxml = fs.readFileSync(
      path.join(ROOT, 'components', 'schedule-view', 'index.wxml'), 'utf8')
    const mainWxml = fs.readFileSync(
      path.join(ROOT, 'pages', 'main', 'main.wxml'), 'utf8')
    assert.ok(scheduleWxml.includes('bindtap="onOpenAuditFavorites"'))
    assert.ok(scheduleWxml.includes('查询蹭课收藏'))
    assert.ok(mainWxml.includes('bind:auditfavorites="onOpenAuditFavorites"'))
    assert.strictEqual(typeof instance.openFavoritesView, 'function')
  })
  await check('开始节次超过结束节次时自动校准', () => {
    instance.setData({ startPeriodIndex: 5, endPeriodIndex: 3 })
    instance.onStartPeriodChange({ detail: { value: 5 } })
    assert.strictEqual(instance.data.endPeriodIndex, 5)
  })
  await check('结束节次早于开始节次时自动校准', () => {
    instance.setData({ startPeriodIndex: 6, endPeriodIndex: 8 })
    instance.onEndPeriodChange({ detail: { value: 4 } })
    assert.strictEqual(instance.data.startPeriodIndex, 4)
  })
  await check('空条件不发请求并提示', () => {
    instance.onClear()
    instance.onSearch()
    assert.strictEqual(calls.length, 0)
    assert.strictEqual(toasts[toasts.length - 1].title, '请至少填写一个查询条件')
  })
  await check('首屏只请求完整查询列表', async () => {
    await instance._loadQueryOptions()
    assert.strictEqual(optionCalls.length, 2)
    assert.deepStrictEqual(optionCalls.map(item => item.part), [0, 1])
    assert.ok(optionCalls.every(item => item.field === 'all'))
    assert.strictEqual(instance._relations.length, 3)
    assert.deepStrictEqual(instance._queryOptions.teachers, ['张老师', '李老师'])
  })
  await check('再次进入仅检查版本，版本不变不拉表单', async () => {
    const allBefore = optionCalls.filter(item => item.field === 'all').length
    await instance._loadQueryOptions()
    assert.strictEqual(optionCalls[optionCalls.length - 1].field, 'version')
    assert.strictEqual(
      optionCalls.filter(item => item.field === 'all').length, allBefore)
  })
  await check('目录版本变化时才重新获取完整表单', async () => {
    optionVersion = 102
    await instance._loadQueryOptions()
    assert.strictEqual(optionCalls[optionCalls.length - 1].field, 'all')
  })
  await check('聚焦和输入只在本地过滤查询列表', async () => {
    const requestCount = optionCalls.length
    instance.onClear()
    instance.setData({ courseName: '数' })
    instance.onFilterFocus({
      currentTarget: { dataset: { field: 'courseName' } }
    })
    await new Promise(resolve => setTimeout(resolve, 10))
    assert.strictEqual(optionCalls.length, requestCount)
    assert.deepStrictEqual(instance.data.suggestOptions, ['数据结构', '高等数学'])
    assert.strictEqual(instance.data.suggestHeight, 136)
  })
  await check('长候选下拉栏使用固定最大滚动高度', () => {
    const originalOptionsForField = instance._optionsForField
    instance._queryOptionsReady = true
    instance._optionsForField = () =>
      Array.from({ length: 20 }, (_, index) => `课程${index}`)
    instance._applyLocalSuggestions('courseName', '')
    assert.strictEqual(instance.data.suggestOptions.length, 20)
    assert.strictEqual(instance.data.suggestHeight, 360)
    instance._optionsForField = originalOptionsForField
  })
  await check('候选下拉栏每次加载 50 项并支持继续加载', () => {
    const originalOptionsForField = instance._optionsForField
    instance._queryOptionsReady = true
    instance._optionsForField = () =>
      Array.from({ length: 125 }, (_, index) => `课程${index}`)
    instance._applyLocalSuggestions('courseName', '')
    assert.strictEqual(instance.data.suggestOptions.length, 50)
    assert.strictEqual(instance.data.suggestVisibleCount, 50)
    instance.onSuggestScrollToLower()
    assert.strictEqual(instance.data.suggestOptions.length, 100)
    assert.strictEqual(instance.data.suggestVisibleCount, 100)
    instance.onSuggestScrollToLower()
    assert.strictEqual(instance.data.suggestOptions.length, 125)
    assert.strictEqual(instance.data.suggestVisibleCount, 125)
    instance._optionsForField = originalOptionsForField
  })
  await check('再次点击已展开的搜索栏会收回下拉栏', () => {
    instance.onClear()
    instance._queryOptionsReady = true
    instance.onFilterTouchStart({
      currentTarget: { dataset: { field: 'courseName' } }
    })
    instance.onFilterFocus({
      currentTarget: { dataset: { field: 'courseName' } }
    })
    assert.strictEqual(instance.data.suggestField, 'courseName')
    instance.onFilterTap({
      currentTarget: { dataset: { field: 'courseName' } }
    })
    assert.strictEqual(instance.data.suggestField, 'courseName')
    instance.onFilterTouchStart({
      currentTarget: { dataset: { field: 'courseName' } }
    })
    instance.onFilterFocus({
      currentTarget: { dataset: { field: 'courseName' } }
    })
    instance.onFilterTap({
      currentTarget: { dataset: { field: 'courseName' } }
    })
    assert.strictEqual(instance.data.suggestField, '')
    instance.onFilterFocus({
      currentTarget: { dataset: { field: 'courseName' } }
    })
    assert.strictEqual(instance.data.suggestField, '')
    instance.onFilterTouchStart({
      currentTarget: { dataset: { field: 'courseName' } }
    })
    instance.onFilterTap({
      currentTarget: { dataset: { field: 'courseName' } }
    })
    assert.strictEqual(instance.data.suggestField, 'courseName')
  })
  const values = items => (items || []).map(item => item.value)

  await check('扩展查询支持多选和三级联动', () => {
    instance.onClear()
    instance.setData({ suggestField: 'courseName' })
    instance.openQueryExplorer()
    assert.strictEqual(instance.data.showQueryExplorer, true)
    assert.strictEqual(instance.data.explorerAllTotal, 2)
    const initialNames = values(instance.data.explorerItems)
    assert.strictEqual(initialNames.length, 2)
    assert.ok(initialNames.includes('数据结构'))
    assert.ok(initialNames.includes('高等数学'))
    instance.onExplorerSelect({
      currentTarget: { dataset: { value: '数据结构' } }
    })
    assert.strictEqual(instance.data.courseName, '数据结构')
    assert.deepStrictEqual(instance.data.selectedNames, ['数据结构'])
    assert.strictEqual(instance.data.showQueryExplorer, true)
    instance.onExplorerTab({
      currentTarget: { dataset: { tab: 'teachers' } }
    })
    assert.strictEqual(instance.data.explorerAllTotal, 2)
    instance.onExplorerInput({ detail: { value: '李' } })
    assert.deepStrictEqual(values(instance.data.explorerItems), ['李老师'])
    instance.onExplorerSelect({
      currentTarget: { dataset: { value: '李老师' } }
    })
    assert.strictEqual(instance.data.teacher, '李老师')
    assert.deepStrictEqual(instance.data.selectedTeachers, ['李老师'])
    instance.onExplorerTab({
      currentTarget: { dataset: { tab: 'names' } }
    })
    const linkedNames = values(instance.data.explorerItems)
    assert.ok(linkedNames.includes('数据结构'))
    assert.ok(linkedNames.includes('高等数学'))
    instance.onExplorerTab({
      currentTarget: { dataset: { tab: 'classrooms' } }
    })
    assert.deepStrictEqual(values(instance.data.explorerItems), ['Ⅳ-A102'])
  })
  await check('时间条件单向约束课程/教师/地点', () => {
    instance.onClear()
    instance.setData({
      weekdayIndex: 1,
      startPeriodIndex: 1,
      endPeriodIndex: 3,
      suggestField: 'courseName'
    })
    instance.openQueryExplorer()
    assert.deepStrictEqual(values(instance.data.explorerItems), ['数据结构'])
    instance.onExplorerSelect({
      currentTarget: { dataset: { value: '数据结构' } }
    })
    assert.deepStrictEqual(instance.data.selectedNames, ['数据结构'])
    assert.strictEqual(instance.data.weekdayIndex, 1)
    assert.strictEqual(instance.data.startPeriodIndex, 1)
    assert.strictEqual(instance.data.endPeriodIndex, 3)
    instance.onExplorerTab({
      currentTarget: { dataset: { tab: 'teachers' } }
    })
    assert.deepStrictEqual(values(instance.data.explorerItems), ['张老师'])
    instance.onExplorerTab({
      currentTarget: { dataset: { tab: 'classrooms' } }
    })
    assert.deepStrictEqual(values(instance.data.explorerItems), ['Ⅳ-A101'])
  })
  await check('同维度多选并按数组提交查询', async () => {
    instance.onClear()
    instance.setData({ suggestField: 'courseName' })
    instance.openQueryExplorer()
    instance.onExplorerSelect({
      currentTarget: { dataset: { value: '数据结构' } }
    })
    instance.onExplorerSelect({
      currentTarget: { dataset: { value: '高等数学' } }
    })
    assert.deepStrictEqual(instance.data.selectedNames, ['数据结构', '高等数学'])
    await instance._query(1)
    const params = calls[calls.length - 1]
    assert.strictEqual(params.names,
      JSON.stringify(['数据结构', '高等数学']))
    assert.strictEqual(params.name_exact, 1)
    assert.strictEqual(params.name, undefined)
  })
  await check('单值精确选择同时兼容旧版单值参数', async () => {
    instance.onClear()
    instance._pickedFields = {}
    instance.setData({
      courseName: '数据结构',
      selectedNames: ['数据结构']
    })
    await instance._query(1)
    const params = calls[calls.length - 1]
    assert.strictEqual(params.names, JSON.stringify(['数据结构']))
    assert.strictEqual(params.name, '数据结构')
    assert.strictEqual(params.name_exact, 1)
  })
  await check('扩展列表接近底部时提前加载下一批', () => {
    instance.onClear()
    instance.setData({
      explorerTab: 'names',
      explorerVisibleCount: 1,
      explorerKeyword: '',
      courseName: '',
      teacher: '',
      classroom: '',
      weekdayIndex: 0,
      startPeriodIndex: 0,
      endPeriodIndex: 0
    })
    instance._pickedFields = {}
    instance._refreshExplorer()
    assert.strictEqual(instance.data.explorerHasMore, true)
    instance.onExplorerScrollToLower()
    assert.strictEqual(instance.data.explorerVisibleCount, 81)
    assert.strictEqual(instance.data.explorerHasMore, false)
  })
  await check('scroll 事件接近底部也会加载下一批', () => {
    instance.onClear()
    instance.setData({
      explorerTab: 'names',
      explorerVisibleCount: 1,
      explorerKeyword: '',
      courseName: '',
      teacher: '',
      classroom: '',
      weekdayIndex: 0,
      startPeriodIndex: 0,
      endPeriodIndex: 0
    })
    instance._pickedFields = {}
    instance._refreshExplorer()
    assert.strictEqual(instance.data.explorerHasMore, true)
    instance._explorerViewportHeight = 400
    instance.onExplorerScroll({
      detail: { scrollTop: 320, scrollHeight: 800 }
    })
    assert.strictEqual(instance.data.explorerVisibleCount, 81)
    assert.strictEqual(instance.data.explorerHasMore, false)
  })
  await check('滚动区域使用 lower-threshold 提前触发', () => {
    const wxml = fs.readFileSync(
      path.join(ROOT, 'components', 'audit-course-view', 'index.wxml'), 'utf8')
    assert.ok(wxml.includes('lower-threshold="240"'))
    assert.ok(wxml.includes('bindscroll="onExplorerScroll"'))
    assert.ok(wxml.includes('class="explorer-body"'))
    assert.ok(wxml.includes('bindtap="onExplorerLoadMore"'))
    assert.ok(wxml.includes('bindtap="toggleFavorites"'))
    assert.ok(wxml.includes('showFavoritesOnly'))
    assert.ok(wxml.includes('style="height: {{suggestHeight}}rpx;"'))
    assert.strictEqual(
      (wxml.match(/bindtap="onFilterTap"/g) || []).length, 3)
    assert.strictEqual(
      (wxml.match(/bindtouchstart="onFilterTouchStart"/g) || []).length, 3)
    const inputBlocks = wxml.split('<input').slice(1)
      .map(part => part.slice(0, part.indexOf('/>')))
      .filter(block => block.includes('class="filter-input"'))
    assert.strictEqual(inputBlocks.length, 3)
    assert.ok(inputBlocks.every(block => block.includes('bindtap="onFilterTap"')))
    assert.ok(inputBlocks.every(block =>
      block.includes('bindtouchstart="onFilterTouchStart"')))
    assert.ok(!wxml.includes('class="filter-row tap" data-field='))
    assert.ok(wxml.includes('scroll-y="{{suggestField ? false : true}}"'))
    assert.strictEqual(
      (wxml.match(/bindtouchmove="onSuggestTouchMove"/g) || []).length, 3)
    assert.ok(!wxml.includes('catchtouchmove="onSuggestTouchMove"'))
    assert.strictEqual(
      (wxml.match(/bindscrolltolower="onSuggestScrollToLower"/g) || []).length,
      3)
  })
  await check('滑动候选列表时 blur 不关闭面板', async () => {
    instance.setData({ suggestField: 'courseName', suggestOptions: ['数据结构'] })
    instance.onSuggestTouchStart()
    instance.onFilterBlur({
      currentTarget: { dataset: { field: 'courseName' } }
    })
    await new Promise(resolve => setTimeout(resolve, 220))
    assert.strictEqual(instance.data.suggestField, 'courseName')
    instance.onSuggestTouchEnd()
  })
  await check('点击候选项回填并关闭面板', () => {
    instance._pickedFields = {}
    instance.onSelectSuggestion({
      currentTarget: {
        dataset: { field: 'courseName', value: '数据结构' }
      }
    })
    assert.strictEqual(instance.data.courseName, '数据结构')
    assert.strictEqual(instance._pickedFields.courseName, true)
    assert.strictEqual(instance.data.suggestField, '')
    assert.deepStrictEqual(instance.data.suggestOptions, [])
    assert.strictEqual(instance.data.suggestHeight, 0)
  })
  await check('手动输入不会在扩展查询中被误判为精确选择', () => {
    instance.onClear()
    instance._pickedFields = {}
    instance.setData({ courseName: '数', suggestField: 'courseName' })
    instance.openQueryExplorer()
    assert.strictEqual(instance._fieldPicked('courseName'), false)
    instance.closeQueryExplorer()
  })
  await check('手动改课程会清除旧精确选择并发送模糊查询', async () => {
    instance.onClear()
    instance._pickedFields = {}
    instance.setData({
      courseName: 'AI时代的商业洞察与竞争分析',
      selectedNames: ['AI时代的商业洞察与竞争分析'],
      courses: [{ name: 'AI时代的商业洞察与竞争分析' }],
      searched: true
    })
    instance.onFilterInput({
      currentTarget: { dataset: { field: 'courseName' } },
      detail: { value: '2D数字表现技法' }
    })
    assert.deepStrictEqual(instance.data.selectedNames, [])
    assert.strictEqual(instance._fieldPicked('courseName'), false)
    assert.strictEqual(instance.data.searched, false)
    assert.strictEqual(instance.data.courses.length, 0)
    await instance._query(1)
    const params = calls[calls.length - 1]
    assert.strictEqual(params.name, '2D数字表现技法')
    assert.strictEqual(params.name_exact, 0)
    assert.strictEqual(params.names, undefined)
  })
  await check('手动输入查询不会提升为多选数组', async () => {
    instance.onClear()
    instance._pickedFields = {}
    instance.setData({ courseName: '大学物理' })
    instance.onSearch()
    await new Promise(resolve => setTimeout(resolve, 10))
    const params = calls[calls.length - 1]
    assert.deepStrictEqual(instance.data.selectedNames, [])
    assert.strictEqual(params.name, '大学物理')
    assert.strictEqual(params.name_exact, 0)
    assert.strictEqual(params.names, undefined)
  })
  await check('组合条件按字段传给后端', async () => {
    instance.onClear()
    instance._pickedFields = {}
    instance.setData({
      courseName: '数据结构',
      teacher: '张老师',
      classroom: 'A101',
      weekdayIndex: 1,
      startPeriodIndex: 3,
      endPeriodIndex: 5
    })
    await instance._query(1)
    const params = calls[calls.length - 1]
    assert.deepStrictEqual(params, {
      name: '数据结构',
      teacher: '张老师',
      classroom: 'A101',
      weekday: 1,
      jc1: 3,
      jc2: 5,
      name_exact: 0,
      teacher_exact: 0,
      classroom_exact: 0,
      page: 1,
      limit: 20,
      semester: '2026-2027-1'
    })
  })
  await check('精确选择传递 exact 标记', async () => {
    instance._pickedFields = {
      courseName: true,
      teacher: true,
      classroom: true
    }
    await instance._query(1)
    assert.strictEqual(calls[calls.length - 1].name_exact, 1)
    assert.strictEqual(calls[calls.length - 1].teacher_exact, 1)
    assert.strictEqual(calls[calls.length - 1].classroom_exact, 1)
  })
  await check('响应卡片补充星期、节次和钟点', () => {
    const course = instance.data.courses[0]
    assert.strictEqual(course.class_info, '924101960123')
    assert.strictEqual(course.scheduleCount, 1)
    assert.strictEqual(course.schedules[0].dayName, '星期一')
    assert.strictEqual(course.schedules[0].periodText, '第3-5节')
    assert.ok(course.schedules[0].timeText)
    assert.strictEqual(course.daySummary, '星期一')
    assert.ok(course.timeSummary.indexOf('第3-5节') === 0)
  })
  await check('点击聚合课程展开全部拆分时段', () => {
    instance.setData({
      courses: [
        instance._decorate({
          name: '数据结构',
          class_info: '924101960123',
          teacher: '张老师,李老师',
          classroom: 'Ⅳ-A101,Ⅳ-A102',
          schedules: [
            { day: 1, start: 1, end: 3, weeks: '1-16', teacher: '张老师', classroom: 'Ⅳ-A101' },
            { day: 3, start: 4, end: 5, weeks: '1-16', teacher: '李老师', classroom: 'Ⅳ-A102' }
          ]
        })
      ]
    })
    instance.onCourseTap({ currentTarget: { dataset: { index: 0 } } })
    assert.strictEqual(instance.data.showWeekly, true)
    assert.strictEqual(instance.data.weeklyName, '数据结构')
    assert.strictEqual(instance.data.weeklyTeacher, '张老师,李老师')
    assert.strictEqual(instance.data.weeklyCourses.length, 2)
    assert.ok(instance.data.weeklyWeek >= 1)
  })
  await check('周课表支持切换周次和关闭', () => {
    instance.nextWeeklyWeek()
    assert.strictEqual(instance.data.weeklyWeek, instance.data.weeklyWeekIndex + 1)
    instance.onWeeklySheetTap()
    assert.strictEqual(instance.data.showWeekly, true)
    instance.closeWeekly()
    assert.strictEqual(instance.data.showWeekly, false)
  })
  await check('卡片模板展示星期和钟点', () => {
    const wxml = fs.readFileSync(
      path.join(ROOT, 'components', 'audit-course-view', 'index.wxml'), 'utf8')
    assert.ok(wxml.includes('{{item.daySummary'))
    assert.ok(wxml.includes('{{item.timeSummary}}'))
    assert.ok(wxml.includes('wx:if="{{item.teacher}}"'))
    assert.ok(wxml.includes('wx:if="{{weeklyTeacher}}"'))
    assert.ok(!wxml.includes('教师未注明'))
  })
  await check('空状态 emoji 会映射到真实图标', () => {
    const emptyWxml = fs.readFileSync(
      path.join(ROOT, 'components', 'empty-state', 'index.wxml'), 'utf8')
    assert.ok(emptyWxml.includes("name === '🔎'"))
    assert.ok(emptyWxml.includes('esico.resolve(iconName)'))
    const iconWxml = fs.readFileSync(
      path.join(ROOT, 'components', 'icon', 'index.wxml'), 'utf8')
    assert.ok(iconWxml.includes("name === 'list'"))
  })
  await check('返回和关闭图标使用正式资源', () => {
    const iconWxml = fs.readFileSync(
      path.join(ROOT, 'components', 'icon', 'index.wxml'), 'utf8')
    assert.ok(iconWxml.includes("name === 'back') return 'back-slate'"))
    assert.ok(iconWxml.includes("name === 'close'"))
    assert.ok(!iconWxml.includes("name === 'close') return 'plus-indigo'"))
    const backViews = [
      'pages/main/main.wxml',
      'components/freeclass-view/index.wxml',
      'components/gallery-view/index.wxml',
      'components/eval-view/index.wxml'
    ]
    backViews.forEach(rel => {
      assert.ok(fs.readFileSync(path.join(ROOT, rel), 'utf8')
        .includes('name="back"'))
    })
    ;['back-slate.png', 'close-slate.png', 'close-indigo.png'].forEach(name => {
      assert.ok(fs.existsSync(path.join(ROOT, 'static', 'icons', name)), name)
    })
  })
  await check('过期查询响应不会覆盖最新结果', async () => {
    const original = api.searchAuditCourses
    const pending = []
    api.searchAuditCourses = params => new Promise(resolve => {
      pending.push({ params, resolve })
    })
    instance.onClear()
    instance.setData({ courseName: '旧课程' })
    const first = instance._query(1)
    instance.setData({ courseName: '新课程' })
    const second = instance._query(1)
    assert.strictEqual(pending.length, 2)
    pending[1].resolve({
      success: true,
      courses: [{ name: '新课程', schedules: [] }],
      total: 1,
      page: 1,
      has_more: false,
      updated_at: 0
    })
    await second
    pending[0].resolve({
      success: true,
      courses: [{ name: '旧课程', schedules: [] }],
      total: 1,
      page: 1,
      has_more: false,
      updated_at: 0
    })
    await first
    assert.strictEqual(instance.data.courses.length, 1)
    assert.strictEqual(instance.data.courses[0].name, '新课程')
    api.searchAuditCourses = original
  })

  console.log('\n' + '='.repeat(52))
  if (failures.length) {
    console.log(`失败 ${failures.length} / ${pass + failures.length}`)
    process.exitCode = 1
  } else {
    console.log(`通过 ${pass} / ${pass}`)
  }
})()
