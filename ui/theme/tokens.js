'use strict'

/**
 * 设计令牌（JS 侧唯一来源，与 styles/design-system.wxss 保持一致）
 *
 * 约定：
 * - 颜色：雾灰页面背景承托白色内容岛 + 品牌蓝少量强调 + 语义绿/琥珀/红区分状态
 * - 圆角：岛 32rpx、分组 24rpx、底部弹层 36rpx、短控件/底栏胶囊 999rpx
 * - 间距：8rpx 的倍数，页面边距 24rpx，岛内留白 24rpx
 * - 动效：按压 120ms、Tab 200ms、二级页/弹层 280ms，切页与弹层使用轻微 Q 弹
 * 修改此处必须同步 design-system.wxss，否则 DSL 生成页面与业务页面会不一致。
 */
const tokens = Object.freeze({
  color: Object.freeze({
    brand: '#3157D5',
    brandStrong: '#2544B5',
    brandLight: '#5D79E0',
    brandSoft: '#EEF2FF',
    brandLine: '#D8E0FA',
    page: '#F2F4F7',
    surface: '#FFFFFF',
    surfaceSoft: '#EDF0F4',
    surfaceHover: '#EEF1F5',
    line: '#E4E7EB',
    lineSoft: '#EEF0F3',
    text: '#20262D',
    textSecondary: '#59636F',
    textMuted: '#6B7684',
    textHint: '#9AA4B0',
    textOnBrand: '#FFFFFF',
    signal: '#A66A0B',
    signalSoft: '#FDF4E6',
    warning: '#A66A0B',
    warningSoft: '#FDF4E6',
    success: '#247B68',
    successSoft: '#E9F4F1',
    danger: '#B84750',
    dangerSoft: '#FBEEEF',
    // 功能入口的第四档强调色（学分），仅用于图标与少量点缀
    violet: '#6C63B8',
    violetSoft: '#F0EEFF'
  }),
  space: Object.freeze({
    xxs: '4rpx',
    xs: '8rpx',
    sm: '12rpx',
    md: '16rpx',
    lg: '24rpx',
    xl: '32rpx',
    page: '24rpx',
    section: '24rpx',
    island: '24rpx'
  }),
  radius: Object.freeze({
    chip: '8rpx',
    control: '16rpx',
    island: '32rpx',
    group: '24rpx',
    card: '32rpx',
    panel: '24rpx',
    sheet: '36rpx',
    pill: '999rpx'
  }),
  typography: Object.freeze({
    display: '700 48rpx/56rpx var(--font-display)',
    pageTitle: '700 36rpx/48rpx var(--font-display)',
    title: '700 36rpx/48rpx var(--font-display)',
    section: '700 28rpx/40rpx var(--font-display)',
    body: '400 28rpx/44rpx var(--font-body)',
    sub: '400 24rpx/36rpx var(--font-body)',
    caption: '400 22rpx/34rpx var(--font-body)',
    number: '700 64rpx/72rpx var(--font-num)'
  }),
  shadow: Object.freeze({
    island: '0 6rpx 20rpx rgba(20,28,36,.035)',
    card: '0 6rpx 20rpx rgba(20,28,36,.035)',
    nav: '0 8rpx 28rpx rgba(20,28,36,.08)',
    popup: '0 12rpx 40rpx rgba(20,28,36,.16)',
    sheet: '0 -8rpx 32rpx rgba(20,28,36,.12)'
  }),
  motion: Object.freeze({
    fast: '120ms',
    base: '200ms',
    slow: '260ms',
    standard: 'cubic-bezier(.2,.7,.3,1)',
    out: 'cubic-bezier(0,0,.2,1)',
    spring: 'cubic-bezier(.2,.8,.3,1)',
    bounce: 'cubic-bezier(.22,1.2,.36,1)'
  }),
  tdesign: Object.freeze({
    brand: '--td-brand-color',
    page: '--td-bg-color-page',
    container: '--td-bg-color-container',
    textPrimary: '--td-text-color-primary',
    textSecondary: '--td-text-color-secondary',
    radius: '--td-radius-default',
    radiusSheet: '--td-radius-extraLarge',
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
  return {
    '--primary': tokens.color.brand,
    '--primary-light': tokens.color.brandLight,
    '--primary-strong': tokens.color.brandStrong,
    '--primary-soft': tokens.color.brandSoft,
    '--primary-line': tokens.color.brandLine,
    '--bg-page': tokens.color.page,
    '--bg-card': tokens.color.surface,
    '--bg-sunken': tokens.color.surfaceSoft,
    '--bg-hover': tokens.color.surfaceHover,
    '--line': tokens.color.line,
    '--line-soft': tokens.color.lineSoft,
    '--text-primary': tokens.color.text,
    '--text-secondary': tokens.color.textSecondary,
    '--text-muted': tokens.color.textMuted,
    '--text-hint': tokens.color.textHint,
    '--signal': tokens.color.signal,
    '--signal-soft': tokens.color.signalSoft,
    '--success': tokens.color.success,
    '--success-soft': tokens.color.successSoft,
    '--danger': tokens.color.danger,
    '--danger-soft': tokens.color.dangerSoft,
    '--radius-chip': tokens.radius.chip,
    '--radius-control': tokens.radius.control,
    '--radius-island': tokens.radius.island,
    '--radius-group': tokens.radius.group,
    '--radius-card': tokens.radius.card,
    '--radius-panel': tokens.radius.panel,
    '--radius-sheet': tokens.radius.sheet,
    '--shadow-island': tokens.shadow.island,
    '--shadow-nav': tokens.shadow.nav,
    '--space-page': tokens.space.page,
    '--space-section': tokens.space.section,
    '--space-island': tokens.space.island,
    '--motion-fast': tokens.motion.fast,
    '--motion-base': tokens.motion.base,
    '--motion-slow': tokens.motion.slow,
    '--ease-standard': tokens.motion.standard,
    '--ease-bounce': tokens.motion.bounce,
    '--shadow-pop': tokens.shadow.popup
  }
}

module.exports = { tokens, resolveToken, createCssVariables }
