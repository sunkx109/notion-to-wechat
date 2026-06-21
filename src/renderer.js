#!/usr/bin/env node
/**
 * mdnice 风格 Markdown → 微信/知乎 HTML 渲染器 v2
 *
 * 修复内容:
 *   1. 嵌入 highlight.js CSS 主题 → 代码高亮生效
 *   2. 集成 KaTeX → 服务端公式渲染为 HTML+CSS
 *   3. 改进主题 CSS → 更接近 mdnice.com 的排版风格
 *
 * 核心管线:
 *   Markdown → markdown-it (+highlight.js +KaTeX) → 主题 CSS → juice Inlining → HTML
 *
 * 用法:
 *   echo "# Hello" | node src/renderer.js --theme orange
 *   node src/renderer.js --theme purple --file article.md --platform zhihu
 */

import MarkdownIt from "markdown-it";
import hljs from "highlight.js";
import juice from "juice";
import katex from "katex";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, "..");

// ============================================================
// 加载 highlight.js & KaTeX CSS（从 node_modules 读取）
// ============================================================
function loadCSS(relativePath) {
  const fullPath = path.join(PROJECT_ROOT, relativePath);
  if (fs.existsSync(fullPath)) {
    return fs.readFileSync(fullPath, "utf-8");
  }
  console.error(`Warning: CSS file not found: ${fullPath}`);
  return "";
}

const HLJS_CSS = loadCSS("node_modules/highlight.js/styles/atom-one-dark.min.css");
const KATEX_CSS = loadCSS("node_modules/katex/dist/katex.min.css");

// ============================================================
// KaTeX 数学公式渲染 — 预处理方式
// ============================================================

/**
 * 在 markdown-it 之前预处理数学公式：
 *   1. $$...$$ (块级) → KaTeX 渲染的 HTML (displayMode)
 *   2. $...$ (行内) → KaTeX 渲染的 HTML (inline)
 *
 * 为什么用预处理而不是 markdown-it 插件:
 *   - 更可靠：不依赖行/块状态机的正确分界
 *   - 避免与 code fence、paragraph 等规则冲突
 *   - 处理跨行公式和与段落文本混排的公式
 */

function preprocessMath(markdown) {
  // ── 先处理块级公式 $$...$$ ──
  // 支持: 单行 $$...$$ 和 多行 $$\n...\n$$
  markdown = markdown.replace(/\$\$([\s\S]*?)\$\$/g, (match, formula) => {
    const trimmed = formula.trim();
    if (!trimmed) return match; // 空的 $$ $$ 保持不变
    try {
      return katex.renderToString(trimmed, {
        displayMode: true,
        throwOnError: false,
        trust: true,
      });
    } catch (e) {
      return `<pre class="math-error">[公式错误: ${escapeHtml(trimmed.slice(0, 80))}${trimmed.length > 80 ? "..." : ""}]</pre>`;
    }
  });

  // ── 再处理行内公式 $...$ ──
  // 排除 $$ 和已经处理的 KaTeX HTML
  // 匹配条件：$ 前不是 $，后面有内容，以单个 $ 结束
  markdown = markdown.replace(/(?<!\$)\$(.+?)\$(?!\$)/g, (match, formula) => {
    if (!formula.trim()) return match; // $ $ 空公式
    try {
      return katex.renderToString(formula.trim(), {
        displayMode: false,
        throwOnError: false,
        trust: true,
      });
    } catch (e) {
      return `<code class="math-error-inline">[Math: ${escapeHtml(formula.slice(0, 40))}...]</code>`;
    }
  });

  return markdown;
}

// markdown-it 中不再需要 math plugin，预处理已处理
function mathPlugin(md) {
  // 空插件占位，保留接口兼容性
}

// ============================================================
// markdown-it 插件加载 (ESM)
// ============================================================
let mdFootnote, mdSub, mdSup, mdMark, mdIns, mdAbbr, mdDeflist, mdTaskLists;

async function loadPlugins() {
  const imports = await Promise.allSettled([
    import("markdown-it-footnote"),
    import("markdown-it-sub"),
    import("markdown-it-sup"),
    import("markdown-it-mark"),
    import("markdown-it-ins"),
    import("markdown-it-abbr"),
    import("markdown-it-deflist"),
    import("markdown-it-task-lists"),
  ]);
  [mdFootnote, mdSub, mdSup, mdMark, mdIns, mdAbbr, mdDeflist, mdTaskLists] =
    imports.map((r) => (r.status === "fulfilled" ? r.value.default : null));
}

