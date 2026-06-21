---
name: notion-publisher
description: 全自动将 Notion 文章发布到微信公众号。当用户提到"发布 Notion 文章"、"发公众号"、"推送到微信"、"notion publish"、"文章排版发布"、"一键发布"时，必须使用此 skill。核心流程：Notion 导出 Markdown → mdnice.com 渲染（公式/代码/排版）→ 复制到微信公众号 → 保存草稿。
compatibility: 需要 Playwright + Chromium, Python 3.10+, Node.js
---

# Notion Publisher — 全自动发布到微信公众号

全自动流程：

```
Notion 文章 → Markdown 导出 → mdnice.com 渲染 → 复制 → 微信公众号粘贴 → 保存草稿
```

## 前置条件

首次使用需要登录两个平台（各只需一次）：

```bash
# 登录微信公众平台
python scripts/mdnice_publish.py --login-wechat

# 登录 mdnice
python scripts/mdnice_publish.py --login-mdnice
```

每次登录会弹出一个二维码截图到项目目录，用户在 VSCode 中打开图片 → 微信扫码 → Cookie 持久化到本地 JSON 文件。

## 发布流程

### 一条命令发布

```bash
# 方式一：直接贴 Notion 链接
python scripts/mdnice_publish.py https://www.notion.so/sunkx109/Title-1af24043556480cfad2dc64212758475

# 方式二：标题 + page_id
python scripts/mdnice_publish.py "文章标题" <notion-page-id>
```

脚本自动完成：
1. 从 Notion API 拉取页面 → 导出 Markdown
2. 图片下载到本地 mds/ 目录
3. mdnice.com 新建文章 → 粘贴 Markdown（图片占位）→ 等待渲染
4. 点击 mdnice 右侧「复制到微信公众号」按钮
5. 微信后台新建文章 → Ctrl+V 粘贴 → 图片自动插入 → 保存草稿

### 已有 Markdown 文件

```bash
python scripts/mdnice_publish.py --md-file article.md "文章标题"
```

### 仅预览（不发布）

```bash
python scripts/mdnice_publish.py --dry-run "文章标题" <notion-page-id>
```

## 用户操作

草稿保存到微信后台后，用户需要：
1. 登录 `mp.weixin.qq.com` → 草稿箱
2. 审核文章格式和内容
3. 手动点击「发布」

## mdnice 编辑器关键元素

| 元素 | 选择器 | 说明 |
|------|--------|------|
| 新建按钮 | `.add-btn` | 左上角 + 按钮 |
| 标题输入 | `.ant-modal input[placeholder="请输入标题"]` | |
| 确认创建 | `.ant-modal button:has-text("新 增")` | |
| 编辑器 | `.CodeMirror` | CodeMirror 实例 |
| 预览区 | `#nice` | 渲染结果 |
| 复制到微信 | `.nice-btn-wechat` | 右侧工具栏第一个按钮 |

## 微信编辑器关键元素（2026 新版）

| 元素 | 选择器 | 说明 |
|------|--------|------|
| 标题 | `.ProseMirror[contenteditable="true"]` 第 0 个 | 无 iframe |
| 正文 | `.ProseMirror[contenteditable="true"]` 第 1 个 | 无 iframe |
| 保存 | `button:has-text("保存为草稿")` | |

## 故障排查

### Cookie 过期
删除对应的 storage JSON 文件，重新运行 `scripts/mdnice_publish.py --login-*` 命令。

### 渲染超时
mdnice 加载较慢时，脚本会自动重试等待最多 60 秒。

### 图片不显示
确保图片已上传到微信 CDN。脚本默认会自动处理，如果跳过可以用 `--md-file` 手动指定已处理的 Markdown。

### 合规检测弹窗
微信保存时会自动弹出合规检测，脚本会等待最多 100 秒并自动点击确认按钮。

## 参考文件
- `references/wechat_editor.md` — 微信后台编辑器 DOM 结构详情
