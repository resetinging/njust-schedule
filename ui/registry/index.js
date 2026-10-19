'use strict'

const definitions = {
  Page: { kind: 'native', tag: 'view' },
  Section: { kind: 'native', tag: 'view' },
  Stack: { kind: 'native', tag: 'view' },
  Inline: { kind: 'native', tag: 'view' },
  Grid: { kind: 'native', tag: 'view' },
  HeroSummary: { kind: 'macro', expandsTo: 'hero-summary' },
  TabBar: { kind: 'macro', expandsTo: 'tab-bar' },
  Text: { kind: 'native', tag: 'text' },
  Icon: { kind: 'local', tag: 'icon' },
  Button: { kind: 'tdesign', tag: 't-button', import: 'tdesign-miniprogram/button/button' },
  Cell: { kind: 'tdesign', tag: 't-cell', import: 'tdesign-miniprogram/cell/cell' },
  CellGroup: { kind: 'tdesign', tag: 't-cell-group', import: 'tdesign-miniprogram/cell-group/cell-group' },
  Switch: { kind: 'tdesign', tag: 't-switch', import: 'tdesign-miniprogram/switch/switch' },
  Picker: { kind: 'tdesign', tag: 't-picker', import: 'tdesign-miniprogram/picker/picker' },
  Search: { kind: 'tdesign', tag: 't-search', import: 'tdesign-miniprogram/search/search' },
  Popup: { kind: 'tdesign', tag: 't-popup', import: 'tdesign-miniprogram/popup/popup' },
  Dialog: { kind: 'tdesign', tag: 't-dialog', import: 'tdesign-miniprogram/dialog/dialog' },
  Toast: { kind: 'tdesign', tag: 't-toast', import: 'tdesign-miniprogram/toast/toast' },
  Skeleton: { kind: 'tdesign', tag: 't-skeleton', import: 'tdesign-miniprogram/skeleton/skeleton' },
  Empty: { kind: 'tdesign', tag: 't-empty', import: 'tdesign-miniprogram/empty/empty' },
  Tag: { kind: 'tdesign', tag: 't-tag', import: 'tdesign-miniprogram/tag/tag' },
  Badge: { kind: 'tdesign', tag: 't-badge', import: 'tdesign-miniprogram/badge/badge' },
  ActionCard: { kind: 'macro', expandsTo: 'Cell' },
  MetricCard: { kind: 'local', tag: 'metric-card' },
  CourseCard: { kind: 'local', tag: 'course-card' },
  WeekGrid: { kind: 'local', tag: 'week-grid' },
  AuditCourseCard: { kind: 'local', tag: 'audit-course-card' }
}

function createRegistry() {
  return new Map(Object.entries(definitions).map(([name, spec]) => [
    name,
    Object.freeze({ name, ...spec })
  ]))
}

function getComponent(name) {
  return definitions[name] || null
}

module.exports = { definitions, createRegistry, getComponent }
