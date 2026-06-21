# Notion → 微信公众号 全自动发布

通过 mdnice.com 渲染引擎，将 Notion 文章一键发布到微信公众号草稿箱。同时也是一个 **Claude Code Skill**，安装后可以在 Claude Code 对话中用自然语言直接触发发布。

```
Notion 文章 → Markdown 导出 → mdnice.com 渲染 → 微信公众号草稿箱
```

## 安装为 Claude Code Skill

这个项目本身就是一个 Claude Code Skill。安装后，你可以在 Claude Code 里直接用自然语言触发发布，比如：

> _"帮我把这篇 Notion 文章发到公众号"_

Claude Code 通过扫描 `~/.claude/skills/` 目录来发现 skill —— 只要该目录下的子目录包含 `SKILL.md` 就会被自动识别。

### 方式一：符号链接（推荐）

将 `notion-publisher/` 软链接到 skills 目录，代码留在 git repo 里，修改即时生效：

```bash
# 克隆项目
git clone https://github.com/sunkx109/notion-to-wechat.git ~/notion-to-wechat

# 创建符号链接
ln -s ~/notion-to-wechat/notion-publisher ~/.claude/skills/notion-publisher
```

### 方式二：直接复制

```bash
git clone https://github.com/sunkx109/notion-to-wechat.git ~/notion-to-wechat
cp -r ~/notion-to-wechat/notion-publisher ~/.claude/skills/notion-publisher
```

### 配置权限（重要）

Skill 安装后，Claude Code 运行其中的脚本时会弹出权限确认。建议把相关命令加入全局 allowlist，避免每次都要点确认：

```bash
# 编辑全局配置
vi ~/.claude/settings.json
```

加入以下内容：

```json
{
  "permissions": {
    "allow": [
      "Bash(python:*)",
      "Bash(pip:*)"
    ]
  }
}
```

> 或直接在 Claude Code 对话中运行 `/permissions` 交互式添加。

### 验证安装

在任意目录打开 Claude Code，输入：

```
/skills
```

列表中应该能看到 `notion-publisher`。然后试一句：

> "帮我看看 notion-publisher 的依赖是否都装好了"

Claude 会自动运行 skill 里的 `install_deps.py` 检查环境。

---

## 手动使用（不用 Claude Code）

不依赖 Claude Code，直接命令行使用也可以。

### 1. 安装依赖

```bash
cd ~/notion-to-wechat
pip install -r notion-publisher/requirements.txt
python -m playwright install chromium
```

或者用自带的一键检测脚本：

```bash
python notion-publisher/scripts/install_deps.py
```

### 2. 配置密钥

在项目根目录或 `notion-publisher/` 下创建 `.env` 文件：

```ini
NOTION_API_KEY=ntn_xxxxxxxxxxxx
WECHAT_APP_ID=wxXXXXXXXXXXXXXXXX
WECHAT_APP_SECRET=xxxxxxxxxxxxxxxx
```

