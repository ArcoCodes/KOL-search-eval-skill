# Skill 更新说明

本 skill 仅在用户明确请求 `check update`、`检查更新kol评估skill`、`更新 kol评估skill` 或类似表述时执行更新检查。

## 目标

- 保持日常 KOL 工作流的快速运行，不依赖网络。
- 未经用户明确同意，不更改已安装的 skill。
- 通过比较版本文件实现确定性的版本检查，而非比较代码本身。

## 版本来源

`VERSION` 文件应包含一个 SemVer 格式的版本号：

```text
0.1.0
```

每次需要通知用户的发布都必须更新 `VERSION`。如果代码有变更但 `VERSION` 未变，`check update` 应报告无更新。

## 检查更新流程

当用户请求检查更新时：

1. 读取已安装 skill 目录下的本地 `VERSION`。
2. 从 GitHub raw content 获取远程 `VERSION`。
3. 去除空白字符后进行精确字符串比较。
4. 返回以下结果之一：
   - `已是最新版本`
   - `有可用更新`
   - `无法检查更新`

除非用户主动要求更新，或用户在看到可用版本后确认更新，否则不要提示更新。

网络故障、远程文件缺失、私有仓库认证失败或版本号格式异常等情况不应阻塞正常的 skill 使用。简要报告问题即可。

## 更新流程

当用户明确要求更新时：

1. 先检查远程版本。
2. 如果本地和远程版本一致，告知已是最新版本。
3. 如果有可用更新，在修改文件前征求用户确认。
4. 备份当前已安装的 skill 目录。
5. 从 GitHub 下载指定 ref 的 skill 目录。
6. 用下载的版本替换已安装的 skill 目录。
7. 告知用户更新将在下一轮对话中生效。

不得静默覆盖本地更改。如果本地文件被修改过，或 skill 目录是一个包含未提交更改的 git worktree，应停止并询问用户后再继续。

## 建议命令

仅在全新安装时使用现有的 skill 安装器。由于安装器会在目标目录已存在时中止，更新需要采用备份并替换的工作流。

检查示例：

```bash
LOCAL_VERSION="$(tr -d '[:space:]' < "$CLAUDE_SKILL_DIR/VERSION")"
curl -fsSL "https://raw.githubusercontent.com/<owner>/<repo>/<ref>/<path-to-skill>/VERSION"
```

重新安装目标示例：

```bash
python3 /Users/l13/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo <owner>/<repo> \
  --path <path-to-skill> \
  --ref <ref> \
  --dest <temporary-destination>
```

仅在用户确认后，才备份并替换已安装的 skill 目录。

## 推荐的用户体验

`check update` 应简洁回复：

```text
当前版本：0.1.0
最新版本：0.1.1
有可用更新。需要安装时请说"更新这个 skill"。
```

`update` 完成后应回复：

```text
已从 0.1.0 更新至 0.1.1。新版本将在下一轮对话中生效。
备份路径：<backup path>
```

