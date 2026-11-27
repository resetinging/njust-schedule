# 小程序代码包体积规范

> 状态：现行
>
> 最后验证：2026-11-27

## 1. 目标

微信小程序单个主包建议不超过 1.5 MiB，硬上限为 2 MiB。当前项目保持单主包，但发布前必须用微信开发者工具实际编译结果确认体积。

## 2. 当前结果

| 项目 | 字节 |
|---|---:|
| 优化前实际预览 | 1,575,325 |
| 当前实际预览 | 1,454,399 |
| 1.5 MiB 阈值 | 1,572,864 |
| 当前余量 | 118,465 |

体积数据来自微信开发者工具 CLI `preview`，不是源码目录估算。

## 3. 打包排除项

`project.config.json` 的 `packOptions.ignore` 排除以下 TDesign 非运行时文件：

- `.wechatide.ib.json` 开发者工具组件元数据
- TDesign 根 `index.js`、`index.d.ts`
- 未使用的多语言 locale 文件
- 未使用的 dayjs locale 文件
- 未被运行时引用的大型 `.d.ts` 类型声明
- 未使用的 `t-search`、`t-tag` 组件目录

`zh_CN.js` 和 `dayjs/locale/zh-cn.js` 必须保留。

## 4. 验证流程

修改 `miniprogram_npm`、`project.config.json` 或新增页面后执行：

```powershell
& 'C:\Program Files (x86)\Tencent\微信web开发者工具\cli.bat' close `
  --project 'C:\Users\a\Documents\local\miniprogram'

& 'C:\Program Files (x86)\Tencent\微信web开发者工具\cli.bat' preview `
  --project 'C:\Users\a\Documents\local\miniprogram' `
  --qr-format image `
  --qr-output 'C:\Users\a\Documents\local\njust-schedule\.tmp\miniapp-preview.png' `
  --info-output 'C:\Users\a\Documents\local\njust-schedule\.tmp\miniapp-preview-info.json'
```

必须关闭并重新打开项目，否则开发者工具可能继续使用旧的 `packOptions` 缓存。

## 5. 后续规则

- 主包超过 1.5 MiB 时，优先排除构建元数据、类型声明和未使用语言包。
- 仍超过阈值时，将独立低频页面拆入分包。
- 不得删除运行时所需的 `zh_CN.js`、`zh-cn.js`、组件样式或依赖文件。
- 每次重新构建 NPM 后都要重新执行实际预览体积检查。
