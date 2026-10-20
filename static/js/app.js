/* ==========================================================================
   CryzonCloud Cpanel — UI interactions
   Lightweight, dependency-free. Safe for WSGI/gunicorn sync workers.
   ========================================================================== */
(function () {
  "use strict";

  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

  /* ---------------------------------------------------------------------
     Sidebar (mobile)
     --------------------------------------------------------------------- */
  function initSidebar() {
    const toggle = $(".menu-toggle");
    const sidebar = $(".sidebar");
    if (!toggle || !sidebar) return;
    let overlay = $(".sidebar-overlay");
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.className = "sidebar-overlay";
      document.body.appendChild(overlay);
    }
    const close = () => { sidebar.classList.remove("open"); overlay.classList.remove("show"); };
    toggle.addEventListener("click", () => {
      sidebar.classList.toggle("open");
      overlay.classList.toggle("show");
    });
    overlay.addEventListener("click", close);
    $$(".nav-item", sidebar).forEach((a) => a.addEventListener("click", () => { if (window.innerWidth <= 900) close(); }));
  }

  /* ---------------------------------------------------------------------
     Animated number counters
     --------------------------------------------------------------------- */
  function animateCount(el) {
    const target = parseFloat(el.dataset.count);
    if (isNaN(target)) return;
    const dur = 1100;
    const start = performance.now();
    const decimals = (el.dataset.count.split(".")[1] || "").length;
    function step(now) {
      const p = Math.min((now - start) / dur, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      const val = target * eased;
      el.textContent = decimals ? val.toFixed(decimals) : Math.round(val).toLocaleString();
      if (p < 1) requestAnimationFrame(step);
      else el.textContent = decimals ? target.toFixed(decimals) : target.toLocaleString();
    }
    requestAnimationFrame(step);
  }

  function initCounters() {
    const els = $$("[data-count]");
    if (!els.length) return;
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) { animateCount(e.target); io.unobserve(e.target); }
      });
    }, { threshold: 0.2 });
    els.forEach((el) => io.observe(el));
  }

  /* ---------------------------------------------------------------------
     Reveal-on-scroll (staggered)
     --------------------------------------------------------------------- */
  function initReveal() {
    const els = $$(".reveal");
    if (!els.length) return;
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e, i) => {
        if (e.isIntersecting) {
          setTimeout(() => e.target.classList.add("in"), i * 60);
          io.unobserve(e.target);
        }
      });
    }, { threshold: 0.08 });
    els.forEach((el) => io.observe(el));
  }

  /* ---------------------------------------------------------------------
     Progress bars
     --------------------------------------------------------------------- */
  function initProgress() {
    $$(".progress .bar[data-pct]").forEach((bar) => {
      const pct = Math.max(0, Math.min(100, parseFloat(bar.dataset.pct) || 0));
      requestAnimationFrame(() => { bar.style.width = pct + "%"; });
      const wrap = bar.closest(".progress");
      if (wrap) {
        wrap.classList.toggle("warn", pct >= 75 && pct < 90);
        wrap.classList.toggle("danger", pct >= 90);
      }
    });
  }

  /* ---------------------------------------------------------------------
     Flash / toast auto-dismiss
     --------------------------------------------------------------------- */
  function initFlash() {
    $$(".flash").forEach((f) => {
      const close = $(".f-close", f);
      const dismiss = () => {
        f.classList.add("out");
        setTimeout(() => f.remove(), 400);
      };
      if (close) close.addEventListener("click", dismiss);
      setTimeout(dismiss, 5200);
    });
  }

  /* ---------------------------------------------------------------------
     Modals — [data-modal-open="id"], [data-modal-close]
     --------------------------------------------------------------------- */
  function openModal(id) {
    const m = document.getElementById(id);
    if (!m) return;
    m.classList.add("open");
    document.body.style.overflow = "hidden";
  }
  function closeModal(m) {
    m.classList.remove("open");
    document.body.style.overflow = "";
  }
  function initModals() {
    $$("[data-modal-open]").forEach((btn) =>
      btn.addEventListener("click", (e) => { e.preventDefault(); openModal(btn.dataset.modalOpen); })
    );
    $$(".modal-backdrop").forEach((bd) => {
      bd.addEventListener("click", (e) => { if (e.target === bd) closeModal(bd); });
      $$("[data-modal-close]", bd).forEach((b) => b.addEventListener("click", () => closeModal(bd)));
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") $$(".modal-backdrop.open").forEach(closeModal);
    });
  }

  /* ---------------------------------------------------------------------
     Tabs — [data-tabs] container with [data-tab] buttons + [data-panel]
     --------------------------------------------------------------------- */
  function initTabs() {
    $$("[data-tabs]").forEach((group) => {
      const btns = $$("[data-tab]", group);
      btns.forEach((btn) => {
        btn.addEventListener("click", () => {
          btns.forEach((b) => b.classList.remove("active"));
          btn.classList.add("active");
          const scope = group.dataset.tabs;
          $$(`[data-panel][data-scope="${scope}"]`).forEach((p) => {
            p.classList.toggle("hidden", p.dataset.panel !== btn.dataset.tab);
          });
        });
      });
    });
  }

  /* ---------------------------------------------------------------------
     Permission matrix helpers (select all / group toggle)
     --------------------------------------------------------------------- */
  function initPermMatrix() {
    $$("[data-perm-toggle-all]").forEach((master) => {
      master.addEventListener("change", () => {
        const scope = master.closest("[data-perm-scope]") || document;
        $$('input[name="permissions"]', scope).forEach((c) => { c.checked = master.checked; });
        updatePermCounts(scope);
      });
    });
    $$(".perm-group-head").forEach((head) => {
      head.addEventListener("click", (e) => {
        if (e.target.closest("input")) return;
        head.closest(".perm-group").classList.toggle("collapsed");
      });
    });
    $$('input[name="permissions"]').forEach((c) => c.addEventListener("change", () => updatePermCounts(c.closest("[data-perm-scope]") || document)));
    $$("[data-perm-scope]").forEach((s) => updatePermCounts(s));
  }
  function updatePermCounts(scope) {
    scope = scope || document;
    $$("[data-perm-group]", scope).forEach((grp) => {
      const total = $$('input[name="permissions"]', grp).length;
      const on = $$('input[name="permissions"]:checked', grp).length;
      const badge = $("[data-perm-count]", grp);
      if (badge) badge.textContent = on + "/" + total;
    });
    const all = $$('input[name="permissions"]', scope);
    const checked = $$('input[name="permissions"]:checked', scope);
    const counter = $("[data-perm-total]");
    if (counter) counter.textContent = checked.length + " selected";
  }

  /* ---------------------------------------------------------------------
     Notification polling
     --------------------------------------------------------------------- */
  function initNotifications() {
    const bell = $("[data-notif-bell]");
    if (!bell) return;
    const dot = $(".dot", bell);
    const list = $("[data-notif-list]");
    let open = false;

    async function refresh() {
      try {
        const res = await fetch("/api/notifications", { headers: { "X-Requested-With": "fetch" } });
        if (!res.ok) return;
        const data = await res.json();
        if (dot) dot.style.display = data.unread > 0 ? "block" : "none";
        if (list) {
          list.innerHTML = data.items.length
            ? data.items.map((n) => `
              <div class="notif-item">
                <div class="ni-ico ${n.level}"></div>
                <div>
                  <div class="ni-title">${escapeHtml(n.title)}</div>
                  <div class="ni-msg">${escapeHtml(n.message || "")}</div>
                </div>
              </div>`).join("")
            : '<div class="muted text-sm" style="padding:18px;text-align:center">No notifications yet</div>';
        }
      } catch (e) { /* offline — ignore */ }
    }

    bell.addEventListener("click", async (e) => {
      e.stopPropagation();
      const panel = $("[data-notif-panel]");
      if (!panel) return;
      open = !open;
      panel.classList.toggle("open", open);
      if (open) {
        await refresh();
        try { await fetch("/api/notifications/read", { method: "POST" }); } catch (err) {}
        if (dot) dot.style.display = "none";
      }
    });
    document.addEventListener("click", () => {
      const panel = $("[data-notif-panel]");
      if (panel && open) { panel.classList.remove("open"); open = false; }
    });
    refresh();
    setInterval(refresh, 30000);
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  /* ---------------------------------------------------------------------
     Live stat refresh on dashboards (elements with data-live-stat)
     --------------------------------------------------------------------- */
  function initLiveStats() {
    const nodes = $$("[data-live-stat]");
    if (!nodes.length) return;
    async function tick() {
      try {
        const res = await fetch("/api/stats");
        if (!res.ok) return;
        const data = await res.json();
        nodes.forEach((el) => {
          const key = el.dataset.liveStat;
          if (data[key] !== undefined) el.textContent = data[key];
        });
      } catch (e) { /* ignore */ }
    }
    setInterval(tick, 15000);
  }

  /* ---------------------------------------------------------------------
     Confirm forms — [data-confirm]
     --------------------------------------------------------------------- */
  function initConfirm() {
    $$("form[data-confirm]").forEach((f) => {
      f.addEventListener("submit", (e) => {
        if (!window.confirm(f.dataset.confirm)) e.preventDefault();
      });
    });
  }

  /* ---------------------------------------------------------------------
     Copy to clipboard — [data-copy]
     --------------------------------------------------------------------- */
  function initCopy() {
    $$("[data-copy]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const val = btn.dataset.copy;
        try {
          await navigator.clipboard.writeText(val);
          const old = btn.innerHTML;
          btn.innerHTML = "Copied!";
          setTimeout(() => { btn.innerHTML = old; }, 1400);
        } catch (e) {}
      });
    });
  }

  /* ---------------------------------------------------------------------
     Ripple effect on buttons
     --------------------------------------------------------------------- */
  function initRipple() {
    document.addEventListener("click", (e) => {
      const btn = e.target.closest(".btn");
      if (!btn) return;
      const r = document.createElement("span");
      const rect = btn.getBoundingClientRect();
      const size = Math.max(rect.width, rect.height);
      r.style.cssText = `position:absolute;border-radius:50%;pointer-events:none;background:rgba(255,255,255,0.35);width:${size}px;height:${size}px;left:${e.clientX - rect.left - size / 2}px;top:${e.clientY - rect.top - size / 2}px;transform:scale(0);opacity:0.7;transition:transform .55s ease,opacity .55s ease;`;
      btn.appendChild(r);
      requestAnimationFrame(() => { r.style.transform = "scale(2.4)"; r.style.opacity = "0"; });
      setTimeout(() => r.remove(), 600);
    });
  }

  /* ---------------------------------------------------------------------
     Boot
     --------------------------------------------------------------------- */
  document.addEventListener("DOMContentLoaded", () => {
    initSidebar();
    initCounters();
    initReveal();
    initProgress();
    initFlash();
    initModals();
    initTabs();
    initPermMatrix();
    initNotifications();
    initLiveStats();
    initConfirm();
    initCopy();
    initRipple();
  });

  window.Cryzon = { openModal, closeModal, escapeHtml };
})();
