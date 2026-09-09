# Claude Code Guard

给本机 Claude Code / Claude CLI **发往 Claude、Anthropic 的请求**钉在一个固定最终出口节点上。  
**shell、脚本、git、远端数据库不要拦**——那些流量走 Clash 规则（国内 DIRECT）。

不保证不封号、绝对不泄漏，或不同账号无法关联。不要把节点名、住宅 IP、第三方评分当成官方认可。

## 保护什么，不保护什么

| 流量 | 怎么走 |
| --- | --- |
| Claude Code / CLI → `claude.ai` / `api.anthropic.com` | `HTTP_PROXY` → 本地 gate `:7899` → 专用入站 `:7898` → **唯一指定叶子** |
| curl 等仍走系统代理、且命中你授权的国内/公司域名 | gate `:7899` → 规则入站 `:7897` → Clash Rule（通常 CN DIRECT） |
| shell / 脚本 / mysql / redis / mongo / git | **真实网络**。Seatbelt 不拦。Clash TUN + 规则分流 |
| Mihomo / Clash 控制口 | 沙箱拒绝，避免进程自己改出口 |

不要做：节点白名单、备用出口、自动轮换。只指定 **一个** 完整叶子名。

## 复制到另一台机器

不要复制别人的节点名、端口、公司域名。先打开你自己的梯子。

1. Clash / Mihomo：**规则模式**，TUN 开，IPv6 关。mixed-port 作为普通规则入口（示例 `:7897`）。
2. 增加一条 **专用 mixed 入站**（示例 `:7898`，只听 `127.0.0.1`，UDP 关），`proxy` 填你选定的那一个叶子完整名字。
3. 用 Skill 里的 wrapper：Claude 的 `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` 指向 gate（示例 `:7899`）。不要把国内库主机写进 `NO_PROXY` 来“绕过保护”——数据库客户端本来就不走 HTTP 代理。
4. Seatbelt 放行普通出站，**只拒绝** Clash 控制 socket。旧模板若 `deny network-outbound` 只放行 localhost，Go 的 MySQL/Redis/Mongo 会 `EPERM`。改沙箱后 **必须重启 Claude**，旧进程还是旧规则。
5. 启动前 / 发 prompt 时校验：当前叶子 == 你指定的那一个；同叶子的动态 IP 可以更新，换叶子就拦截。失败拦截这一次请求，不要杀进程。
6. 可选：环境变量 `CCG_RULES_HOST_SUFFIXES=example.com,corp.example`（逗号分隔）。只有 HTTP 代理 CONNECT 会看这份列表。不要把别人的域名抄过来。

探测（不自动改配置）：

```bash
python3 scripts/ccg_detect.py --list
```

已有保护环境先审计，不要重跑安装器覆盖：

```bash
python3 scripts/ccg_audit.py
```

## 安装这个 Skill

需要 Node.js 22+：

```bash
npx skills add xnydl/claude-code-guard -g -y
```

或解压后按 [INSTALL.md](INSTALL.md) 链到 `~/.claude/skills` / `~/.grok/skills`。新开对话，输入 `/claude-code-guard`。

安装 Skill **不会**自动改 Clash、wrapper 或沙箱。

## 常见坑

- **远端库被拦、本地库可以**：几乎一定是旧沙箱只放行 localhost。更新 `claude-network.sb` 后重启 Claude。
- **改了文件仍 EPERM**：当前 Claude 进程还是启动时的旧沙箱。
- **把作者的节点名/端口原样粘贴**：每台机器的 Clash 入站和叶子名都不同。
- **为了“防泄漏”把所有 TCP 送进 7898**：国内 RDS/Redis 会被送到境外叶子，表现为偶发连不上。数据库走规则分流即可。

Agent 操作说明见 [SKILL.md](SKILL.md)。分层与验收见 [references/layers.md](references/layers.md)。维护见 [references/maintenance.md](references/maintenance.md)。

---

打个小广

AI 代充：https://ssyai.xytpark.cn/

L 站用户可享社区价，每个品一月一次优惠

需要大量的客户可以开个代理，预充的金额会到你的余额

支持企业对接，对公转账，开票，普票专票都可

也欢迎佬友们吃回扣，合作共赢～（为了不浪费我的富可敌国，我要争取做到每日冒泡 hh
原作者的邀请链接：https://ssyai.xytpark.cn/register?invite=R73D442E6A446
