# Claude Code 防封 Skill — 安装说明

解压后得到 `claude-code-guard/` 目录。

## 1. 装到 AI 工具里

在解压后的目录里执行（或把路径改成你的实际位置）：

```bash
# Grok
mkdir -p ~/.grok/skills
ln -s "$PWD/claude-code-guard" ~/.grok/skills/claude-code-guard

# Claude Code
mkdir -p ~/.claude/skills
ln -s "$PWD/claude-code-guard" ~/.claude/skills/claude-code-guard
```

Windows：把整个文件夹拷到 `%USERPROFILE%\.grok\skills\claude-code-guard` 或 `%USERPROFILE%\.claude\skills\claude-code-guard`。

新开一个对话，输入 `/claude-code-guard`。

## 2. 已有环境先维护，不重装

安装 Skill 不等于安装网络保护。先读 `SKILL.md` 和 `references/maintenance.md`，在 Skill 目录做只读审计：

```bash
python3 scripts/ccg_audit.py
```

本机现用 `~/.local/claude-guard/` 与旧通用模板的 `~/.claude-guard/` 不同。旧安装器会拒绝覆盖发现的保护文件或已有 Hook；不要删除这些文件来绕过检查。按实际部署增量维护，保留默认权限、鼠标、开发分流及普通浏览器资料。

## 3. 新环境只指定一个最终节点

先打开你自己的梯子，然后：

```bash
python3 claude-code-guard/scripts/ccg_detect.py --list
```

Windows 用 `py -3` 或 `python`。

从清单里确认 **一个固定叶子节点**的完整名字，不配置白名单、备用节点或自动轮换。单跳/链式代理均须解析到这个唯一节点；更换时替换旧目标而非追加。节点名字或旗帜不代表实际地区，仍需出口验证。

先读 `references/clients.md`：通用脚本是旧模板，并未实现所有现用链式/会话策略。先按该机能力适配、在无账号环境测试，获准部署后才使用单一 `--node` 参数，例如：

```bash
python3 claude-code-guard/scripts/ccg_install.py --node "这里换成你选的完整节点名" --region TW
```

这个安装器只输出专用 listener 的配置建议，不自动合并 Mihomo 配置或完成服务部署；不能仅凭脚本退出成功就登录。没有选定节点、入口未配置或检查未通过时，不进行登录。

## 4. 账号资料只按授权清理

更新 Skill、升级 CLI 或曾被封号都不自动授权删除。先读 `references/identity-purge.md`，确认具体应用、账号和 profile 范围，只报告存在性/数量，不显示凭证或正文。

旧 `--purge-browser` 可能清理全部 Camoufox Persistent profile，不能当单账号定向清理。不要顺便清空 Chrome、Claude 配置、聊天、钥匙串或 CC Switch；关闭运行中实例也应先确认影响。

完整流程见 `SKILL.md`。
