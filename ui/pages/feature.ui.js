'use strict'

module.exports = {
  version: 1,
  page: 'pages/main/main',
  theme: 'brand',
  tree: {
    type: 'Page',
    id: 'feature-page',
    props: { surface: 'page' },
    children: [
      {
        type: 'Section',
        id: 'academic-section',
        props: { title: '课业' },
        children: [
          {
            type: 'Grid',
            id: 'academic-grid',
            props: { columns: 2 },
            children: [
              {
                type: 'ActionCard',
                id: 'exam-entry',
                props: { icon: 'doc', title: '考试安排', tone: 'brand' },
                events: { tap: { action: 'openFeature', data: { sub: 'exams' } } }
              },
              {
                type: 'ActionCard',
                id: 'eval-entry',
                props: { icon: 'clipboard', title: '教学评价', tone: 'violet' },
                events: { tap: { action: 'openFeature', data: { sub: 'eval' } } }
              },
              {
                type: 'ActionCard',
                id: 'grade-entry',
                props: { icon: 'chart', title: '成绩查询', tone: 'success' },
                events: { tap: { action: 'openFeature', data: { sub: 'grades' } } }
              },
              {
                type: 'ActionCard',
                id: 'credit-entry',
                props: { icon: 'award', title: '学分进度', tone: 'signal' },
                events: { tap: { action: 'openFeature', data: { sub: 'credit' } } }
              }
            ]
          }
        ]
      },
      {
        type: 'Section',
        id: 'campus-section',
        props: { title: '校园工具' },
        children: [
          {
            type: 'Grid',
            id: 'campus-grid',
            props: { columns: 2 },
            children: [
              {
                type: 'ActionCard',
                id: 'freeclass-entry',
                props: { icon: 'building', title: '空教室', tone: 'brand' },
                events: { tap: { action: 'openTool', data: { page: 'freeclass' } } }
              },
              {
                type: 'ActionCard',
                id: 'gallery-entry',
                props: { icon: 'image', title: '校园图鉴', tone: 'violet' },
                events: { tap: { action: 'openTool', data: { page: 'gallery' } } }
              },
              {
                type: 'ActionCard',
                id: 'audit-entry',
                props: { icon: 'search', title: '蹭课查询', tone: 'signal' },
                events: { tap: { action: 'openTool', data: { page: 'audit' } } }
              }
            ]
          }
        ]
      },
      {
        type: 'TabBar',
        id: 'main-tabbar',
        props: { active: 'feature' }
      }
    ]
  }
}
