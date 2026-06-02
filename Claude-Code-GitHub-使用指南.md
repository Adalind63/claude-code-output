# Claude Code × GitHub 使用指南

> **配置日期：** 2026-06-02
> **GitHub 账号：** Adalind63
> **主仓库：** https://github.com/Adalind63/claude-code-output
> **本地路径：** `C:\Users\admin\claude-code-output`

---

## 目录

1. [环境概览](#1-环境概览)
2. [基础工作流](#2-基础工作流)
3. [常用操作场景](#3-常用操作场景)
4. [命令速查表](#4-命令速查表)
5. [多仓库管理](#5-多仓库管理)
6. [最佳实践](#6-最佳实践)
7. [故障排除](#7-故障排除)

---

## 1. 环境概览

### 1.1 已配置的组件

```
你的电脑
├── Git 2.54.0                    ← 版本控制
├── GitHub CLI (gh) 2.74.0        ← GitHub 命令行工具
│   └── 位置: %LOCALAPPDATA%\GitHubCLI\bin\gh.exe
├── SSH Key (ED25519)             ← 免密推送（已添加到 GitHub）
│   └── 位置: ~/.ssh/id_ed25519
├── GH_TOKEN（永久环境变量）       ← gh CLI 自动使用
└── Git 全局配置
    ├── user.name: Adalind Petrov
    ├── user.email: 2212777179@qq.com
    └── HTTPS → SSH 自动重定向    ← github.com 自动走 SSH
```

### 1.2 为什么用 SSH 而不是 HTTPS？

你本地的网络环境对 git.exe 的 HTTPS 连接有限制（TLS 握手被重置）。因此配置了：
- SSH 协议传输代码
- 全局 `insteadOf` 规则：任何 `https://github.com` 的 URL 自动替换为 `git@github.com`

**对你来说完全透明**——你正常使用即可，无需关心底层协议。

---

## 2. 基础工作流

### 2.1 Claude 产出代码 → 保存到本地 → 推送到 GitHub

**最常用的流程，3 步完成：**

```
第 1 步：Claude 生成代码 → 自动写入 claude-code-output 目录
第 2 步：对 Claude 说 "提交并推送"
第 3 步：代码出现在 https://github.com/Adalind63/claude-code-output
```

**示例对话：**

> 👤 你：帮我写一个 Python 爬虫脚本
>
> 🤖 Claude：（写代码，保存到 `C:\Users\admin\claude-code-output\crawler.py`）
>
> 👤 你：提交到 GitHub
>
> 🤖 Claude：已提交并推送到 `claude-code-output` 仓库

### 2.2 完整的手动流程（如果你想自己操作）

如果你在终端中手动操作，步骤是：

```powershell
# 1. 进入仓库目录
cd C:\Users\admin\claude-code-output

# 2. 查看当前状态
git status

# 3. 添加所有新文件
git add -A

# 4. 提交（写清楚做了什么）
git commit -m "feat: 添加 Python 爬虫脚本"

# 5. 推送到 GitHub
git push
```

---

## 3. 常用操作场景

### 场景 A：保存单个文件

> 👤 你：帮我把这个 `utils.py` 提交到 GitHub，commit 信息写"添加工具函数"

Claude 会执行：
```powershell
cd C:\Users\admin\claude-code-output
git add utils.py
git commit -m "添加工具函数"
git push
```

### 场景 B：一次保存所有修改

> 👤 你：把刚才所有的改动都推送到 GitHub

Claude 会执行：
```powershell
cd C:\Users\admin\claude-code-output
git add -A
git commit -m "批量更新: [自动生成摘要]"
git push
```

### 场景 C：为不同项目创建子目录

> 👤 你：帮我写一个 React 组件，放到 `claude-code-output/react-components/` 目录下

```
C:\Users\admin\claude-code-output\
├── react-components\          ← 新项目目录
│   ├── Button.tsx
│   ├── Modal.tsx
│   └── README.md
├── python-scripts\            ← 之前的项目
│   └── crawler.py
├── README.md
└── .gitignore
```

### 场景 D：创建全新的 GitHub 仓库

> 👤 你：帮我创建一个新仓库叫 `my-api-server`

Claude 会执行：
```powershell
gh repo create Adalind63/my-api-server --public
```

然后在新仓库中初始化并推送代码。

### 场景 E：查看提交历史

> 👤 你：看看最近提交了什么

Claude 会执行：
```powershell
cd C:\Users\admin\claude-code-output
git log --oneline -10
```

### 场景 F：回退某个文件

> 👤 你：把 `config.py` 恢复到上次提交的版本

Claude 会执行：
```powershell
cd C:\Users\admin\claude-code-output
git checkout -- config.py
```

---

## 4. 命令速查表

### 4.1 你对 Claude 说的自然语言指令

| 你说的 | Claude 做的 |
|--------|------------|
| "提交并推送" | add → commit → push |
| "推送到 GitHub" | git push |
| "提交，信息写 xxx" | git commit -m "xxx" → git push |
| "看看状态" | git status |
| "查看提交历史" | git log |
| "创建新仓库 xxx" | gh repo create → 初始化 → 推送 |
| "撤销刚才的修改" | git checkout / git reset |
| "把这个文件加到 .gitignore" | 编辑 .gitignore → 提交推送 |

### 4.2 终端手动命令

```powershell
# ===== 日常使用 =====
git status                          # 看改了哪些文件
git diff                            # 看具体改了什么内容
git add <文件名>                     # 添加指定文件
git add -A                          # 添加所有改动
git commit -m "提交信息"            # 提交
git push                            # 推送到 GitHub

# ===== 查看历史 =====
git log --oneline                   # 简明提交历史
git log --oneline -5                # 最近 5 条
git show <commit-hash>              # 查看某次提交的详情

# ===== 撤销操作 =====
git checkout -- <文件名>            # 撤销单个文件的修改
git reset HEAD <文件名>             # 取消暂存
git reset --soft HEAD~1             # 撤销最近一次 commit（保留修改）

# ===== 分支操作 =====
git branch                          # 查看分支
git checkout -b <新分支名>          # 创建并切换到新分支
git merge <分支名>                  # 合并分支到当前分支

# ===== GitHub CLI =====
gh repo create <名称> --public      # 创建公开仓库
gh repo create <名称> --private     # 创建私有仓库
gh auth status                      # 查看登录状态
gh repo view --web                  # 在浏览器打开仓库
```

---

## 5. 多仓库管理

### 5.1 目录结构建议

```
C:\Users\admin\
├── claude-code-output\           ← 默认主仓库（各种小项目混放）
│   ├── python-scripts\
│   ├── web-components\
│   └── ...
├── my-api-server\                ← 独立大项目的专属仓库
│   └── ...
└── data-analysis-tool\           ← 另一个独立项目
    └── ...
```

### 5.2 创建独立项目仓库

```powershell
# 1. 创建目录
mkdir C:\Users\admin\my-new-project
cd C:\Users\admin\my-new-project

# 2. 初始化
git init
git branch -M main

# 3. 在 GitHub 上创建同名仓库
gh repo create Adalind63/my-new-project --public

# 4. 关联远程（SSH 自动生效）
git remote add origin git@github.com:Adalind63/my-new-project.git

# 5. 首次推送
echo "# My New Project" > README.md
git add -A
git commit -m "Initial commit"
git push -u origin main
```

---

## 6. 最佳实践

### 6.1 Commit 信息规范

推荐使用约定式提交格式：

```
feat: 添加用户登录功能
fix: 修复日期格式错误
docs: 更新 README 使用说明
refactor: 重构数据库连接模块
chore: 更新 .gitignore
```

### 6.2 合理使用 .gitignore

当前仓库已配置 `.gitignore`，排除以下内容：
- `node_modules/`、`__pycache__/` 等依赖目录
- `.env` 等敏感配置文件
- `dist/`、`build/` 等构建产物
- IDE 配置文件

**需要添加新的忽略规则时，直接说：**

> 👤 你：帮我把 `*.db` 文件加到 .gitignore

### 6.3 不要提交的内容

| 类型 | 原因 |
|------|------|
| API Key / Token / 密码 | 安全风险 |
| `.env` 文件 | 含敏感配置 |
| `node_modules/` | 太大，可用 `package.json` 还原 |
| `.exe` / `.dll` 文件 | 二进制文件不适合版本控制 |
| 日志文件 (`*.log`) | 无版本价值 |

### 6.4 推送频率

- **建议**：每个功能点完成后提交一次
- **避免**：攒了几十个文件一次性提交（难以追溯变更历史）
- **典型节奏**：对话结束前统一提交当天产出

---

## 7. 故障排除

### 7.1 推送失败

```powershell
# 检查 SSH 连接
ssh -T git@github.com
# 预期输出: Hi Adalind63! You've successfully authenticated...

# 检查远程地址
git remote -v
# 应该是: origin  git@github.com:Adalind63/claude-code-output.git

# 如果不是 SSH 地址，修改它：
git remote set-url origin git@github.com:Adalind63/claude-code-output.git
```

### 7.2 gh CLI 找不到

```powershell
# 添加 gh 到当前会话的 PATH
$env:PATH = "$env:PATH;$env:LOCALAPPDATA\GitHubCLI\bin"

# 或使用完整路径
& "$env:LOCALAPPDATA\GitHubCLI\bin\gh.exe" auth status
```

### 7.3 Token 过期

GitHub Personal Access Token 过期后，gh CLI 的 API 功能会失效：

```powershell
# 重新生成 token 后，更新环境变量
[Environment]::SetEnvironmentVariable("GH_TOKEN", "新的token", "User")

# 或重新登录
gh auth login --web
```

### 7.4 SSH Key 丢失

如果重装系统或换了电脑：

```powershell
# 1. 生成新 key
ssh-keygen -t ed25519 -C "2212777179@qq.com"

# 2. 复制公钥
Get-Content ~/.ssh/id_ed25519.pub

# 3. 到 https://github.com/settings/ssh/new 添加公钥
# 4. 测试连接
ssh -T git@github.com
```

---

## 📌 快速参考卡片

```
┌─────────────────────────────────────────────────────────┐
│               Claude Code × GitHub 速查                  │
├─────────────────────────────────────────────────────────┤
│  本地仓库    C:\Users\admin\claude-code-output           │
│  远程仓库    github.com/Adalind63/claude-code-output     │
│  传输协议    SSH (自动从 HTTPS 重定向)                    │
│  GitHub CLI  C:\Users\admin\AppData\Local\GitHubCLI\bin  │
│                                                         │
│  对 Claude 说：                                          │
│  • "提交并推送"        → git add -A; commit; push        │
│  • "推送到 GitHub"     → git push                        │
│  • "创建新仓库 XXX"    → gh repo create + 初始化         │
│  • "查看提交历史"      → git log                         │
│  • "撤销修改"          → git checkout -- <file>          │
└─────────────────────────────────────────────────────────┘
```

---

*指南生成于 2026-06-02 · 由 Claude Code 创建*
