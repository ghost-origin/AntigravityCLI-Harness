(function () {
  function escapeHtml(s) {
    return s
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function escapeAttr(s) {
    return escapeHtml(s).replace(/'/g, '&#39;');
  }

  function unescapeHtml(s) {
    return s
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&amp;/g, '&');
  }

  function wrapMermaidBlocks(html) {
    var count = 0;
    var out = html.replace(/<pre><code class="language-mermaid">([\s\S]*?)<\/code><\/pre>/gi, function (_full, inner) {
      var raw = unescapeHtml(inner).trim();
      count += 1;
      var enc = escapeAttr(raw);
      return (
        '<div class="mermaid-block-wrap" data-mermaid-src="' + enc + '">' +
          '<div class="mermaid-block-tools">' +
            '<button type="button" class="math-copy-btn" data-mermaid-action="copy" title="复制 Mermaid 源码">复制源码</button>' +
            '<button type="button" class="math-copy-btn" data-mermaid-action="zoom" title="放大查看图表">放大</button>' +
          '</div>' +
          '<div class="mermaid-canvas" data-mermaid-src="' + enc + '"><span class="mermaid-fallback">正在渲染 Mermaid 图表...</span></div>' +
        '</div>'
      );
    });
    return { html: out, mermaidCount: count };
  }

  function isLocalImagePath(src) {
    if (!src) return false;
    if (/^(https?:|data:|\/api\/)/i.test(src)) return false;
    return /^(file:\/\/\/|[A-Za-z]:[\\/])/i.test(src);
  }

  function rewriteLocalImgSrc(html) {
    return html.replace(/<img\s+([^>]*?)src="([^"]+)"([^>]*)>/gi, function (full, pre, src, post) {
      if (!isLocalImagePath(src)) return full;
      var proxied = '/api/media?path=' + encodeURIComponent(src);
      return '<img ' + pre + 'src="' + proxied + '" data-orig-src="' + escapeAttr(src) + '"' + post + '>';
    });
  }

  function extractMathAndCode(md) {
    var codeHolders = [];
    var mathHolders = [];

    // 1. Protect fenced code blocks
    var text = md.replace(/(^|\n)(```+|~~~+)[^\n]*\n[\s\S]*?\n\2[ \t]*(?=\n|$)/g, function (m) {
      var idx = codeHolders.length;
      codeHolders.push(m);
      return '\u0000CODE' + idx + '\u0000';
    });

    // 2. Protect inline code spans
    text = text.replace(/(`+)([^\n`]*?)\1/g, function (m) {
      var idx = codeHolders.length;
      codeHolders.push(m);
      return '\u0000CODE' + idx + '\u0000';
    });

    // 3. Extract display math $$...$$
    text = text.replace(/\$\$([\s\S]+?)\$\$/g, function (_m, tex) {
      var idx = mathHolders.length;
      mathHolders.push({ tex: tex.trim(), display: true });
      return '\n\n@@AGYMATH_' + idx + '@@\n\n';
    });

    // 4. Extract inline math $...$ (currency-safe: no leading/trailing space, no trailing digit)
    text = text.replace(/(^|[^\\$])\$([^\s$](?:[^$\n]*?[^\s$\\])?)\$(?![0-9$])/g, function (m, pre, tex) {
      if (!tex || /^\d+(?:[.,]\d+)?$/.test(tex)) return m;
      var idx = mathHolders.length;
      mathHolders.push({ tex: tex.trim(), display: false });
      return pre + '@@AGYMATH_' + idx + '@@';
    });

    // 5. Restore protected code spans/blocks before marked parses markdown
    text = text.replace(/\u0000CODE(\d+)\u0000/g, function (_m, i) {
      return codeHolders[Number(i)];
    });

    return { text: text, mathHolders: mathHolders };
  }

  function renderKatexToken(item) {
    var rendered = '';
    try {
      rendered = window.katex.renderToString(item.tex, {
        displayMode: item.display,
        throwOnError: false,
        strict: false,
        output: 'htmlAndMathml'
      });
    } catch (e) {
      rendered = '<code>' + escapeHtml(item.tex) + '</code>';
    }

    var encoded = escapeAttr(item.tex);
    if (item.display) {
      return (
        '<div class="math-block-wrap" data-latex="' + encoded + '" data-display="1">' +
          '<div class="math-block-tools">' +
            '<button type="button" class="math-copy-btn" data-copy-mode="wrapped" title="复制带 $$ 的公式">复制 $$</button>' +
            '<button type="button" class="math-copy-btn" data-copy-mode="raw" title="仅复制纯 LaTeX 源码">纯公式</button>' +
          '</div>' +
          rendered +
        '</div>'
      );
    }
    return (
      '<span class="math-inline-wrap" data-latex="' + encoded + '" data-display="0" title="单击复制 $...$，按住 Alt 单击复制纯公式">' +
        rendered +
      '</span>'
    );
  }

  function renderMarkdownWithMath(md) {
    if (!md) return { html: '', mathCount: 0, mermaidCount: 0, mathItems: [] };
    var extracted = extractMathAndCode(md);
    var html = window.marked.parse(extracted.text, { gfm: true, breaks: true });
    html = rewriteLocalImgSrc(html);
    var mmd = wrapMermaidBlocks(html);
    html = mmd.html;

    html = html.replace(/(?:<p>\s*)?@@AGYMATH_(\d+)@@(?:\s*<\/p>)?/g, function (full, idxStr) {
      var item = extracted.mathHolders[Number(idxStr)];
      if (!item) return full;
      if (item.display) {
        return renderKatexToken(item);
      }
      var hasOpenP = full.indexOf('<p>') === 0;
      var hasCloseP = full.slice(-4) === '</p>';
      return (hasOpenP ? '<p>' : '') + renderKatexToken(item) + (hasCloseP ? '</p>' : '');
    });

    return {
      html: html,
      mathCount: extracted.mathHolders.length,
      mermaidCount: mmd.mermaidCount,
      mathItems: extracted.mathHolders
    };
  }

  window.AgyMathMarkdown = {
    renderMarkdownWithMath: renderMarkdownWithMath,
    renderKatexToken: renderKatexToken,
    escapeHtml: escapeHtml
  };
})();
