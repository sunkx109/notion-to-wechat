# Notion → 微信公众号 全自动发布

通过 mdnice.com 渲染引擎，将 Notion 文章一键发布到微信公众号草稿箱。同时也是一个 **Claude Code Skill**，安装后在对话中用自然语言触发发布。

```
Notion API 拉取 → Markdown 导出 → mdnice 粘贴渲染 → 复制到微信 → 粘贴 + 图片插入 → 保存草稿
```

---

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/sunkx109/notion-to-wechat.git ~/notion-to-wechat
cd ~/notion-to-wechat
```

### 2. 安装依赖

```bash
pip install -r notion-publisher/requirements.txt
python -m playwright install chromium
```

### 3. 配置密钥

在**项目根目录**创建 `.env` 文件：

```bash
cp .env.example .env
# 编辑 .env，填入你的真实密钥
```

```ini
# ~/notion-to-wechat/.env

# Notion API Key: https://www.notion.so/my-integrations → 新建集成
NOTION_API_KEY=ntn_xxxxxxxxxxxx

# 微信公众号: mp.weixin.qq.com → 设置与开发 → 基本配置
WECHAT_APP_ID=wxXXXXXXXXXXXXXXXX
WECHAT_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

> `.env` 已在 `.gitignore` 中，不会被提交到 git。

### 4. 一键发布

```bash
# 直接贴 Notion 分享链接
python notion-publisher/scripts/mdnice_publish.py https://app.notion.com/p/Title-1af24043556480cfad2dc64212758475

# 或 手动指定标题 + page_id
python notion-publisher/scripts/mdnice_publish.py "文章标题" <notion-page-id>
```

首次运行会自动弹出二维码让你扫码登录微信公众平台和 mdnice（Cookie 持久化，后续无需重复）。

### 5. 审核发布

登录 [mp.weixin.qq.com](https://mp.weixin.qq.com) → 草稿箱 → 检查格式 → 手动点击「发布」。

---

## 安装为 Claude Code Skill

这个项目本身就是一个 Claude Code Skill。安装后，在 Claude Code 里直接用自然语言触发：

> _"帮我把这篇 Notion 文章发到公众号"_

### 符号链接安装（推荐）

```bash
git clone https://github.com/sunkx109/notion-to-wechat.git ~/notion-to-wechat
ln -s ~/notion-to-wechat/notion-publisher ~/.claude/skills/notion-publisher
```

> 运行 `/skills` 验证是否识别成功。

---

## 自动完成的步骤

脚本执行时会自动完成以下操作：

| 步骤 | 操作 |
|------|------|
| ① | Notion API 拉取页面 → 导出 Markdown（图片并发下载到 `mds/<标题>/images/`） |
| ② | mdnice.com 新建文章 → `Ctrl+V` 粘贴 Markdown → 等待公式/代码渲染 → 自动保存 |
| ③ | 点击 mdnice 右侧「复制到微信公众号」按钮 |
| ④ | 微信后台新建草稿 → `Ctrl+V` 粘贴内容 → 按序上传本地图片替换占位符 |
| ⑤ | 点击「保存为草稿」 |

---

## 登录流程

首次使用需要分别登录微信公众平台和 mdnice，Cookie 自动持久化到项目根目录：

| 平台 | Cookie 文件 | 说明 |
|------|-------------|------|
| 微信公众平台 | `wechat_storage.json` | 长期有效 |
| mdnice | `mdnice_storage.json` | 长期有效 |

登录是**自动触发**的 —— 检测到未登录时：
1. 打开登录页面，截图二维码到 `login_img/`
2. 扫描二维码（在 VSCode 中打开图片）
3. 扫码成功后自动保存 Cookie 并继续发布
4. 二维码过期自动刷新，无需手动干预

也可以手动预登录：

```bash
python notion-publisher/scripts/mdnice_publish.py --login-wechat
python notion-publisher/scripts/mdnice_publish.py --login-mdnice
```

重新登录：删除对应的 `*_storage.json` 文件即可。

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
├── .env                    # 密钥配置（gitignore，在项目根目录）
├── .env.example            # 密钥配置模板
├── .gitignore
├── README.md
│
├── login_img/              # 登录二维码（gitignore）
├── mds/                    # 导出的 Markdown + 图片（gitignore）
├── wechat_storage.json     # 微信 Cookie（gitignore）
├── mdnice_storage.json     # mdnice Cookie（gitignore）
│
└── notion-publisher/       # ★ Claude Code Skill
    ├── SKILL.md            # skill 定义
    ├── config.yaml         # 平台配置模板（可选，env 优先）
    ├── requirements.txt    # Python 依赖
    ├── scripts/
    │   ├── mdnice_publish.py   # ★ 主脚本：全自动发布
    │   ├── notion_export.py    # Notion 拉取/导出 CLI
    │   └── install_deps.py     # 依赖一键检测与安装
    ├── src/
    │   ├── notion_client.py    # Notion API 封装
    │   ├── notion2md.py        # Notion blocks → Markdown
    │   ├── wechat_client.py    # 微信 API
    │   └── utils.py            # 配置加载、日志
    ├── evals/
    │   └── evals.json
    └── references/
        └── wechat_editor.md    # 微信后台编辑器 DOM 结构
```

### 导出目录结构

```
mds/
└── DeepSeek_V4_inference_代码走读/
    ├── article.md          # Markdown（图片使用相对路径）
    └── images/
        ├── img_00.png
        ├── img_01.png
        └── ...
```

---

## 常见问题

### Q: 未配置 NOTION_API_KEY?

在项目根目录创建 `.env` 文件：`cp .env.example .env`，然后填入密钥。

### Q: Cookie 过期了怎么办？

删除项目根目录下的 `wechat_storage.json` 或 `mdnice_storage.json`，下次运行自动重新登录。

### Q: 图片不显示？

确保图片已上传到微信 CDN。脚本默认自动处理；如果跳过可以用 `--md-file` 手动指定已处理的 Markdown。

### Q: 微信保存时弹出合规检测？

脚本会自动等待并点击确认按钮。

---

## ☕ Buy Me a Coffee

如果这个工具帮你省了排版发布的时间，欢迎请我喝杯咖啡~

<div align="center">
  <img src="imgs/wechat_reward.png" alt="微信赞赏码" width="350">
  <p><sub>微信扫码赞赏</sub></p>
</div>
