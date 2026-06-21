# 微信公众号后台编辑器结构（2026 新版）

## 页面结构

微信公众平台文章编辑器页面 URL 格式：
```
https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit_v2&action=edit&isNew=1&type=77&lang=zh_CN&token={token}
```

## DOM 结构

新编辑器基于 ProseMirror，分为标题和正文两个可编辑区域。

### 标题区域

```css
.ProseMirror[contenteditable="true"]  /* 第 0 个 */
```

- 类型：contenteditable div
- 内容：纯文本，不包含任何 HTML 标签
- 操作：设置 `textContent` 并触发 `input` 事件

### 正文区域

```css
.ProseMirror[contenteditable="true"]  /* 第 1 个 */
```

- 类型：contenteditable div
- 内容：富文本 HTML（从 mdnice 粘贴）
- 支持代码块 (`<pre>`)、图片 (`<img>`)、表格等

### 图片上传

```css
input[type="file"][accept*="image"]
```

- 通过 file input 直接上传本地图片
- 编辑器会自动在光标位置插入图片
- 无需使用微信素材管理接口

### 保存按钮

```css
button:has-text("保存为草稿")
```

### 合规检测弹窗

保存时会自动弹出，需点击以下任一按钮确认：
- `button:has-text("仍要保存")`
- `button:has-text("确定")`
- `button:has-text("我知道了")`
- `button:has-text("继续")`
- `button:has-text("关闭")`

## 与旧版编辑器的区别

| 项目 | 旧版 | 新版 |
|------|------|------|
| 编辑器 | iframe 内嵌 | ProseMirror（无 iframe） |
| 标题 | `#title` textarea | 第 0 个 ProseMirror |
| 正文 | `#ueditor_0` iframe | 第 1 个 ProseMirror |
| 图片 | 素材管理 API | file input 直接上传 |
| 选择器 | ID 选择器 | contenteditable 属性 + nth() |
