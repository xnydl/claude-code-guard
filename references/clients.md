# 客户端识别与模板能力

先识别 OS、Claude 命令解析、wrapper/启动服务、监听端口、代理客户端和控制器；不凭安装路径或 UI 推断进程状态。探测不自动改系统代理、规则或节点。

- macOS + Mihomo：查活动配置/控制器，确认专用入站 proxy 的最终叶子、TUN、IPv6/DNS。单跳和链式都以实际路由为准。
- Windows：识别 Clash/v2rayN/sing-box 等，不照搬 launchd、Unix socket 或 sandbox-exec。代理变量不是防火墙，出站限制要独立验证。
- 只有 SOCKS/HTTP 端口：只能检测端口/出口，不能自动验证最终节点。报告能力缺口，不伪造身份。
- 控制器鉴权失败、配置缺失、链路不可解析：不能拿空 JSON 或旧状态冒充核验。探测输出可能包含 secret，不原样分享。

## 脚本状态

| 脚本 | 用途/限制 |
| --- | --- |
| ccg_audit.py | 新增只读维护审计，不执行被审计脚本 |
| test_skill.py | 离线验证，不访问账号或运行中配置 |
| ccg_detect.py --list | 旧跨平台探测辅助，结果仍需核对 |
| ccg_install.py / ccg_guard.py / ccg_gate.py | 旧单节点通用模板，安装至 ~/.claude-guard/，不是现用本机运行版本 |
| wrapper.sh/.ps1、camoufox.sh/.ps1 | 旧通用配套，不能替换现用持久化启动器 |
| claude-wrapper.sh、claude-network-gate.py、claude-camoufox.sh、config.example.env | 历史 macOS 样例，有过期行为/路径，不能作为维护更新源 |

旧安装器仅输出 listener YAML 建议，不会自动配置 Mihomo；选定端口不代表入口已存在。它使用单个 expected_node，但缺少完整链式/动态 IP 会话策略。旧 ccg_gate.py 有检查/监控逻辑，现用 gate 则不同，不能混用描述。

本次为模板增加防误操作：安装器在发现已有保护文件/Hook 时，在探测和写入前拒绝覆盖；请求 Hook 控制口不可用/异常时直接阻止，不追加第二轮长探测。这些修改留在 Skill 模板中，不自动发布到运行中 Hook。

## 新装审查

1. 已有选择沿用；新环境只确认一个最终出口叶子、地区、链式入口和浏览器需求；不提供白名单或备用出口配置。
2. 确定平台隔离能力并适配模板，不直接跑历史安装器；通过无账号隔离测试后才部署。
3. 探测端口/路径，增量合并配置，保留其他 Hook、权限和开发分流。不擅自开启 bypassPermissions。
4. 备份即将修改的具体配置，不复制整份账号/浏览器数据；未完成 listener/服务配置时不能声称安装完成。
5. 验证允许与拒绝路径，交付启动方法和限制。部署成功不等于通过泄漏测试。
