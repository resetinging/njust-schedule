/**
 * 订阅消息公共逻辑(设置页 / 考试页共用)
 *
 * 微信规则要点:
 * - 必须由用户点击触发(requestSubscribeMessage 不能在启动时静默调用);
 * - 一次性订阅: 点一次授权 = 可发 1 条; 勾选"总是保持以上选择"后, 后续点击不再弹窗, 可继续累积;
 * - 额度按 "用户 × 模板" 独立累计。
 */
const api = require('./api')
const storage = require('./storage')

// 目前只做考试提醒; 后端新增类型时在这里补一个中文名即可自动显示
const LABELS = { exam: '考试提醒' }

/** 拉取可用类型(含模板 ID 与剩余额度); 未登录/失败返回 { kinds: [], enabled: false } */
async function loadStatus() {
  if (!storage.isLoggedIn()) return { kinds: [], enabled: false }
  try {
    const res = await api.getSubscribeStatus()
    if (!res || !res.success) return { kinds: [], enabled: false }
    const map = res.kinds || {}
    const kinds = Object.keys(map)
      .filter(k => map[k] && map[k].enabled)
      .map(k => ({
        kind: k,
        label: LABELS[k] || k,
        templateId: map[k].template_id || '',
        quota: map[k].quota || 0
      }))
    return { kinds, enabled: !!res.send_enabled }
  } catch (e) {
    return { kinds: [], enabled: false }
  }
}

/**
 * 请求一次订阅授权并上报额度(必须在用户点击回调里调用)。
 * @returns {Promise<{ok:boolean, quota?:number, reason?:string}>}
 */
function requestGrant(kind, templateId) {
  return new Promise((resolve) => {
    if (!kind || !templateId) {
      resolve({ ok: false, reason: 'unavailable' })
      return
    }
    wx.requestSubscribeMessage({
      tmplIds: [templateId],
      success: async (r) => {
        if (r[templateId] !== 'accept') {
          resolve({ ok: false, reason: String(r[templateId] || 'reject') })
          return
        }
        try {
          const res = await api.grantSubscribe(kind, 1)
          resolve({ ok: !!(res && res.success), quota: (res && res.quota) || 0 })
        } catch (e) {
          resolve({ ok: false, reason: 'report-failed' })
        }
      },
      fail: (e) => resolve({ ok: false, reason: (e && e.errMsg) || 'fail' })
    })
  })
}

module.exports = { loadStatus, requestGrant, LABELS }
