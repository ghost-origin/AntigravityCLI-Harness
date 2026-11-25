(function () {
  var feedEl = document.getElementById('feed');
  var statusDot = document.getElementById('statusDot');
  var convDropdown = document.getElementById('convDropdown');
  var convTrigger = document.getElementById('convTrigger');
  var convTriggerText = document.getElementById('convTriggerText');
  var convMenu = document.getElementById('convMenu');
  var convCtxMenu = document.getElementById('convCtxMenu');
  var btnFilter = document.getElementById('btnFilter');
  var btnAutoScroll = document.getElementById('btnAutoScroll');
  var btnTheme = document.getElementById('btnTheme');
  var clipBanner = document.getElementById('clipBanner');
  var clipImg = document.getElementById('clipImg');
  var clipName = document.getElementById('clipName');
  var btnClipClear = document.getElementById('btnClipClear');
  var lightbox = document.getElementById('lightbox');
  var lightboxImg = document.getElementById('lightboxImg');
  var lightboxCaption = document.getElementById('lightboxCaption');
  var lightboxClose = document.getElementById('lightboxClose');
  var toastEl = document.getElementById('toast');

  var state = {
    snapshot: null,
    formulasOnly: false,
    autoScroll: true,
    toastTimer: null,
    mermaidSeq: 0,
    menuOpen: false,
    ctxConv: null
  };

  function getTheme() {
    return document.documentElement.getAttribute('data-theme') || 'dark';
  }

  function initMermaid(theme) {
    if (!window.mermaid) return;
    try {
      window.mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'loose',
        theme: theme === 'dark' ? 'dark' : 'default'
      });
    } catch (e) {}
  }

  function renderMermaidBlocks() {
    if (!window.mermaid) return;
    initMermaid(getTheme());
    var nodes = feedEl.querySelectorAll('.mermaid-canvas[data-mermaid-src]');
    nodes.forEach(function (node) {
      var src = node.getAttribute('data-mermaid-src') || '';
      if (!src) return;
      state.mermaidSeq += 1;
      var id = 'agy-mmd-' + state.mermaidSeq;
      window.mermaid.render(id, src).then(function (res) {
        node.innerHTML = res.svg;
      }).catch(function () {
        node.innerHTML = '<pre class="mermaid-fallback"><code>' + window.AgyMathMarkdown.escapeHtml(src) + '</code></pre>';
      });
    });
  }

  function openSvgLightbox(svgEl, caption) {
    if (!svgEl) return;
    var cloned = svgEl.cloneNode(true);
    cloned.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    var bg = getTheme() === 'dark' ? '#151920' : '#ffffff';
    cloned.style.background = bg;
    var xml = new XMLSerializer().serializeToString(cloned);
    var url = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(xml);
    openLightbox(url, caption || 'Mermaid 图表');
  }

  function showToast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.remove('hidden');
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(function () {
      toastEl.classList.add('hidden');
    }, 1800);
  }

  function copyText(text, label) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        showToast(label || '已复制 LaTeX');
      }).catch(function () {
        fallbackCopy(text, label);
      });
    } else {
      fallbackCopy(text, label);
    }
  }

  function fallbackCopy(text, label) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand('copy');
      showToast(label || '已复制 LaTeX');
    } finally {
      document.body.removeChild(ta);
    }
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    btnTheme.textContent = theme === 'dark' ? '浅色' : '深色';
    try { localStorage.setItem('agy-sidebar-theme', theme); } catch (e) {}
  }

  applyTheme((function () {
    try { return localStorage.getItem('agy-sidebar-theme') || 'dark'; } catch (e) { return 'dark'; }
  })());

  btnTheme.addEventListener('click', function () {
    var cur = getTheme();
    applyTheme(cur === 'dark' ? 'light' : 'dark');
    renderFeed();
  });

  btnFilter.addEventListener('click', function () {
    state.formulasOnly = !state.formulasOnly;
    btnFilter.classList.toggle('active', state.formulasOnly);
    btnFilter.textContent = state.formulasOnly ? '仅公式与图表' : '全部对话';
    renderFeed();
  });

  btnAutoScroll.addEventListener('click', function () {
    state.autoScroll = !state.autoScroll;
    btnAutoScroll.classList.toggle('active', state.autoScroll);
    if (state.autoScroll) {
      feedEl.scrollTop = feedEl.scrollHeight;
    }
  });

  feedEl.addEventListener('scroll', function () {
    var nearBottom = feedEl.scrollHeight - feedEl.scrollTop - feedEl.clientHeight < 60;
    if (!nearBottom && state.autoScroll) {
      state.autoScroll = false;
      btnAutoScroll.classList.remove('active');
    }
  });

  function closeMenus() {
    state.menuOpen = false;
    state.ctxConv = null;
    convMenu.classList.add('hidden');
    convCtxMenu.classList.add('hidden');
  }

  function closeCtxMenu() {
    state.ctxConv = null;
    convCtxMenu.classList.add('hidden');
  }

  function selectConversation(convId) {
    fetch('/api/select', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conv_id: convId })
    });
    closeMenus();
  }

  function openConversationInTerminal(conv) {
    if (!conv || !conv.id) return;
    fetch('/api/open-terminal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conv_id: conv.id })
    }).then(function (r) { return r.json(); }).then(function (res) {
      if (res && res.ok) {
        showToast('已在新标签页打开: ' + (conv.title || conv.id.slice(0, 8)));
      } else {
        showToast('打开新标签页失败: ' + ((res && res.error) || '未知错误'));
      }
    }).catch(function () {
      showToast('打开新终端请求失败');
    });
    closeMenus();
  }

  convTrigger.addEventListener('click', function (e) {
    e.stopPropagation();
    closeCtxMenu();
    state.menuOpen = !state.menuOpen;
    convMenu.classList.toggle('hidden', !state.menuOpen);
  });

  document.addEventListener('click', function (e) {
    if (!convDropdown.contains(e.target) && !convCtxMenu.contains(e.target)) {
      closeMenus();
    } else if (!convCtxMenu.contains(e.target)) {
      closeCtxMenu();
    }
  });

  convCtxMenu.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-ctx-action]');
    if (!btn || !state.ctxConv) return;
    var action = btn.getAttribute('data-ctx-action');
    var target = state.ctxConv;
    if (action === 'open-terminal') {
      openConversationInTerminal(target);
    } else if (action === 'select-sidebar') {
      selectConversation(target.id);
    } else if (action === 'copy-id') {
      copyText(target.id, '已复制会话 ID');
      closeCtxMenu();
    }
  });

  btnClipClear.addEventListener('click', function () {
    fetch('/api/clipboard/clear', { method: 'POST' });
    clipBanner.classList.add('hidden');
  });

  function openLightbox(src, caption) {
    lightboxImg.src = src;
    lightboxCaption.textContent = caption || '';
    lightbox.classList.remove('hidden');
  }

  function closeLightbox() {
    lightbox.classList.add('hidden');
    lightboxImg.src = '';
  }

  lightboxClose.addEventListener('click', closeLightbox);
  lightbox.addEventListener('click', function (e) {
    if (e.target === lightbox) closeLightbox();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      closeLightbox();
      closeMenus();
    }
  });

  clipImg.addEventListener('click', function () {
    openLightbox(clipImg.src, clipName.textContent || '剪贴板图片');
  });

  function updateClipboardBanner(meta) {
    if (meta && meta.has_image && meta.url) {
      clipImg.src = meta.url;
      clipName.textContent = meta.name || 'clipboard';
      clipBanner.classList.remove('hidden');
    } else {
      clipBanner.classList.add('hidden');
    }
  }

  function formatShortDate(mtimeSec) {
    if (!mtimeSec) return '';
    try {
      var d = new Date(mtimeSec * 1000);
      var m = String(d.getMonth() + 1).padStart(2, '0');
      var day = String(d.getDate()).padStart(2, '0');
      var hh = String(d.getHours()).padStart(2, '0');
      var mm = String(d.getMinutes()).padStart(2, '0');
      return m + '-' + day + ' ' + hh + ':' + mm;
    } catch (e) {
      return '';
    }
  }

  function showConvCtxMenu(x, y, conv) {
    state.ctxConv = conv;
    convCtxMenu.classList.remove('hidden');
    var mw = convCtxMenu.offsetWidth || 200;
    var mh = convCtxMenu.offsetHeight || 110;
    var left = Math.min(x, window.innerWidth - mw - 8);
    var top = Math.min(y, window.innerHeight - mh - 8);
    convCtxMenu.style.left = Math.max(8, left) + 'px';
    convCtxMenu.style.top = Math.max(8, top) + 'px';
  }

  function updateConversations(snap) {
    var convs = snap.conversations || [];
    var activeObj = null;
    for (var i = 0; i < convs.length; i++) {
      if (convs[i].id === snap.active_conv) {
        activeObj = convs[i];
        break;
      }
    }

    if (snap.auto_follow) {
      var activeLabel = activeObj && activeObj.title ? activeObj.title : '';
      convTriggerText.textContent = activeLabel ? ('自动跟随 · ' + activeLabel) : '自动跟随最新会话';
    } else if (activeObj) {
      convTriggerText.textContent = activeObj.title || activeObj.id.slice(0, 8);
    } else {
      convTriggerText.textContent = snap.active_conv ? snap.active_conv.slice(0, 8) : '选择会话';
    }

    var frag = document.createDocumentFragment();
    var hint = document.createElement('div');
    hint.className = 'conv-menu-hint';
    hint.textContent = '左键切换侧边栏预览 · 右键在新标签页打开会话';
    frag.appendChild(hint);

    var autoBtn = document.createElement('button');
    autoBtn.type = 'button';
    autoBtn.className = 'conv-item' + (snap.auto_follow ? ' selected' : '');
    autoBtn.innerHTML = '<span class="conv-item-title">自动跟随最新会话</span>';
    autoBtn.addEventListener('click', function () { selectConversation('auto'); });
    frag.appendChild(autoBtn);

    var sep = document.createElement('div');
    sep.className = 'conv-sep';
    frag.appendChild(sep);

    convs.forEach(function (c) {
      var btn = document.createElement('button');
      btn.type = 'button';
      var isSelected = (!snap.auto_follow && c.id === snap.active_conv);
      btn.className = 'conv-item' + (isSelected ? ' selected' : '');
      var titleText = c.title || c.id.slice(0, 8);
      var curTag = c.id === snap.active_conv ? '<span class="conv-item-tag">当前</span>' : '';
      var wsLabel = c.workspace_name || c.id.slice(0, 8);
      btn.innerHTML =
        '<span class="conv-item-title">' + window.AgyMathMarkdown.escapeHtml(titleText) + curTag + '</span>' +
        '<span class="conv-item-meta"><span>' + window.AgyMathMarkdown.escapeHtml(wsLabel) + '</span><span>' + formatShortDate(c.mtime) + '</span></span>';
      btn.title = titleText + (c.workspace ? ('\n' + c.workspace) : '');
      btn.addEventListener('click', function () {
        selectConversation(c.id);
      });
      btn.addEventListener('contextmenu', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        showConvCtxMenu(ev.clientX, ev.clientY, c);
      });
      frag.appendChild(btn);
    });

    convMenu.innerHTML = '';
    convMenu.appendChild(frag);
  }

  function formatTime(iso) {
    if (!iso) return '';
    try {
      var d = new Date(iso);
      return d.toLocaleTimeString('zh-CN', { hour12: false });
    } catch (e) {
      return '';
    }
  }

  function renderFeed() {
    var snap = state.snapshot;
    if (!snap || !snap.messages || snap.messages.length === 0) {
      feedEl.innerHTML = '<div class="empty-state">等待 Antigravity CLI 会话输出...</div>';
      return;
    }

    var frag = document.createDocumentFragment();
    var renderedCards = 0;

    snap.messages.forEach(function (msg) {
      var parsed = window.AgyMathMarkdown.renderMarkdownWithMath(msg.content || '');
      var hasMedia = (msg.media && msg.media.length > 0) || /<img\b/i.test(parsed.html) || parsed.mermaidCount > 0;
      if (state.formulasOnly && parsed.mathCount === 0 && !hasMedia) {
        return;
      }

      var card = document.createElement('article');
      card.className = 'card ' + msg.role;

      var head = document.createElement('div');
      head.className = 'card-head';
      var roleLabel = msg.role === 'user' ? '你' : 'Antigravity';
      head.innerHTML =
        '<span><span class="role-badge">' + roleLabel + '</span> · ' + formatTime(msg.created_at) + '</span>' +
        '<button type="button" class="copy-msg-btn" title="复制整条消息的原始 Markdown 与 LaTeX">复制原文</button>';
      head.querySelector('.copy-msg-btn').addEventListener('click', function () {
        copyText(msg.content || '', '已复制整条 Markdown 原文');
      });
      card.appendChild(head);

      var body = document.createElement('div');
      body.className = 'card-body';
      if (state.formulasOnly && parsed.mathItems.length > 0 && parsed.mermaidCount === 0) {
        body.innerHTML = parsed.mathItems.map(function (it) {
          return window.AgyMathMarkdown.renderKatexToken({ tex: it.tex, display: true });
        }).join('');
      } else if (parsed.html) {
        body.innerHTML = parsed.html;
      }
      card.appendChild(body);

      if (msg.media && msg.media.length > 0) {
        var grid = document.createElement('div');
        grid.className = 'media-grid';
        msg.media.forEach(function (m) {
          var item = document.createElement('div');
          item.className = 'media-item';
          var img = document.createElement('img');
          img.src = m.url;
          img.alt = m.name || 'image';
          img.addEventListener('click', function () {
            openLightbox(m.url, m.name || m.uri);
          });
          var cap = document.createElement('div');
          cap.className = 'media-caption';
          cap.textContent = m.name || m.uri;
          item.appendChild(img);
          item.appendChild(cap);
          grid.appendChild(item);
        });
        card.appendChild(grid);
      }

      frag.appendChild(card);
      renderedCards += 1;
    });

    feedEl.innerHTML = '';
    if (renderedCards === 0) {
      feedEl.innerHTML = '<div class="empty-state">当前会话暂无公式或图表</div>';
    } else {
      feedEl.appendChild(frag);
      renderMermaidBlocks();
    }

    if (state.autoScroll) {
      feedEl.scrollTop = feedEl.scrollHeight;
    }
  }

  // Delegated click handlers for formula copy, mermaid actions & inline images
  feedEl.addEventListener('click', function (e) {
    var mmdBtn = e.target.closest('[data-mermaid-action]');
    if (mmdBtn) {
      var mwrap = mmdBtn.closest('.mermaid-block-wrap');
      if (!mwrap) return;
      var action = mmdBtn.getAttribute('data-mermaid-action');
      if (action === 'copy') {
        copyText(mwrap.getAttribute('data-mermaid-src') || '', '已复制 Mermaid 源码');
      } else if (action === 'zoom') {
        openSvgLightbox(mwrap.querySelector('svg'), 'Mermaid 图表');
      }
      return;
    }

    var mmdSvg = e.target.closest('.mermaid-canvas svg');
    if (mmdSvg) {
      openSvgLightbox(mmdSvg, 'Mermaid 图表');
      return;
    }

    var copyBtn = e.target.closest('.math-copy-btn');
    if (copyBtn) {
      var wrap = copyBtn.closest('.math-block-wrap');
      if (!wrap) return;
      var tex = wrap.getAttribute('data-latex') || '';
      var mode = copyBtn.getAttribute('data-copy-mode');
      var out = mode === 'raw' ? tex : '$$\n' + tex + '\n$$';
      copyText(out, mode === 'raw' ? '已复制纯 LaTeX 公式' : '已复制 $$ 公式');
      return;
    }

    var inlineMath = e.target.closest('.math-inline-wrap');
    if (inlineMath) {
      var sel = window.getSelection();
      if (sel && sel.toString().length > 0) return;
      var itex = inlineMath.getAttribute('data-latex') || '';
      var iout = e.altKey ? itex : '$' + itex + '$';
      copyText(iout, e.altKey ? '已复制纯 LaTeX' : '已复制 $...$ 公式');
      return;
    }

    if (e.target.tagName === 'IMG' && e.target.closest('.card-body')) {
      openLightbox(e.target.src, e.target.alt || '');
    }
  });

  function connectSSE() {
    var es = new EventSource('/api/events');
    es.onopen = function () {
      statusDot.classList.remove('offline');
      statusDot.classList.add('online');
    };
    es.addEventListener('update', function (ev) {
      try {
        var snap = JSON.parse(ev.data);
        state.snapshot = snap;
        updateConversations(snap);
        updateClipboardBanner(snap.clipboard);
        renderFeed();
      } catch (e) {}
    });
    es.addEventListener('clipboard', function (ev) {
      try {
        updateClipboardBanner(JSON.parse(ev.data));
      } catch (e) {}
    });
    es.addEventListener('shutdown', function () {
      es.close();
      window.close();
    });
    es.onerror = function () {
      statusDot.classList.remove('online');
      statusDot.classList.add('offline');
    };
  }

  connectSSE();
})();