// ============================================================
// 代码语法高亮
// ============================================================
function highlightCode(str, lang) {
  if (lang && hljs.getLanguage(lang)) {
    try {
      const result = hljs.highlight(str, { language: lang, ignoreIllegals: true });
      return `<pre class="hljs"><code class="language-${lang}">${result.value}</code></pre>`;
    } catch (e) {
      // fallthrough
    }
  } else if (lang) {
    return `<pre class="hljs"><code class="language-${lang}">${escapeHtml(str)}</code></pre>`;
  }
  try {
    const result = hljs.highlightAuto(str);
    return `<pre class="hljs"><code>${result.value}</code></pre>`;
  } catch (e) {
    return `<pre><code>${escapeHtml(str)}</code></pre>`;
  }
}

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ============================================================
// mdnice 风格主题 CSS — 参考 mdnice.com 的实际样式
// ============================================================

/**
 * 基础主题 (Basic) — 所有主题共享
 * 设计参考 mdnice 的 basic template
 */
/**
 * 基础 CSS + 单一主题 — 匹配 mdnice 风格
 *
 * 特征:
 *   - 标题: 正常黑色 (#222)
 *   - 链接: 天蓝色 (#448aff)
 *   - 代码块: atom-one-dark 背景 + 完整语法高亮
 *   - 公式: KaTeX 服务端渲染
 */
function buildThemeCSS(hljsCSS, rawKatexCSS) {
  // 去掉 KaTeX @font-face（微信不支持，只保留渲染规则）
  const katexCSS = rawKatexCSS.replace(/@font-face\s*\{[^}]*\}/g, "");

  return `
/* === highlight.js 代码高亮 (atom-one-dark) === */
${hljsCSS}

/* === KaTeX 公式样式 (去除 @font-face，微信不兼容) === */
${katexCSS}

/* === 排版样式 — 匹配 mdnice 经典风格 === */
#nice{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Hiragino Sans GB", "Microsoft YaHei", "Helvetica Neue", Helvetica,
    Arial, "Apple Color Emoji", "Segoe UI Emoji", sans-serif;
  font-size: 15px;
  line-height: 1.75;
  color: #333333;
  word-wrap: break-word;
  padding: 10px 2px;
  text-align: justify;
}

/* 标题 — 正常黑色 */
#nice h1, #nice h2, #nice h3, #nice h4, #nice h5, #nice h6 {
  font-weight: 700;
  line-height: 1.35;
  color: #222222;
  margin: 24px 0 12px;
  padding: 0;
}
#nice h1 { font-size: 24px; }
#nice h2 { font-size: 21px; border-bottom: 1px solid #e8e8e8; padding-bottom: 8px; }
#nice h3 { font-size: 19px; }
#nice h4 { font-size: 17px; }

#nice p {
  margin: 10px 0;
  line-height: 1.8;
  letter-spacing: 0.5px;
}

#nice strong { font-weight: 700; color: #222; }
#nice em { font-style: italic; }

/* 链接 — 天蓝色 */
#nice a {
  color: #448aff;
  text-decoration: none;
  border-bottom: 1px solid #bbdefb;
}
#nice a:hover { border-bottom-color: #448aff; }

/* 引用块 */
#nice blockquote {
  padding: 12px 20px;
  margin: 18px 0;
  border-left: 4px solid #e0e0e0;
  border-radius: 0 4px 4px 0;
  background: #f8f9fa;
  color: #666666;
  font-size: 14px;
  line-height: 1.7;
}
#nice blockquote p { margin: 6px 0; }

/* 列表 */
#nice ul, #nice ol {
  padding-left: 24px;
  margin: 10px 0;
}
#nice li { margin: 6px 0; line-height: 1.8; }
#nice ul.task-list { list-style: none; padding-left: 2px; }

/* 行内代码 */
#nice code {
  font-family: "SF Mono", "Fira Code", "Fira Mono", "Roboto Mono",
    Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
  padding: 2px 6px;
  border-radius: 4px;
  background: #f0f5ff;
  color: #0052d9;
}

/* 代码块 */
#nice pre.hljs, #nice pre {
  padding: 16px 20px;
  border-radius: 8px;
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.65;
  margin: 18px 0;
}
#nice pre code {
  font-family: "SF Mono", "Fira Code", "Fira Mono", "Roboto Mono",
    "Source Code Pro", Menlo, Monaco, Consolas, "Courier New", monospace;
  font-size: 13px;
  background: transparent;
  padding: 0;
  border-radius: 0;
  color: inherit;
}

/* 表格 */
#nice table {
  border-collapse: collapse;
  width: 100%;
  margin: 18px 0;
  font-size: 14px;
}
#nice table th, #nice table td {
  border: 1px solid #e0e0e0;
  padding: 10px 14px;
  text-align: left;
}
#nice table th {
  background: #f5f7fa;
  color: #333;
  font-weight: 700;
}

/* 分割线 */
#nice hr {
  border: none;
  height: 1px;
  background: #e8e8e8;
  margin: 28px 0;
}

/* 图片 */
#nice img {
  max-width: 100%;
  height: auto;
  display: block;
  margin: 14px auto;
  border-radius: 4px;
}

/* 脚注 */
#nice.footnotes {
  font-size: 13px;
  color: #888;
  border-top: 1px solid #eee;
  margin-top: 36px;
  padding-top: 14px;
}
#nice.footnotes ol { padding-left: 18px; }

/* 数学公式 */
#nice.math-block { text-align: center; margin: 18px 0; overflow-x: auto; }
#nice.math-inline { display: inline; }
#nice.math-error { color: #e74c3c; background: #fdf0ef; padding: 8px 12px; border-radius: 4px; font-size: 13px; }
`;
}

