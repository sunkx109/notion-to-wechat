# Notion → 微信公众号 全自动发布

通过 mdnice.com 渲染引擎，将 Notion 文章一键发布到微信公众号草稿箱。

## 快速开始

### 1. 安装依赖

```bash
pip install -r notion-publisher/requirements.txt
python -m playwright install chromium
```

### 2. 配置密钥

创建 `.env` 文件，填入凭证：

```ini
NOTION_API_KEY=ntn_xxxxxxxxxxxx
WECHAT_APP_ID=wxXXXXXXXXXXXXXXXX
WECHAT_APP_SECRET=xxxxxxxxxxxxxxxx
```

### 3. 一键发布

直接粘贴 Notion 分享链接即可，标题和 page-id 自动提取：

```bash
python notion-publisher/scripts/mdnice_publish.py https://app.notion.com/p/Article-Name-1af24043556480cfad2dc64212758475
```

也兼容旧的手动指定方式：

```bash
python notion-publisher/scripts/mdnice_publish.py "文章标题" <notion-page-id>
```

首次运行时会自动检测登录状态 —— 如果未登录，会弹出扫码提示并循环等待，扫码成功后自动继续发布。

自动完成以下步骤：

```
① Notion API 拉取页面 → 导出 Markdown（图片保存到 mds/<标题>/images/）
② mdnice.com 新建文章、粘贴 Markdown、等待公式/代码渲染
③ 点击 mdnice「复制到微信公众号」
④ 微信编辑器粘贴内容 → 按序上传本地图片替换占位符
⑤ 保存草稿
```

### 4. 审核发布

登录 [mp.weixin.qq.com](https://mp.weixin.qq.com) → 草稿箱 → 检查格式 → 手动点击「发布」。

## 登录流程

首次使用需要分别登录微信公众平台和 mdnice，Cookie 会持久化到本地文件：

| 平台 | Cookie 文件 | 说明 |
|------|-------------|------|
| 微信公众平台 | `wechat_storage.json` | 登录一次，长期有效 |
| mdnice | `mdnice_storage.json` | 登录一次，长期有效 |

**登录是自动触发的** — 运行 `mdnice_publish.py` 时如果检测到未登录，会：

1. 打开登录页面，截图二维码保存到 `login_img/` 目录
2. 提示你扫描二维码，每 10 秒输出一次等待状态
3. 扫码成功后自动保存 Cookie 并继续发布
4. 如果二维码过期（120 秒），自动刷新页面获取新二维码，无需手动干预

也可以手动预登录：

```bash
python notion-publisher/scripts/mdnice_publish.py --login-wechat   # 微信公众平台扫码
python notion-publisher/scripts/mdnice_publish.py --login-mdnice   # mdnice.com 扫码
```

如需重新登录，删除对应的 `*_storage.json` 文件即可。

## 其他用法

```bash
# 已有 Markdown 文件，直接发布
python notion-publisher/scripts/mdnice_publish.py --md-file article.md "标题"

# 仅 mdnice 渲染预览，不发布到微信
python notion-publisher/scripts/mdnice_publish.py --dry-run https://app.notion.com/p/...

# 仅从 Notion 导出 Markdown + 图片到本地
python notion-publisher/scripts/notion_export.py fetch <page-id>
```

## 项目结构

```
notion-to-wechat/
├── README.md
├── login_img/                        # 登录二维码（gitignore）
├── mds/                              # 导出的 Markdown（gitignore）
├── wechat_storage.json               # 微信 Cookie（gitignore）
├── mdnice_storage.json               # mdnice Cookie（gitignore）
└── notion-publisher/                 # Claude Code Skill
    ├── SKILL.md
    ├── config.yaml                   # 平台配置
    ├── requirements.txt              # Python 依赖
    ├── .env.example
    ├── scripts/
    │   ├── mdnice_publish.py         # ★ 主脚本：全自动发布
    │   ├── notion_export.py          # Notion 拉取/导出 CLI
    │   └── install_deps.py           # 依赖自动安装
    ├── src/
    │   ├── notion_client.py          # Notion API 封装
    │   ├── notion2md.py              # Notion blocks → Markdown
    │   ├── wechat_client.py          # 微信 API
    │   └── utils.py                  # 配置加载、日志
    ├── evals/
    │   └── evals.json
    └── references/
        └── wechat_editor.md
```

## 导出目录结构

每次导出会在 `mds/` 下创建以文章标题命名的文件夹：

```
mds/
└── SageAttention_论文学习笔记/
    ├── article.md              # Markdown（图片使用相对路径）
    └── images/
        ├── img_00.png          # Notion 原始图片
        ├── img_01.png
        └── ...
```

## ☕ Buy Me a Coffee

如果这个工具帮你省了排版发布的时间，欢迎请我喝杯咖啡~

<div align="center">
  <img src="imgs/wechat_reward.png" alt="微信赞赏码" width="350">
  <p><sub>微信扫码赞赏</sub></p>
</div>
