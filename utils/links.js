/**
 * 常用链接 — 数据集中在此, 便于增删维护
 * 说明: 小程序无法直接打开外部网页(web-view 需业务域名白名单, 外部站点无法配置),
 *       因此交互设计为「点击复制链接 → 在浏览器粘贴打开」。
 */
const LINK_GROUPS = [
  {
    title: '校内服务',
    icon: '🌐',
    items: [
      { name: '南京理工大学 / 官网', url: 'https://www.njust.edu.cn/' },
      { name: '南京理工大学 / 统一身份认证平台', url: 'https://ehall2.njust.edu.cn/' },
      { name: '南京理工大学 / 教务处', url: 'https://jwc.njust.edu.cn/' },
      { name: '南京理工大学 / 研究生院', url: 'https://gs.njust.edu.cn/' },
      { name: '南京理工大学 / 图书馆', url: 'https://lib.njust.edu.cn/' },
      { name: '南京理工大学 / WebVPN', url: 'https://webvpn.njust.edu.cn/' },
      { name: '南京理工大学 / 学校邮箱', url: 'https://mail.njust.edu.cn/' },
      { name: '南京理工大学 / 缴费平台', url: 'https://cwcmh.njust.edu.cn/payment/pay/payment.jsp' },
      { name: '南京理工大学 / 智慧团委', url: 'https://zhtw.njust.edu.cn/' },
      { name: '南京理工大学 / X·Space', url: 'https://xspace.njust.edu.cn/main.htm' },
      { name: 'NJUST 开放知识库', url: 'https://njust.wiki/' },
    ],
  },
  {
    title: '考试与学习',
    icon: '📄',
    items: [
      { name: '四六级报名', url: 'https://cet-bm.neea.edu.cn/' },
      { name: '四六级准考证', url: 'https://cet-bm.neea.edu.cn/Home/QueryTestTicket' },
      { name: '四六级成绩', url: 'https://cet.neea.edu.cn/cet/' },
      { name: '计算机等级考试报名 & 准考证', url: 'https://ncre-bm.neea.cn/' },
      { name: '计算机等级考试成绩', url: 'https://cjcx.neea.edu.cn/html1/folder/22014/5476-1.htm' },
      { name: 'CCF 计算机专业资格认证', url: 'https://cspro.org/' },
      { name: '普通话成绩', url: 'https://www.cltt.org/studentscore' },
      { name: '超星学习通', url: 'https://i.mooc.chaoxing.com/space/index' },
      { name: '中国大学 MOOC', url: 'https://www.icourse163.org/' },
    ],
  },
]

function totalCount() {
  return LINK_GROUPS.reduce((n, g) => n + g.items.length, 0)
}

module.exports = { LINK_GROUPS, totalCount }
