'use strict'

const tokens = Object.freeze({
  color: Object.freeze({
    brand: '#3157D5',
    brandStrong: '#2544B5',
    brandSoft: '#EEF2FF',
    page: '#F5F7FA',
    surface: '#FFFFFF',
    surfaceSoft: '#EDF1F5',
    text: '#182230',
    textMuted: '#748196',
    signal: '#D99025',
    signalSoft: '#FFF6E5',
    success: '#1F9D82',
    successSoft: '#E9F7F3',
    warning: '#D99025',
    danger: '#D75C62',
    dangerSoft: '#FCEEEF',
    violet: '#6C63B8',
    violetSoft: '#F0EEFF'
  }),
  space: Object.freeze({
    xxs: '4rpx',
    xs: '8rpx',
    sm: '12rpx',
    md: '20rpx',
    lg: '32rpx',
    xl: '48rpx'
  }),
  radius: Object.freeze({
    control: '12rpx',
    card: '18rpx',
    panel: '24rpx',
    sheet: '32rpx',
    pill: '999rpx'
  }),
  typography: Object.freeze({
    display: '600 48rpx/56rpx var(--font-display)',
    title: '600 36rpx/48rpx var(--font-display)',
    body: '400 28rpx/44rpx var(--font-body)',
    caption: '400 22rpx/34rpx var(--font-body)',
    number: '600 64rpx/72rpx var(--font-num)'
  }),
  shadow: Object.freeze({
    card: '0 4rpx 16rpx rgba(24,34,48,.04)',
    glass: '0 16rpx 44rpx rgba(24,34,48,.10)',
    popup: '0 -12rpx 40rpx rgba(24,34,48,.13)'
  }),
  motion: Object.freeze({
    fast: '120ms',
    base: '200ms',
    slow: '280ms',
    standard: 'cubic-bezier(.2,.8,.2,1)',
    spring: 'cubic-bezier(.34,1.56,.64,1)'
  }),
  tdesign: Object.freeze({
    brand: '--td-brand-color',
    page: '--td-bg-color-page',
    container: '--td-bg-color-container',
    textPrimary: '--td-text-color-primary',
    textSecondary: '--td-text-color-secondary',
    radius: '--td-radius-default',
    fontFamily: '--td-font-family'
  })
})

function resolveToken(path) {
  const value = String(path || '').replace(/^\$token\.?/, '').split('.').filter(Boolean)
  return value.reduce((current, key) => (
    current && Object.prototype.hasOwnProperty.call(current, key)
      ? current[key]
      : undefined
  ), tokens)
}

function createCssVariables() {
  const vars = {
    '--primary': tokens.color.brand,
    '--primary-strong': tokens.color.brandStrong,
    '--primary-soft': tokens.color.brandSoft,
    '--bg-page': tokens.color.page,
    '--bg-card': tokens.color.surface,
    '--bg-sunken': tokens.color.surfaceSoft,
    '--text-primary': tokens.color.text,
    '--text-muted': tokens.color.textMuted,
    '--signal': tokens.color.signal,
    '--signal-soft': tokens.color.signalSoft,
    '--success': tokens.color.success,
    '--success-soft': tokens.color.successSoft,
    '--danger': tokens.color.danger,
    '--danger-soft': tokens.color.dangerSoft,
    '--radius-control': tokens.radius.control,
    '--radius-card': tokens.radius.card
  }
  return vars
}

module.exports = { tokens, resolveToken, createCssVariables }
