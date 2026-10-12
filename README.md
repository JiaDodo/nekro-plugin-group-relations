# 群关系观察 · Nekro Agent

基于 QQ 群内 **@ 与引用回复**，生成互动关系网络、聊天搭子排行、个人互动报告和高清 PNG。附带管理员 Web 看板，支持拖动、缩放、点击成员和连线查看统计依据。

> 仅供娱乐。连线表示已记录的互动，不代表现实亲密度；没有连线不代表关系疏远。

![管理员看板（全部为模拟数据）](https://raw.githubusercontent.com/JiaDodo/nekro-plugin-group-relations/main/docs/dashboard-demo.png)

[查看 PNG 报告示例](https://github.com/JiaDodo/nekro-plugin-group-relations/blob/main/docs/report-demo.png) · [查看手机看板示例](https://github.com/JiaDodo/nekro-plugin-group-relations/blob/main/docs/mobile-demo.png)

## Web 看板入口

安装并启用后，在当前 Nekro Agent 地址后加：

**[打开群关系看板](/plugins/JiaDodo.group_relations/)**

例如：`http://localhost:8021/plugins/JiaDodo.group_relations/`。

使用 Nekro Agent 后台的管理员账号登录。看板和 API 与机器人共用服务，不需要额外开放端口。普通账号不能访问统计数据。看板外壳不包含群数据；所有数据接口使用 Bearer 鉴权，不接受 URL 令牌。

## 安装

兼容目标：**Nekro Agent 2.3.3，Python 3.11/3.12，OneBot V11 / NapCat**。

在宿主机的数据目录下安装（请按自己的路径修改）：

```bash
cd /home/nekro/srv/nekro_agent/plugins/workdir
git clone https://github.com/JiaDodo/nekro-plugin-group-relations.git group_relations
```

通过插件管理重新加载插件；若当前版本不能发现新增插件目录，重启 Nekro Agent。找到“群关系观察”，启用后打开看板。首次请求会从 Nekro Agent **已保存的消息**回填所选周期和上一周期的互动记录。

插件不修改 Nekro Agent 主程序或前端。管理页自动显示配置、方法和说明；交互看板通过上面的链接打开，不会新增主程序左侧菜单。

## 群里使用

```text
/relations 7            最近 7 天关系图片（别名：/群关系图、/群关系周报）
/my_relations 7         自己的聊天搭子（别名：/我的群关系）
/relations_optout       退出本群统计并清理个人互动记录（别名：/退出关系统计）
/relations_optin        重新加入统计（别名：/加入关系统计）
```

周期为 1–30 天。也可以对机器人说“分析本群关系”“生成最近一周的关系图”“看看我的聊天搭子”，由 Agent 调用插件工具。工具固定使用当前群，不接受任意群标识。

## 图片渲染

使用自托管 **browserless Chromium** 的 `/screenshot` 接口。默认地址 `http://nekro_html2img:3000`；渲染容器需要与 Nekro Agent 在可互通的 Docker 网络中，并安装中文字体（推荐 Noto Sans CJK）。

统计结果 → 确定布局的 SVG → 自包含 HTML 报告 → 2 倍像素密度 PNG。前端无需 CDN，不依赖 AI 绘图。网络图与看板使用相同绘图函数。PNG 失败时群命令回退文字；后台仍可下载 SVG。

## 配置

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| 群白名单 | 空 | 空表示所有 QQ 群；填 `onebot_v11-group_群号` 可限制群 |
| 互动记录保留天数 | 90 | 插件数据的保留周期；不改变主程序聊天历史 |
| 单次历史同步消息上限 | 50000 | 超出时明确标注部分样本 |
| 关系图最少互动次数 | 2 | 少于此次数不画线；统计明细仍保留 |
| 单日单向互动计分上限 | 20 | 限制刷屏对指数的影响，实际次数仍展示 |
| 启用 AI 娱乐点评 | 关 | 手动请求时才调用，只发送统计和昵称，不发送聊天正文 |
| 点评模型组 | 空 | 空表示系统主聊天模型组 |
| 图片渲染服务 | `http://nekro_html2img:3000` | browserless 服务地址 |
| 图片渲染令牌 | 空 | 渲染服务启用 token 时填写 |
| 渲染超时秒数 | 60 | PNG 渲染超时 |

## 统计方法与边界

- 一条消息对同一人的 @ 与引用回复只算一次，优先归为引用回复；排除自己、全体成员、机器人和退出统计的用户。
- 只有明确目标才形成连线。相邻发言、同时在线和单纯发言多，不自动解释为关系。
- 引用回复优先根据同群消息 ID 解析作者；找不到作者时不强行归属。引用其他群不会计入本群。
- 指数使用引用回复权重 3、@ 权重 2，限制每日单向计分，再按双方发言量、双向程度和互动天数调整。它是排序指数，不是百分比或关系概率。
- “稳定聊天搭子”要求至少 3 个互动日期且双向比例不低于 0.4。互动圈是重复双向连线的连通分组，不代表真实社交团体。
- 第一版不基于聊天正文推断话题同盟、互怼、恋爱、敌意或人格。AI 仅润色结构化统计。
- 仅能分析机器人接收且主程序保留的记录。被过滤、丢失、清理的消息不会被恢复；没有上一周期数据时会提示，不把新增计数直接当成“升温”。
- 采集回调快速入队，SQLite 写入、历史同步、图布局与截图均在回调之外处理。队列溢出会记录日志，可同步历史补齐。

## 数据管理

数据保存到 `plugin.get_plugin_data_dir()`：

```text
relations.sqlite3       群、成员、时间、@ 对象、引用 ID；不存聊天正文
exports/*.png           报告缓存（保留约 24 小时，定期清理）
```

按群隔离；后台可暂停采集、清空本群数据。清空后会记录时间边界，旧历史不会再次回填。退出统计后会移除个人发言记录、入向 @ 和已解析引用作者，后续导入继续排除；重新加入后仍保留在主程序中的历史可能被再次导入。插件“数据管理”标签只显示框架 KV 数据，本插件的 SQLite 请通过看板管理。

## 开发与验证

```bash
python -m pip install fastapi httpx
python -m unittest discover -s tests -v
python scripts/demo.py /tmp/group-relations-demo
```

测试覆盖互动去重、刷屏计分、统计时间边界、图布局、昵称转义、群隔离、退出统计、清空阻止回填、接口鉴权和参数校验。模拟脚本只生成虚构成员数据，不读取机器人数据库。

## 升级与故障排查

- 更新：在插件目录执行 `git pull`，然后重启 Nekro Agent；动态路由热重载在框架中可能保留旧路由，更新后优先重启。
- 图片失败：检查渲染地址、令牌、Docker 网络和中文字体；查看插件日志，不需要把渲染端口公开到公网。
- 看板无群：检查 OneBot 接入是否收到群消息，以及群白名单是否使用完整 chat_key。
- 非默认反向代理路径：当前看板按根路径部署，登录地址为 `/api/user/login`；若主程序使用子路径代理，需要同步调整登录路径。

MIT License。
