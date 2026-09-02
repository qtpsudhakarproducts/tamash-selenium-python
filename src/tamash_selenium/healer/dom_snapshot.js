(function () {
  /* Injected by tamash_selenium.healer.dom_snapshot.capture.
     Walks the live DOM and returns a YAML accessibility tree in the exact shape
     durable_locator.parse_aria_ai_tree parses. Every emitted element is stamped
     data-tamash-ref="eN" so an AI-picked [ref=eN] resolves back to a real node via
     [data-tamash-ref='eN']. */
  const MAX_NODES = 1500;
  const REF_ATTR = 'data-tamash-ref';
  let counter = 0;
  const out = [];

  function roleOf(el) {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit.trim().split(/\s+/)[0];
    const tag = el.tagName.toLowerCase();
    switch (tag) {
      case 'a': return el.hasAttribute('href') ? 'link' : 'generic';
      case 'button': return 'button';
      case 'input': {
        const t = (el.getAttribute('type') || 'text').toLowerCase();
        if (t === 'checkbox') return 'checkbox';
        if (t === 'radio') return 'radio';
        if (t === 'button' || t === 'submit' || t === 'reset') return 'button';
        if (t === 'hidden') return 'none';
        return 'textbox';
      }
      case 'textarea': return 'textbox';
      case 'select': return 'combobox';
      case 'img': return 'img';
      case 'h1': case 'h2': case 'h3': case 'h4': case 'h5': case 'h6': return 'heading';
      case 'nav': return 'navigation';
      case 'main': return 'main';
      case 'header': return 'banner';
      case 'footer': return 'contentinfo';
      case 'section': case 'article': return 'region';
      case 'ul': case 'ol': return 'list';
      case 'li': return 'listitem';
      case 'table': return 'table';
      case 'form': return 'form';
      case 'label': return 'text';
      default: return 'generic';
    }
  }

  function accessibleName(el) {
    const al = el.getAttribute('aria-label');
    if (al && al.trim()) return al.trim();
    const lb = el.getAttribute('aria-labelledby');
    if (lb) {
      const parts = lb.split(/\s+/).map(function (id) {
        const t = document.getElementById(id);
        return t ? (t.textContent || '').trim() : '';
      }).filter(Boolean);
      if (parts.length) return parts.join(' ');
    }
    const tag = el.tagName.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') {
      if (el.id) {
        try {
          const forLabel = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
          if (forLabel && forLabel.textContent.trim()) return forLabel.textContent.trim();
        } catch (e) {}
      }
      const wrap = el.closest('label');
      if (wrap && wrap.textContent.trim()) return wrap.textContent.trim();
      const ph = el.getAttribute('placeholder');
      if (ph && ph.trim()) return ph.trim();
      const ti = el.getAttribute('title');
      if (ti && ti.trim()) return ti.trim();
      return '';
    }
    if (tag === 'img') {
      const alt = el.getAttribute('alt');
      return alt ? alt.trim() : '';
    }
    const own = (el.textContent || '').replace(/\s+/g, ' ').trim();
    if (own && own.length <= 120) return own;
    const t = el.getAttribute('title');
    return t && t.trim() ? t.trim() : '';
  }

  function isInteractive(el) {
    const tag = el.tagName.toLowerCase();
    if (['a', 'button', 'input', 'select', 'textarea', 'summary'].indexOf(tag) !== -1) return true;
    const r = el.getAttribute('role');
    return !!r && ['button', 'link', 'checkbox', 'radio', 'combobox', 'textbox', 'tab', 'menuitem', 'option', 'switch'].indexOf(r.trim()) !== -1;
  }

  function visible(el) {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 || r.height > 0;
  }

  function q(s) {
    if (s == null) return null;
    return '"' + String(s).replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, ' ') + '"';
  }

  function boxOf(el) {
    const r = el.getBoundingClientRect();
    const x = Math.round(r.left + window.scrollX);
    const y = Math.round(r.top + window.scrollY);
    return '[box=' + x + ',' + y + ',' + Math.round(r.width) + ',' + Math.round(r.height) + ']';
  }

  function walk(el, depth) {
    if (counter >= MAX_NODES) return;
    const tag = el.tagName ? el.tagName.toLowerCase() : '';
    if (['script', 'style', 'noscript', 'template', 'head', 'meta', 'link', 'br', 'svg', 'path'].indexOf(tag) !== -1) return;
    const interactive = isInteractive(el);
    const vis = visible(el);
    const role = roleOf(el);
    if (role === 'none' || (!vis && !interactive)) {
      for (const c of el.children) walk(c, depth);
      return;
    }
    const ref = 'e' + (++counter);
    try { el.setAttribute(REF_ATTR, ref); } catch (e) {}
    const name = accessibleName(el);
    const indent = '  '.repeat(depth);
    let line = indent + '- ' + role;
    if (name) line += ' ' + q(name);
    line += ' [ref=' + ref + '] ' + boxOf(el);

    const directText = [];
    for (const n of el.childNodes) {
      if (n.nodeType === 3) {
        const t = n.textContent.replace(/\s+/g, ' ').trim();
        if (t && (!name || name.indexOf(t) === -1)) directText.push(t);
      }
    }
    const kids = Array.prototype.slice.call(el.children).filter(function (c) {
      const ct = c.tagName.toLowerCase();
      return ['script', 'style', 'noscript', 'template'].indexOf(ct) === -1;
    });
    if (kids.length || directText.length) {
      out.push(line + ':');
      for (const t of directText) out.push(indent + '  - text: ' + t);
      for (const c of kids) walk(c, depth + 1);
    } else {
      out.push(line);
    }
  }

  const root = document.body || document.documentElement;
  walk(root, 0);
  return out.join('\n');
})();