> 密钥获取方式：
> - **Notion API Key**：在 [Notion Integrations](https://www.notion.so/my-integrations) 创建，然后连接到你的 Notion 页面
> - **微信公众号**：公众号后台 → 设置与开发 → 基本配置 → AppID / AppSecret

### 3. 一键发布

直接粘贴 Notion 分享链接，标题和 page-id 自动提取：

```bash
python notion-publisher/scripts/mdnice_publish.py https://app.notion.com/p/Article-Name-1af24043556480cfad2dc64212758475
```

也可以手动指定标题和 page-id：

```bash
python notion-publisher/scripts/mdnice_publish.py "文章标题" <notion-page-id>
```

首次运行时会自动检测登录状态 —— 如果未登录，弹出二维码并等待扫码，成功后自动继续。

自动完成的步骤：

```
① Notion API 拉取页面 → 导出 Markdown（图片保存到 mds/<标题>/images/）
② mdnice.com 新建文章、粘贴 Markdown、等待公式/代码渲染
③ 点击 mdnice「复制到微信公众号」
④ 微信编辑器粘贴内容 → 按序上传本地图片替换占位符
⑤ 保存草稿
```

### 4. 审核发布

登录 [mp.weixin.qq.com](https://mp.weixin.qq.com) → 草稿箱 → 检查格式 → 手动点击「发布」。

---

## 登录流程

首次使用需要分别登录微信公众平台和 mdnice，Cookie 会自动持久化：

| 平台 | Cookie 文件 | 说明 |
|------|-------------|------|
| 微信公众平台 | `wechat_storage.json` | 登录一次，长期有效 |
| mdnice | `mdnice_storage.json` | 登录一次，长期有效 |

**登录是自动触发的** —— 如果检测到未登录，脚本会：

1. 打开登录页面，截图二维码保存到 `login_img/` 目录
2. 提示扫码，每 10 秒输出等待状态
3. 扫码成功后自动保存 Cookie 并继续发布
4. 二维码过期（120 秒）后自动刷新获取新码，无需手动干预

也可以手动预登录：

```bash
python notion-publisher/scripts/mdnice_publish.py --login-wechat   # 微信公众平台扫码
python notion-publisher/scripts/mdnice_publish.py --login-mdnice   # mdnice.com 扫码
```

如需重新登录，删除对应的 `*_storage.json` 文件即可。

---

## 其他用法

```bash
# 已有 Markdown 文件，直接发布
python notion-publisher/scripts/mdnice_publish.py --md-file article.md "标题"

# 仅 mdnice 渲染预览，不发布到微信
python notion-publisher/scripts/mdnice_publish.py --dry-run https://app.notion.com/p/...

# 仅从 Notion 导出 Markdown + 图片到本地
python notion-publisher/scripts/notion_export.py fetch <page-id>
```

---

## 项目结构

```
notion-to-wechat/
├── README.md
├── .env                              # 密钥配置（gitignore）
├── login_img/                        # 登录二维码（gitignore）
├── mds/                              # 导出的 Markdown（gitignore）
├── wechat_storage.json               # 微信 Cookie（gitignore）
├── mdnice_storage.json               # mdnice Cookie（gitignore）
└── notion-publisher/                 # ★ Claude Code Skill
    ├── SKILL.md                      # skill 定义（名称、描述、触发词、使用说明）
    ├── config.yaml                   # 平台配置（可被 .env 覆盖）
    ├── requirements.txt              # Python 依赖
    ├── .env.example                  # 环境变量模板
    ├── scripts/
    │   ├── mdnice_publish.py         # ★ 主脚本：全自动发布
    │   ├── notion_export.py          # Notion 拉取/导出 CLI
    │   └── install_deps.py           # 依赖一键检测与安装
    ├── src/
    │   ├── notion_client.py          # Notion API 封装
    │   ├── notion2md.py              # Notion blocks → Markdown
    │   ├── wechat_client.py          # 微信 API
    │   └── utils.py                  # 配置加载、日志
    ├── evals/
    │   └── evals.json                # skill 触发测试用例
    └── references/
        └── wechat_editor.md          # 微信后台编辑器 DOM 结构
```

### 导出目录结构

每次导出会在 `mds/` 下创建以文章标题命名的文件夹：

```
mds/
└── SageAttention_论文学习笔记/
    ├── article.md              # Markdown（图片使用相对路径）
    └── images/
        ├── img_00.png
        ├── img_01.png
        └── ...
```

---

## 常见问题

### Q: 安装 skill 后 Claude Code 识别不到？

确认 `~/.claude/skills/notion-publisher/SKILL.md` 文件存在。如果用的是符号链接，确认源路径没有被删除。运行 `/skills` 查看已注册的 skill 列表。

### Q: Claude 执行脚本时每次都弹权限确认？

需要把 `python` 和 `pip` 加入全局 permissions allowlist，见上方「配置权限」一节。

### Q: Cookie 过期了怎么办？

删除项目根目录下的 `wechat_storage.json` 或 `mdnice_storage.json`，下次运行时会自动触发重新登录。

### Q: mdnice 渲染超时？

脚本内置 60 秒超时重试。如果网络较慢，可以稍后重试。

### Q: 图片不显示？

确保图片已上传到微信 CDN。脚本默认自动处理；如果跳过可以用 `--md-file` 手动指定已处理的 Markdown。

### Q: 微信保存时弹出合规检测？

脚本会自动等待最多 100 秒并点击确认按钮。

---

## ☕ Buy Me a Coffee

如果这个工具帮你省了排版发布的时间，欢迎请我喝杯咖啡~

<div align="center">
  <img src="imgs/wechat_reward.png" alt="微信赞赏码" width="350">
  <p><sub>微信扫码赞赏</sub></p>
</div>