/**
 * 主题变体 — 参考 mdnice.com 的主题色板
 *
 * 橙心 (orange)：mdnice 最受欢迎的暖色主题
 * 姹紫 (purple)：优雅紫调
 * 绿意 (green)：清新自然绿
 * 科技蓝 (tech-blue)：稳重专业蓝
 * 全栈蓝 (fullstack-blue)：深蓝极客风
 * 红绯 (red)：亮眼红色主题
 * 简约 (simple)：极简灰白
 */
// 单一主题 — 匹配 mdnice 经典风格
// 特征: 黑标题 / 天蓝链接 / atom-one-dark 代码高亮 / KaTeX 公式

// ============================================================
// markdown-it 实例
// ============================================================
function createMarkdownIt() {
  const md = new MarkdownIt({
    html: true,
    breaks: true,
    linkify: true,
    typographer: true,
    highlight: highlightCode,
  });

  // 先加载数学公式插件
  md.use(mathPlugin);

  // 加载其他插件
  if (mdFootnote) md.use(mdFootnote);
  if (mdSub) md.use(mdSub);
  if (mdSup) md.use(mdSup);
  if (mdMark) md.use(mdMark);
  if (mdIns) md.use(mdIns);
  if (mdAbbr) md.use(mdAbbr);
  if (mdDeflist) md.use(mdDeflist);
  if (mdTaskLists) md.use(mdTaskLists, { enabled: true });

  return md;
}

// ============================================================
// 主渲染函数
// ============================================================
function render(markdown, platform = "wechat") {
  const fullCSS = buildThemeCSS(HLJS_CSS, KATEX_CSS);

  // 预处理数学公式（在 markdown-it 之前，避免解析冲突）
  const preprocessedMD = preprocessMath(markdown);

  const md = createMarkdownIt();
  const bodyHTML = md.render(preprocessedMD);

  // 构建完整 HTML
  const fullHTML = `
    <section id="nice">
      ${bodyHTML}
    </section>
    <style>${fullCSS}</style>
  `;

  // juice CSS 内联
  const juiceOpts = {
    inlinePseudoElements: false,
    preserveImportant: true,
    removeStyleTags: platform === "wechat",
    applyStyleTags: true,
    applyWidthAttributes: false,
    applyAttributesTableElements: false,
  };

  const inlined = juice(fullHTML, juiceOpts);

  return inlined;
}

// ============================================================
// CLI
// ============================================================
async function main() {
  await loadPlugins();

  const args = process.argv.slice(2);
  let themeName = "orange";
  let platform = "wechat";
  let inputFile = null;

  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--platform" && args[i + 1]) {
      platform = args[i + 1]; i++;
    } else if (args[i] === "--file" && args[i + 1]) {
      inputFile = args[i + 1]; i++;
    } else if (args[i] === "--help" || args[i] === "-h") {
      console.log(`
mdnice 风格 Markdown → HTML 渲染器 v2
用法: node src/renderer.js [--platform wechat|zhihu|generic] [--file <path>]
`);
      process.exit(0);
    }
  }

  let markdown;
  if (inputFile) {
    markdown = fs.readFileSync(inputFile, "utf-8");
  } else {
    const chunks = [];
    for await (const chunk of process.stdin) { chunks.push(chunk); }
    markdown = Buffer.concat(chunks).toString("utf-8");
  }

  if (!markdown.trim()) { console.error("Error: 输入为空"); process.exit(1); }

  const result = render(markdown, platform);
  process.stdout.write(result);
}

main().catch((err) => {
  console.error("渲染失败:", err.message);
  process.exit(1);
});
