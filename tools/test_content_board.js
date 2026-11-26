const assert = require('assert')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
// 版本断言以代码内置更新记录的最新一条为准，避免每次发版后测试硬编码过期
const { RELEASES } = require(path.join(ROOT, 'utils', 'changelog'))
const LATEST_VERSION = RELEASES[0].version
const apiPath = require.resolve(path.join(ROOT, 'utils', 'api'))
const storagePath = require.resolve(path.join(ROOT, 'utils', 'storage'))
const contentPath = require.resolve(path.join(ROOT, 'utils', 'content-board'))

function loadWith(response, cachedBoard, announcementResponse) {
  delete require.cache[contentPath]
  require.cache[apiPath] = {
    id: apiPath,
    filename: apiPath,
    loaded: true,
    exports: {
      getContentBoard: () => Promise.resolve(response),
      getAnnouncement: () => Promise.resolve(announcementResponse)
    }
  }
  require.cache[storagePath] = {
    id: storagePath,
    filename: storagePath,
    loaded: true,
    exports: {
      getCached: () => cachedBoard,
      get: () => '',
      set: () => {},
      setCached: () => {}
    }
  }
  return require(contentPath)
}

;(async () => {
  const failed = loadWith({ success: false, message: '网络请求失败' }, null)
  await assert.rejects(failed.load(true), /网络请求失败/)

  const legacy = loadWith(
    { success: false, message: '404 page not found' },
    null,
    {
      success: true,
      enabled: true,
      text: '旧接口公告仍可展示',
      updated: '2026-10-20 09:30:00'
    }
  )
  const legacyResult = await legacy.load(true)
  assert.strictEqual(legacyResult.announcements.length, 1)
  assert.strictEqual(legacyResult.announcements[0].body, '旧接口公告仍可展示')
  assert.strictEqual(legacyResult.announcements[0].priority, 'important')
  assert.strictEqual(legacyResult.announcements[0].published_at, '2026-10-20')
  assert(legacyResult.changelog.length >= 3)
  assert.strictEqual(legacyResult.changelog[0].version, LATEST_VERSION)
  assert.strictEqual(legacyResult.competitions.length, 0)

  const board = {
    updated: '2026-10-19 16:00:00',
    announcements: [
      { id: 'cached', title: '缓存公告', body: '正文' },
      { id: 'expired', title: '过期公告', body: '不应展示', expires_at: '2000-01-01' }
    ],
    changelog: [],
    community: { name: '', qq: '', note: '' }
  }
  const fallback = loadWith({ success: false }, board)
  const fallbackResult = await fallback.load(true)
  assert.strictEqual(fallbackResult.announcements.length, 1)
  assert.strictEqual(fallbackResult.announcements[0].type_label, '公告')
  assert.strictEqual(fallbackResult.announcements[0].priority_label, '')

  const fetched = loadWith({
    success: true,
    board: Object.assign({}, board, {
      updated: '2026-10-19 16:10:00',
      changelog: [{ version: 'server-value-must-be-ignored', title: '后端值', changes: [] }]
    })
  }, null)
  const fetchedResult = await fetched.load(true)
  assert.strictEqual(fetchedResult.updated, '2026-10-19 16:10:00')
  assert.strictEqual(fetchedResult.changelog[0].version, LATEST_VERSION)
  assert.ok(['新增', '优化', '修复', '移除'].includes(fetchedResult.changelog[0].changes[0].type_label), '更新记录变更类型标签应合法')
  assert.ok(fetchedResult.changelog[0].changes[0].text, '更新记录变更文案不应为空')

  const competitionBoard = {
    updated: '2026-10-21 10:00:00',
    announcements: [],
    competitions: [
      {
        id: 'old', title: '旧竞赛', summary: '旧摘要', published_at: '2026-10-01',
        deadline: '', source_url: 'https://xspace.njust.edu.cn/old', enabled: true
      },
      {
        id: 'new', title: '新竞赛', body: '新正文', published_at: '2026-10-20',
        deadline: '2026-11-01', source_url: 'https://njust.edu.cn/new', enabled: true
      },
      {
        id: 'hidden', title: '隐藏竞赛', summary: '不应展示', published_at: '2026-10-30',
        deadline: '', source_url: 'https://njust.edu.cn/hidden', enabled: false
      }
    ],
    changelog: [],
    community: { name: '', qq: '', note: '' }
  }
  const competitionResult = await loadWith({ success: true, board: competitionBoard }, null).load(true)
  assert.strictEqual(competitionResult.competitions.length, 2, '只展示启用的竞赛')
  assert.strictEqual(competitionResult.competitions[0].id, 'new', '竞赛按发布日期倒序')
  assert.strictEqual(competitionResult.competitions[1].id, 'old')
  assert.strictEqual(competitionResult.competitions[0].display_summary, '新正文', '没有摘要时回退正文')
  assert.strictEqual(competitionResult.competitions[0].deadline, '2026-11-01')
  assert.strictEqual(competitionResult.competitions[1].deadline, '')
  assert.strictEqual(competitionResult.competitions[0].source_url, 'https://njust.edu.cn/new')

  // 旧版 board JSON 没有 competitions 时必须兼容为空数组。
  const legacyBoardResult = await loadWith({ success: true, board }, null).load(true)
  assert.deepStrictEqual(legacyBoardResult.competitions, [])
  console.log('Content board fallback test passed [OK]')
})().catch(error => {
  console.error(error)
  process.exit(1)
})
