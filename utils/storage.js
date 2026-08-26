/**
 * 本地存储封装 — 用户信息、数据缓存
 */

const STORAGE_KEYS = {
  STUDENT_ID: 'student_id',
  STUDENT_NAME: 'student_name',
  SEMESTER: 'semester',
  TOKEN: 'token',           // 后端登录 token（多用户会话标识）
  SAVED_PASSWORD: 'saved_password',   // 记住的密码（仅本机，退出登录时清除）
  COURSES: 'cached_courses',
  EXAMS: 'cached_exams',
  EVALUATIONS: 'cached_evaluations',
  GRADES: 'cached_grades',
  CET_SCORES: 'cached_cet_scores',
  CACHE_TIME: 'cache_timestamps'
}

/** 获取存储值 */
function get(key, defaultValue = null) {
  try {
    const v = wx.getStorageSync(key)
    return v !== '' && v !== undefined ? v : defaultValue
  } catch (e) {
    return defaultValue
  }
}

/** 设置存储值 */
function set(key, value) {
  try {
    wx.setStorageSync(key, value)
  } catch (e) {
    console.error('存储写入失败:', key, e)
  }
}

/** 删除存储值 */
function remove(key) {
  try {
    wx.removeStorageSync(key)
  } catch (e) {
    console.error('存储删除失败:', key, e)
  }
}

// ============================================================
// 用户信息
// ============================================================

function getStudentId() { return get(STORAGE_KEYS.STUDENT_ID, '') }
function setStudentId(id) { set(STORAGE_KEYS.STUDENT_ID, id) }
function getStudentName() { return get(STORAGE_KEYS.STUDENT_NAME, '') }
function setStudentName(n) { set(STORAGE_KEYS.STUDENT_NAME, n) }
function getSemester() { return get(STORAGE_KEYS.SEMESTER, '') }
function setSemester(s) { set(STORAGE_KEYS.SEMESTER, s) }
function isLoggedIn() { return !!getStudentId() }

// ============================================================
// 数据缓存
// ============================================================

function getCached(key) {
  try {
    const raw = get(key, '')
    return raw ? JSON.parse(raw) : null
  } catch (e) {
    return null
  }
}

function setCached(key, data) {
  set(key, JSON.stringify(data))
  // 记录缓存时间
  const timestamps = get(STORAGE_KEYS.CACHE_TIME, {})
  timestamps[key] = Date.now()
  set(STORAGE_KEYS.CACHE_TIME, timestamps)
}

function getCacheAge(key) {
  const timestamps = get(STORAGE_KEYS.CACHE_TIME, {})
  const ts = timestamps[key] || 0
  return Date.now() - ts
}

/** 带过期时间的缓存读取 */
function getCachedIfFresh(key, ttl) {
  if (getCacheAge(key) < ttl) {
    return getCached(key)
  }
  return null
}

// ============================================================
// 清除所有数据
// ============================================================

function clearAll() {
  Object.values(STORAGE_KEYS).forEach(k => remove(k))
}

module.exports = {
  get, set, remove,
  isLoggedIn,
  getStudentId, setStudentId, getStudentName, setStudentName,
  getSemester, setSemester,
  getCached, setCached, getCachedIfFresh, getCacheAge,
  clearAll
}
