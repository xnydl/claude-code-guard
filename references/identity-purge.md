# 账号残留扫描与定向清理

仅用于用户明确提出的本地隐私/数据清理。更新 Skill/CLI、切节点或提及曾被封号，不自动授权删除资料。

## 扫描不读出内容

- 区分 Code 配置/凭证/项目会话、Desktop 应用数据/钥匙串、浏览器特定 profile 的站点数据。
- 只报告位置、类型、存在性、数量，不输出 token、API key、Cookie、邮箱、machineID、会话正文或钥匙串内容。
- ccg_identity.py scan 是旧辅助工具，先审查输出/目标；不代表全面残留扫描。
- machineID/Cookie 存在不能证明封号原因；本地清理不删除服务器记录，也不能保证账号不关联。

## 删除对应授权

1. 应用/账号/profile 不明时先问，不能模糊匹配后批量删除。
2. 说明退出哪些账号、丢失哪些本地会话；关闭运行中实例需授权，不为清一个 profile 杀所有浏览器。
3. 仅获准清 Claude 站点 Cookie/历史时，保留其他站点、书签、扩展、密码和其他 Chrome profile；处理数据库锁与一致性。
4. 保留网络 Hook、wrapper、代理绑定、CC Switch、源文件和未授权的聊天。不顺便清空 ~/.claude、Chrome User Data、系统缓存/偏好或 LaunchServices。
5. 不默认跑 purge --yes 或 --purge-browser；旧 --purge-browser 可能清全部 Camoufox Persistent profile，不能代表单账号定向清理。
6. 凭证备份仍是敏感残留，不能无说明复制。删除后只复查目标存在性，说明恢复能力和未处理范围。

资料丢失或启动失败时暂停清理，只读查原因和恢复办法；不重建默认 profile 掩盖问题。
