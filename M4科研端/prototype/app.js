(() => {
  "use strict";

  const runtimeProfiles = {
    FULL: {
      label: "完整在线",
      badge: "完整能力",
      tone: "success",
      description: "后端、星辰工作流、Lean 4 与外部学术源均可用。",
      capabilities_used: ["research-api", "xingchen-workflow", "lean4-backend", "external-sources"],
      missing_capabilities: []
    },
    LOCAL_ENGINE: {
      label: "本地引擎",
      badge: "受控降级",
      tone: "warning",
      description: "由本地服务完成核心处理；外部检索与部分工作流暂不可用。",
      capabilities_used: ["local-engine", "lean4-local-service", "local-index"],
      missing_capabilities: ["xingchen-workflow", "external-sources"]
    },
    BROWSER_LOCAL: {
      label: "浏览器本地",
      badge: "离线草稿",
      tone: "warning",
      description: "仅保存草稿、整理证据和导出；Lean 构建标记为 formal_pending。",
      capabilities_used: ["indexeddb", "browser-search", "local-export"],
      missing_capabilities: ["research-api", "lean4-backend", "xingchen-workflow", "external-sources"]
    },
    UNAVAILABLE: {
      label: "能力不可用",
      badge: "只读保护",
      tone: "danger",
      description: "执行能力不可用；现有项目、证据与运行记录仍可查看和导出。",
      capabilities_used: ["cached-snapshot"],
      missing_capabilities: ["research-api", "lean4-backend", "xingchen-workflow", "external-sources", "local-engine"]
    }
  };

  const state = {
    view: "dashboard",
    runtime: "FULL",
    leanTimers: [],
    leanRunning: false
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  function toast(message, tone = "info") {
    const region = $("#toast-region");
    if (!region) return;
    const item = document.createElement("div");
    item.className = `toast toast-${tone}`;
    item.setAttribute("role", "status");
    item.textContent = message;
    region.appendChild(item);
    requestAnimationFrame(() => item.classList.add("is-visible"));
    window.setTimeout(() => {
      item.classList.remove("is-visible");
      window.setTimeout(() => item.remove(), 220);
    }, 2800);
  }

  function navigate(viewId) {
    const target = $(`[data-view="${viewId}"]`);
    if (!target) return;
    state.view = viewId;
    $$('[data-view]').forEach((view) => view.classList.toggle("is-active", view === target));
    $$('[data-nav]').forEach((button) => {
      const selected = button.dataset.nav === viewId;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-current", selected ? "page" : "false");
    });
    const viewTitle = target.dataset.title || $("h1", target)?.textContent || "科研工作台";
    document.title = `${viewTitle} · Math.Arena Research`;
    target.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function setRuntimeMode(mode, announce = true) {
    const profile = runtimeProfiles[mode];
    if (!profile) return;
    state.runtime = mode;
    try { localStorage.setItem("m4-research-runtime", mode); } catch (_) { /* private mode */ }

    document.body.dataset.runtime = mode;
    document.body.classList.remove("mode-full", "mode-local-engine", "mode-browser-local", "mode-unavailable");
    document.body.classList.add(`mode-${mode.toLowerCase().replace("_", "-")}`);

    const select = $("#runtime-mode");
    if (select) select.value = mode;
    const label = $("#runtime-label");
    if (label) label.textContent = profile.label;
    const description = $("#runtime-description");
    if (description) description.textContent = profile.description;
    const badge = $("#runtime-badge");
    if (badge) {
      badge.textContent = profile.badge;
      badge.dataset.tone = profile.tone;
    }

    $$('[data-requires="execution"]').forEach((control) => {
      control.disabled = mode === "UNAVAILABLE";
      control.title = control.disabled ? "当前处于只读保护模式" : "";
    });
    $$('[data-requires="lean"]').forEach((control) => {
      control.disabled = mode === "BROWSER_LOCAL" || mode === "UNAVAILABLE";
      control.title = control.disabled ? "Lean 4 必须由后端或本地引擎运行" : "";
    });

    const formalStatus = $("#formal-runtime-status");
    if (formalStatus) {
      formalStatus.textContent = mode === "BROWSER_LOCAL" ? "formal_pending · 等待恢复后端构建" :
        mode === "UNAVAILABLE" ? "unavailable · 仅可查看历史结果" : "ready · Lean 4 构建服务可用";
    }
    const leanStatus = $("#lean-status");
    if (leanStatus && !state.leanRunning) {
      leanStatus.textContent = mode === "BROWSER_LOCAL" ? "formal_pending" :
        mode === "UNAVAILABLE" ? "unavailable" : "ready";
    }
    const capabilityUsed = $("#capabilities-used");
    if (capabilityUsed) capabilityUsed.textContent = profile.capabilities_used.join(" · ");
    const capabilityMissing = $("#missing-capabilities");
    if (capabilityMissing) capabilityMissing.textContent = profile.missing_capabilities.length ? profile.missing_capabilities.join(" · ") : "无";

    if (announce) toast(`已切换为“${profile.label}”：${profile.description}`, profile.tone);
  }

  function toggleRunDrawer(force) {
    const drawer = $("#run-drawer");
    if (!drawer) return;
    const willOpen = typeof force === "boolean" ? force : !drawer.classList.contains("is-open");
    drawer.classList.toggle("is-open", willOpen);
    drawer.setAttribute("aria-hidden", String(!willOpen));
    document.body.classList.toggle("drawer-open", willOpen);
  }

  function openModal(type) {
    const dialog = $("#action-modal");
    const title = $("#modal-title");
    const body = $("#modal-body");
    if (!dialog || !title || !body) return;

    const templates = {
      "new-task": ["新建研究任务", `<label class="field">任务名称<input autofocus value="谱方法误差界复核"></label><label class="field">任务类型<select><option>文献调研与证据综合</option><option>数值实验</option><option>Lean 形式化</option><option>论文写作</option></select></label><label class="field">交付目标<textarea>形成可复核证据链、实验记录与阶段性结论。</textarea></label>`],
      import: ["导入研究资料", `<div class="drop-zone"><strong>拖入 PDF、BibTeX、Markdown 或数据文件</strong><span>原文件保留，解析结果写入证据账本</span></div>`],
      assistant: ["研究助理", `<div class="assistant-thread"><p><strong>建议下一步：</strong>补齐定理 2 的反例检索，然后把证据 #E-104 绑定到论断 C-07。</p><label class="field">继续询问<textarea placeholder="描述你要验证的问题…"></textarea></label></div>`],
      capabilities: ["能力与降级说明", `<dl class="capability-list"><dt>capabilities_used</dt><dd id="capabilities-used"></dd><dt>missing_capabilities</dt><dd id="missing-capabilities"></dd></dl><p>所有运行均记录实际使用能力，界面不会把降级结果伪装为完整结果。</p>`],
      evidence: ["证据账本详情", `<p><strong>#E-104 · 谱方法收敛率</strong></p><p>来源：arXiv:2403.01891，第 4 节，命题 2。已绑定论断 C-07 与实验 EXP-12。</p><div class="modal-actions"><button class="button secondary" data-close-modal>关闭</button><button class="button primary" data-toast="已复制可追溯引用">复制引用</button></div>`],
      command: ["快速跳转", `<label class="field">搜索功能<input autofocus id="command-input" placeholder="输入：Lean、文献、评审…"></label><div class="command-results"><button data-target-view="verify">证据验证</button><button data-target-view="formalize">Lean 4 形式化工作台</button><button data-target-view="review">协作评审</button></div>`],
      project: ["切换研究项目", `<div class="project-list"><button data-toast="已切换至：谱方法可信计算">谱方法可信计算 <span>当前</span></button><button data-toast="已切换至：组合恒等式形式化">组合恒等式形式化</button><button data-toast="已切换至：课堂科研数据治理">课堂科研数据治理</button></div>`]
    };
    const template = templates[type] || ["操作确认", "<p>此操作已准备就绪。</p>"];
    title.textContent = template[0];
    body.innerHTML = template[1];
    setRuntimeMode(state.runtime, false);
    dialog.showModal();
  }

  function clearLeanTimers() {
    state.leanTimers.forEach((timer) => window.clearTimeout(timer));
    state.leanTimers = [];
  }

  function startLeanBuild() {
    if (state.runtime === "BROWSER_LOCAL" || state.runtime === "UNAVAILABLE") {
      toast("当前模式不能运行 Lean 4；已保留为 formal_pending。", "warning");
      return;
    }
    if (state.leanRunning) return;
    state.leanRunning = true;
    clearLeanTimers();
    const status = $("#lean-status");
    const consoleOutput = $("#lean-console");
    const button = $("#lean-build-button");
    if (button) button.textContent = "构建中…";
    if (status) status.textContent = "preparing";
    if (consoleOutput) consoleOutput.textContent = "$ preparing isolated Lean 4 workspace\n$ resolving pinned Mathlib revision…";

    state.leanTimers.push(window.setTimeout(() => {
      if (status) status.textContent = "elaborating";
      if (consoleOutput) consoleOutput.textContent += "\n$ lake env lean Main.lean\ninfo: elaborating theorem spectral_error_bound";
    }, 650));
    state.leanTimers.push(window.setTimeout(() => {
      state.leanRunning = false;
      if (status) status.textContent = "succeeded";
      if (consoleOutput) consoleOutput.textContent += "\n✓ build succeeded · 0 errors · 2.31 s\nartifact: lean://run/RUN-2026-0821-0142";
      if (button) button.textContent = "重新构建";
      toast("Lean 4 后端构建成功，证明产物已写入证据账本。", "success");
    }, 1450));
  }

  function cancelLeanBuild() {
    clearLeanTimers();
    if (!state.leanRunning) {
      toast("当前没有正在运行的 Lean 构建。", "info");
      return;
    }
    state.leanRunning = false;
    const status = $("#lean-status");
    const consoleOutput = $("#lean-console");
    const button = $("#lean-build-button");
    if (status) status.textContent = "cancelled";
    if (consoleOutput) consoleOutput.textContent += "\n! build cancelled by researcher";
    if (button) button.textContent = "重新构建";
    toast("已取消构建，临时运行环境将在后台回收。", "warning");
  }

  function runEducationPreflight() {
    const scope = $("#class-scope")?.value || "combined";
    const card = $("#privacy-check");
    const value = $("#privacy-k-value");
    const publish = $("#publish-teacher-button");
    const invalid = scope === "single";
    if (value) value.textContent = invalid ? "k=14 · 未达到 k≥20" : "k=36 · 满足 k≥20";
    if (card) {
      card.classList.toggle("is-invalid", invalid);
      card.classList.toggle("is-valid", !invalid);
    }
    if (publish) publish.disabled = invalid || state.runtime === "UNAVAILABLE";
    toast(invalid ? "预检未通过：样本过小，请合并班级或扩大时间范围。" : "预检通过：仅发布聚合洞见，不传递学生原始数据。", invalid ? "danger" : "success");
  }

  function closeModal() {
    const dialog = $("#action-modal");
    if (dialog?.open) dialog.close();
  }

  function bindEvents() {
    document.addEventListener("click", (event) => {
      const nav = event.target.closest("[data-nav], [data-target-view]");
      if (nav) {
        navigate(nav.dataset.nav || nav.dataset.targetView);
        if (nav.closest("dialog")) closeModal();
      }
      const modalTrigger = event.target.closest("[data-modal]");
      if (modalTrigger) openModal(modalTrigger.dataset.modal);
      if (event.target.closest("[data-close-modal]")) closeModal();
      const toastTrigger = event.target.closest("[data-toast]");
      if (toastTrigger) {
        toast(toastTrigger.dataset.toast, "success");
        if (toastTrigger.closest("dialog")) closeModal();
      }
      const tab = event.target.closest("[data-tab]");
      if (tab) {
        $$(`[data-tab-group="${tab.dataset.tabGroup}"]`).forEach((item) => item.classList.toggle("is-active", item === tab));
        toast(`已切换到“${tab.textContent.trim()}”`, "info");
      }
    });

    $("#runtime-mode")?.addEventListener("change", (event) => setRuntimeMode(event.target.value));
    $("#run-drawer-toggle")?.addEventListener("click", () => toggleRunDrawer());
    $("#run-drawer-close")?.addEventListener("click", () => toggleRunDrawer(false));
    $("#lean-build-button")?.addEventListener("click", startLeanBuild);
    $("#lean-cancel-button")?.addEventListener("click", cancelLeanBuild);
    $("#education-preflight")?.addEventListener("click", runEducationPreflight);
    $("#class-scope")?.addEventListener("change", runEducationPreflight);

    $("#run-verification")?.addEventListener("click", () => {
      if (state.runtime === "UNAVAILABLE") return;
      toast(state.runtime === "BROWSER_LOCAL" ? "已完成浏览器本地一致性检查；外部证据待联网复核。" : "验证任务已创建，可在运行抽屉查看实时状态。", "success");
      toggleRunDrawer(true);
    });
    $("#sync-offline")?.addEventListener("click", () => toast("本地更改已按证据 ID 合并，2 处冲突等待人工确认。", "warning"));
    $("#compile-latex")?.addEventListener("click", () => toast("LaTeX 编译完成：0 errors，2 warnings。", "success"));

    document.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        openModal("command");
      }
      if (event.key === "Escape") toggleRunDrawer(false);
    });
    $("#action-modal")?.addEventListener("click", (event) => {
      if (event.target === event.currentTarget) closeModal();
    });
  }

  function init() {
    bindEvents();
    let stored = "FULL";
    try { stored = localStorage.getItem("m4-research-runtime") || "FULL"; } catch (_) { /* private mode */ }
    setRuntimeMode(runtimeProfiles[stored] ? stored : "FULL", false);
    navigate("dashboard");
    runEducationPreflight();
  }

  window.navigate = navigate;
  window.setRuntimeMode = setRuntimeMode;
  window.toggleRunDrawer = toggleRunDrawer;
  window.openModal = openModal;
  window.startLeanBuild = startLeanBuild;
  window.cancelLeanBuild = cancelLeanBuild;
  window.runEducationPreflight = runEducationPreflight;

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
