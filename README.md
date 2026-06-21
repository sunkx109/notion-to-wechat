# Notion → 微信公众号 自动发布工具

将 Notion 文章导出为微信公众号兼容格式。采用 mdnice 风格渲染引擎（markdown-it + highlight.js + KaTeX + juice CSS Inlining）。

## 快速开始

### 1. 安装依赖

```bash
cd notion-to-wechat

# Python 依赖
pip install -r requirements.txt

# Node.js 渲染引擎
npm install
```

### 2. 获取并配置密钥

#### Notion API Key

1. 打开 [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. 点击 **"新建集成"** → 起名 → 选择工作区 → 提交
3. 复制 **Internal Integration Secret**（以 `secret_` 或 `ntn_` 开头）
4. **给页面授权**：在 Notion 中打开目标页面/数据库 → 右上角 `⋯` → **连接** → 添加你的集成

#### 微信公众号密钥（可选，仅 API 推送需要）

1. 登录 [微信公众平台](https://mp.weixin.qq.com) → 设置与开发 → 基本配置
2. 复制 **AppID** 和 **AppSecret**
3. 将服务器 IP 加入 **IP 白名单**

#### 知乎 Cookie（可选）

1. 浏览器登录 [zhihu.com](https://www.zhihu.com)
2. F12 → Console → 输入 `document.cookie` → 复制结果

### 3. 填写配置

```bash
cp .env.example .env
```

编辑 `.env`：

```ini
NOTION_API_KEY=ntn_xxxxxxxxxxxx
WECHAT_APP_ID=wxXXXXXXXXXXXXXXXX      # 可选
WECHAT_APP_SECRET=xxxxxxxxxxxxxxxx     # 可选
ZHIHU_COOKIE='d_c0="..."; ...'        # 可选
NOTION_DATABASE_ID=xxx                # auto 模式需要
```

### 4. 配置数据库字段映射（auto 模式）

编辑 `config.yaml`，按你的 Notion 数据库实际列名修改：

```yaml
field_mapping:
  title: "Title"         # 标题列名
  status: "Status"       # 发布状态列名
  pending: "待发布"       # 待发布状态值
  published: "已发布"     # 已发布状态值
```

### 5. 获取 Notion 页面 ID

`notion-page-id` 就是你 Notion 文章的唯一标识符，从浏览器地址栏即可获取。

**方法：在浏览器中打开你的 Notion 页面，看地址栏 URL：**

```
https://www.notion.so/sunkx109/DeepSeek-V4-38324043556480c49193fbe0a6f72c51
                                                    └────────── 32位 ──────────┘
```

**那串 32 位的十六进制字符串就是 page-id**：`38324043556480c49193fbe0a6f72c51`

> 如果 URL 中有 `?` 或 `#`，取它们之前那部分。例如：
> `https://www.notion.so/xxx/My-Page-1a724043556480b2b60dccb29b6878bd?pvs=4`
> → page-id 是 `1a724043556480b2b60dccb29b6878bd`

**数据库 ID 同理**：打开 Notion 数据库，地址栏中那串 32 位字符串就是 `database_id`。

---

## 使用

### 导出文章（推荐）

```bash
# <notion-page-id> 替换为你的 32 位页面 ID
python main.py export <notion-page-id>

# 同时打开浏览器预览
python main.py export <notion-page-id> --open
```

执行后会生成两个文件：

| 文件 | 说明 |
|------|------|
| `export_<标题>.md` | Markdown 原文，用于粘贴到 mdnice |
| `export_<标题>.html` | 渲染后的 HTML，用于浏览器复制 |

---

### 发布到微信公众号

#### 方式 A：通过 mdnice 复制（✅ 推荐，100% 可靠）

```
1. 打开 export_<标题>.md
2. 全选复制内容
3. 粘贴到 https://editor.mdnice.com 左侧编辑器
4. 在右侧选择喜欢的主题
5. 点击「复制」按钮
6. 粘贴到微信公众号编辑器 (Ctrl+V / Cmd+V)
```

> 这是最可靠的方式。mdnice 做了大量的微信兼容处理，能保证样式在微信公众号中正确显示。

#### 方式 B：从 HTML 文件复制（⚠️ 部分成功）

```
1. 打开 export_<标题>.html
2. 浏览器中 Ctrl+A 全选 → Ctrl+C 复制
3. 粘贴到微信公众号编辑器
```

> 本方式渲染的 HTML 在浏览器中显示正常，但复制到微信公众号后样式可能丢失。微信
> 编辑器对 HTML 的过滤机制导致部分 CSS 属性被剥离。推荐使用方式 A。

#### 方式 C：API 直接推送（⚠️ 实验性）

```bash
# 推送到微信草稿箱
python main.py publish <notion-page-id>

# 推送到知乎
python main.py publish-zhihu <notion-page-id>

# 同时推送到微信 + 知乎
python main.py publish-all <notion-page-id>
```

> API 推送存在微信后台对 HTML 的过滤问题，样式可能不完整。适合自动化场景，
> 但排版质量不如方式 A。

---

### 其他命令

```bash
# 拉取 Notion 页面，保存为 JSON 或 Markdown
python main.py fetch <page-id>
python main.py fetch <page-id> --format md

# 将 Markdown 转换为 HTML 预览
python main.py convert article.md -o preview.html

# 预览渲染效果（不发布）
python main.py preview <page-id> --open

# 查看微信草稿列表
python main.py list-drafts

# 发布指定草稿
python main.py publish-draft <media_id>

# 验证知乎 Cookie
python main.py zhihu-login

# 自动扫描数据库中的待发布文章
python main.py auto --dry-run     # 先看看有哪些
python main.py auto --preview     # 预览第一篇后确认
```

---

### 全自动脚本

```bash
# 预览模式
python auto_publish_all.py --dry-run

# 发布前预览第一篇确认
python auto_publish_all.py --preview

# 全自动发布
python auto_publish_all.py
```

---

### 定时自动化

```bash
# crontab -e  每 30 分钟检查一次
*/30 * * * * cd /path/to/notion-to-wechat && python auto_publish_all.py >> logs/auto.log 2>&1
```

---

## 渲染特性

| 特性 | 说明 |
|------|------|
| 代码高亮 | highlight.js (atom-one-dark 主题)，支持 40+ 语言 |
| 数学公式 | KaTeX 服务端渲染为 HTML+CSS |
| 表格 | Markdown 表格完整支持 |
| 图片 | 保留 Notion 原始链接（微信发布需手动上传） |
| 主题 | 黑标题 + 天蓝链接 + 灰引用，匹配 mdnice 经典风格 |

## 支持的 Notion Block 类型

段落 / 标题 H1-H4 / 无序列表 / 有序列表 / 待办 / 引用 / Callout / 代码块 / 分割线 / 表格 / 图片 / 书签 / 文件 / 视频 / 公式 / Toggle / 分栏

## 项目结构

```
notion-to-wechat/
├── main.py                  # CLI 入口
├── auto_publish_all.py      # 全自动发布脚本
├── config.yaml              # 配置文件
├── .env                     # 密钥（不提交 git）
├── package.json             # Node.js 渲染引擎依赖
└── src/
    ├── notion_client.py     # Notion API
    ├── notion2md.py         # Notion blocks → Markdown
    ├── renderer.js          # mdnice 风格渲染引擎
    ├── renderer_bridge.py   # Python ↔ Node.js 桥接
    ├── wechat_client.py     # 微信 API
    ├── zhihu_client.py      # 知乎 API
    ├── publisher.py         # 多平台发布编排
    └── converter.py         # 旧版转换器（保留）
```
