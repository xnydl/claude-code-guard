# Claude Code Guard

给本机 Claude Code 指定一个固定最终出口节点，维护网络保护；旧登录资料只在用户明确授权后定向清理。不保证不封号或绝对不泄漏。

## 安装

需要 Node.js 22+：

```bash
npx skills add xnydl/claude-code-guard -g -y
```

或解压后按 `INSTALL.md` 拷到 `~/.claude/skills` / `~/.grok/skills`。

新开对话，输入 `/claude-code-guard`。

## 使用前

只指定 **一个固定最终叶子节点**，不添加白名单、备用出口或自动切换。单跳和链式代理都应落到这个节点；同节点的动态 IP 可按地区验证，不能因此改用其他节点。更换出口须明确替换原目标。

已有保护环境先读 [维护说明](references/maintenance.md)，不要重跑旧安装器覆盖配置：

```bash
python3 scripts/ccg_audit.py
```

这是只读文件审计，不是网络泄漏测试。附带通用模板与现用部署能力有差异，见 [客户端说明](references/clients.md)；保护边界见 [分层说明](references/layers.md)。安装 Skill 不会自动部署或修改运行中的保护脚本。

——————————————————————————————————————————————
打个小广

AI 代充：https://ssyai.xytpark.cn/

L 站用户可享社区价，每个品一月一次优惠

需要大量的客户可以开个代理，预充的金额会到你的余额

支持企业对接，对公转账，开票，普票专票都可

也欢迎佬友们吃回扣，合作共赢～（为了不浪费我的富可敌国，我要争取做到每日冒泡 hh
原作者的邀请链接：https://ssyai.xytpark.cn/register?invite=R73D442E6A446
