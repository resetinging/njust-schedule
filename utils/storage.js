/**
 * 本地存储封装 — token、用户信息、数据缓存
 */

const STORAGE_KEYS = {
  TOKEN: 'auth_token',
  STUDENT_ID: 'student_id',
  STUDENT_NAME: 'student_name',
  SEMESTER: 'semester',
  COURSES: 'cached_courses',
  EXAMS: 'cached_exams',
  EVALUATIONS: 'cached_evaluations',
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
// Token 管理
// ============================================================

function getToken() { return get(STORAGE_KEYS.TOKEN, '') }
function setToken(t) { set(STORAGE_KEYS.TOKEN, t) }
function clearToken() { remove(STORAGE_KEYS.TOKEN) }
function isLoggedIn() { return !!getToken() }

// ============================================================
// 用户信息
// ============================================================

function getStudentId() { return get(STORAGE_KEYS.STUDENT_ID, '') }
function setStudentId(id) { set(STORAGE_KEYS.STUDENT_ID, id) }
function getStudentName() { return get(STORAGE_KEYS.STUDENT_NAME, '') }
function setStudentName(n) { set(STORAGE_KEYS.STUDENT_NAME, n) }
function getSemester() { return get(STORAGE_KEYS.SEMESTER, '') }
function setSemester(s) { set(STORAGE_KEYS.SEMESTER, s) }

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
  getToken, setToken, clearToken, isLoggedIn,
  getStudentId, setStudentId, getStudentName, setStudentName,
  getSemester, setSemester,
  getCached, setCached, getCachedIfFresh, getCacheAge,
  clearAll
}
