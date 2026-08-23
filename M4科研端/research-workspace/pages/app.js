/* ============================================
   智学数研 · 科研工作台 — 交互逻辑
   ============================================ */

(function() {
  'use strict';

  // ===== State =====
  const state = {
    currentView: 'dashboard',
    currentMode: 'FULL',
    drawerOpen: false,
    evidenceOpen: true,
    leanBuildRunning: false,
    leanBuildProgress: 0,
    leanBuildTimer: null
  };

  // ===== View Navigation =====
  function switchView(viewName) {
    state.currentView = viewName;

    // Update sidebar nav items
    document.querySelectorAll('.nav-item').forEach(item => {
      item.classList.remove('active');
      if (item.dataset.view === viewName) {
        item.classList.add('active');
      }
    });

    // Update views visibility
    document.querySelectorAll('.view').forEach(view => {
      view.classList.remove('active');
    });
    const targetView = document.getElementById('view-' + viewName);
    if (targetView) {
      targetView.classList.add('active');
    }

    // Scroll workspace to top
    const workspace = document.querySelector('.workspace');
    if (workspace) workspace.scrollTop = 0;
  }

  // ===== Tab Switching =====
  function switchTab(group, tabName) {
    // Update tab buttons
    const tabsEl = document.getElementById(group + 'Tabs');
    if (tabsEl) {
      tabsEl.querySelectorAll('.tab').forEach(tab => {
        tab.classList.remove('active');
        if (tab.dataset.tab === tabName) {
          tab.classList.add('active');
        }
      });
    }

    // Note: Full tab content switching would need tab-content elements
    // For prototype purposes, we show a toast notification
    showToast('已切换到 ' + tabName + ' 标签页', 'info');
  }

  // ===== Mode Toggle =====
  const modeConfig = {
    FULL: { color: 'var(--success)', label: 'FULL', text: '云端完整模式' },
    LOCAL_ENGINE: { color: 'var(--brand-400)', label: 'LOCAL_ENGINE', text: '本地引擎模式' },
    BROWSER_LOCAL: { color: 'var(--warning)', label: 'BROWSER_LOCAL', text: '纯浏览器模式' },
    UNAVAILABLE: { color: 'var(--error)', label: 'UNAVAILABLE', text: '离线模式' }
  };

  function handleModeChange(mode) {
    state.currentMode = mode;
    const config = modeConfig[mode] || modeConfig.FULL;

    const dot = document.getElementById('modeDot');
    const label = document.getElementById('modeLabel');

    if (dot) {
      dot.style.background = config.color;
      dot.style.boxShadow = '0 0 0 3px ' + config.color + '33';
    }
    if (label) {
      label.textContent = config.label;
    }

    // Update run mode explainer
    const explainer = document.getElementById('runModeExplainer');
    if (explainer) {
      const strong = explainer.querySelector('strong');
      const small = explainer.querySelector('small');
      if (strong) strong.textContent = config.text + ' (' + mode + ')';
      if (small) small.textContent = getModeDescription(mode);
    }

    showToast('已切换到 ' + config.text, 'info');
  }

  function getModeDescription(mode) {
    const desc = {
      FULL: '所有运行任务在云端服务器执行，支持完整的 Lean4 构建和大规模计算',
      LOCAL_ENGINE: '使用本地引擎执行计算任务，部分高级功能可能不可用',
      BROWSER_LOCAL: '仅在浏览器内运行，功能受限，数据不离开本地',
      UNAVAILABLE: '网络连接不可用，仅支持查看本地缓存数据'
    };
    return desc[mode] || '';
  }

  function switchMode() {
    const modes = ['FULL', 'LOCAL_ENGINE', 'BROWSER_LOCAL', 'UNAVAILABLE'];
    const currentIdx = modes.indexOf(state.currentMode);
    const nextMode = modes[(currentIdx + 1) % modes.length];
    const select = document.getElementById('modeSelect');
    if (select) select.value = nextMode;
    handleModeChange(nextMode);
  }

  // ===== Run Drawer Toggle =====
  function toggleRunDrawer() {
    state.drawerOpen = !state.drawerOpen;
    const drawer = document.getElementById('runDrawer');
    if (drawer) {
      drawer.classList.toggle('open', state.drawerOpen);
    }
  }

  // ===== Evidence Panel Toggle =====
  function toggleEvidencePanel() {
    state.evidenceOpen = !state.evidenceOpen;
    const app = document.getElementById('app');
    const panel = document.getElementById('evidencePanel');

    if (app) {
      app.classList.toggle('evidence-collapsed', !state.evidenceOpen);
    }
    if (panel) {
      panel.classList.toggle('open', state.evidenceOpen);
    }
  }

  // ===== Modals =====
  function openModal(modalName) {
    const modal = document.getElementById('modal-' + modalName);
    if (modal) {
      modal.classList.add('open');
      // Focus first input if any
      setTimeout(() => {
        const input = modal.querySelector('input[type="text"]');
        if (input) input.focus();
      }, 100);
    }
  }

  function closeModal(modalName) {
    const modal = document.getElementById('modal-' + modalName);
    if (modal) {
      modal.classList.remove('open');
    }
  }

  function closeModalOnBackdrop(event, modalName) {
    if (event.target.classList.contains('modal-backdrop')) {
      closeModal(modalName);
    }
  }

  // ===== Toast Notifications =====
  function showToast(message, type) {
    const region = document.getElementById('toastRegion');
    if (!region) return;

    const toast = document.createElement('div');
    toast.className = 'toast toast-' + (type || 'info');
    toast.innerHTML = '<span class="toast-icon">' + getToastIcon(type) + '</span><span>' + message + '</span><button class="toast-close" aria-label="关闭">✕</button>';

    region.appendChild(toast);

    // Animate in
    requestAnimationFrame(() => {
      toast.classList.add('show');
    });

    // Close button
    const closeBtn = toast.querySelector('.toast-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', () => dismissToast(toast));
    }

    // Auto dismiss
    setTimeout(() => dismissToast(toast), 3500);
  }

  function getToastIcon(type) {
    const icons = {
      success: '✓',
      error: '✕',
      warning: '!',
      info: 'i'
    };
    return icons[type] || 'i';
  }

  function dismissToast(toast) {
    toast.classList.remove('show');
    setTimeout(() => {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    }, 200);
  }

  // ===== Lean Build Simulation =====
  function runLeanBuild() {
    if (state.leanBuildRunning) {
      showToast('构建已在进行中', 'warning');
      return;
    }

    state.leanBuildRunning = true;
    state.leanBuildProgress = 0;

    // Update UI
    const statusEl = document.getElementById('leanBuildStatus');
    const detailEl = document.getElementById('leanBuildDetail');
    const dotEl = document.getElementById('leanBuildDot');
    const cancelBtn = document.getElementById('leanCancelBtn');
    const consoleEl = document.getElementById('leanConsole');

    if (statusEl) statusEl.textContent = '准备中...';
    if (detailEl) detailEl.textContent = '初始化构建环境';
    if (dotEl) {
      dotEl.style.background = 'var(--brand-400)';
      dotEl.style.boxShadow = '0 0 0 3px var(--brand-500-soft)';
      dotEl.style.animation = 'pulse 1.5s ease-in-out infinite';
    }
    if (cancelBtn) cancelBtn.style.display = 'inline-flex';
    if (consoleEl) {
      consoleEl.innerHTML = '';
      addConsoleLog(consoleEl, 'info', '正在准备构建环境...');
    }

    // Simulate build phases
    const phases = [
      { progress: 15, status: '准备中', detail: '加载工具链', log: '工具链 leanprover/lean4:v4.12.0', type: 'info' },
      { progress: 25, status: '准备中', detail: '加载 Mathlib 缓存', log: '加载 Mathlib 缓存... 2,847 条', type: 'info' },
      { progress: 40, status: 'elaborating', detail: 'spectral_bound', log: '开始 elaboration: main_theorem.lean', type: 'info' },
      { progress: 55, status: 'elaborating', detail: 'spectral_bound 证明中', log: '✓ spectral_bound 证明完成 (3.2s)', type: 'success' },
      { progress: 70, status: 'elaborating', detail: 'norm_inequality 证明中', log: '✓ norm_inequality 证明完成 (2.8s)', type: 'success' },
      { progress: 85, status: 'elaborating', detail: 'main_convergence 证明中', log: '正在验证 main_convergence...', type: 'info' },
      { progress: 100, status: '构建成功', detail: '3 个定理 · 零错误', log: '✓ main_convergence 证明完成 (6.1s)', type: 'success' }
    ];

    let phaseIndex = 0;

    state.leanBuildTimer = setInterval(() => {
      if (!state.leanBuildRunning) {
        clearInterval(state.leanBuildTimer);
        return;
      }

      if (phaseIndex >= phases.length) {
        clearInterval(state.leanBuildTimer);
        finishLeanBuild(true);
        return;
      }

      const phase = phases[phaseIndex];
      state.leanBuildProgress = phase.progress;

      if (statusEl) statusEl.textContent = phase.status;
      if (detailEl) detailEl.textContent = phase.detail;
      if (consoleEl && phase.log) {
        addConsoleLog(consoleEl, phase.type || 'info', phase.log);
      }

      phaseIndex++;
    }, 1200);
  }

  function cancelLeanBuild() {
    if (!state.leanBuildRunning) return;

    state.leanBuildRunning = false;
    if (state.leanBuildTimer) {
      clearInterval(state.leanBuildTimer);
      state.leanBuildTimer = null;
    }

    const statusEl = document.getElementById('leanBuildStatus');
    const detailEl = document.getElementById('leanBuildDetail');
    const dotEl = document.getElementById('leanBuildDot');
    const cancelBtn = document.getElementById('leanCancelBtn');
    const consoleEl = document.getElementById('leanConsole');

    if (statusEl) statusEl.textContent = '已取消';
    if (detailEl) detailEl.textContent = '用户取消构建';
    if (dotEl) {
      dotEl.style.background = 'var(--error)';
      dotEl.style.boxShadow = '0 0 0 3px var(--error-bg)';
      dotEl.style.animation = 'none';
    }
    if (cancelBtn) cancelBtn.style.display = 'none';
    if (consoleEl) {
      addConsoleLog(consoleEl, 'error', '构建已被用户取消');
    }

    showToast('构建已取消', 'warning');
  }

  function finishLeanBuild(success) {
    state.leanBuildRunning = false;
    if (state.leanBuildTimer) {
      clearInterval(state.leanBuildTimer);
      state.leanBuildTimer = null;
    }

    const statusEl = document.getElementById('leanBuildStatus');
    const detailEl = document.getElementById('leanBuildDetail');
    const dotEl = document.getElementById('leanBuildDot');
    const cancelBtn = document.getElementById('leanCancelBtn');
    const consoleEl = document.getElementById('leanConsole');

    if (success) {
      if (statusEl) statusEl.textContent = '构建成功';
      if (detailEl) detailEl.textContent = '3 个定理 · 零错误';
      if (dotEl) {
        dotEl.style.background = 'var(--success)';
        dotEl.style.boxShadow = '0 0 0 3px var(--success-bg)';
        dotEl.style.animation = 'none';
      }
      if (consoleEl) {
        addConsoleLog(consoleEl, 'success', '构建成功 · 3 个定理 · 零错误 · 16.2s');
      }
      showToast('Lean4 构建成功！3 个定理全部验证通过', 'success');
    }

    if (cancelBtn) cancelBtn.style.display = 'none';
  }

  function addConsoleLog(consoleEl, type, message) {
    const line = document.createElement('div');
    line.className = 'log-line';
    const now = new Date();
    const time = now.getHours().toString().padStart(2, '0') + ':' +
                 now.getMinutes().toString().padStart(2, '0') + ':' +
                 now.getSeconds().toString().padStart(2, '0');

    let prefix = '';
    if (type === 'success') {
      prefix = '<span class="log-success">✓</span> ';
    } else if (type === 'error') {
      prefix = '<span class="log-error">✕</span> ';
    } else {
      prefix = '<span class="log-info">info:</span> ';
    }

    line.innerHTML = '<span class="log-time">[' + time + ']</span> ' + prefix + message;
    consoleEl.appendChild(line);
    consoleEl.scrollTop = consoleEl.scrollHeight;
  }

  // ===== Verification Run Simulation =====
  function runVerification() {
    showToast('正在运行数学验证...', 'info');

    // Simulate verification progress
    const summary = document.getElementById('verifySummary');
    if (summary) {
      const originalHTML = summary.innerHTML;
      summary.style.opacity = '0.6';
      summary.style.pointerEvents = 'none';

      setTimeout(() => {
        summary.style.opacity = '1';
        summary.style.pointerEvents = 'auto';
        showToast('5 项验证全部通过！', 'success');
      }, 2000);
    }
  }

  // ===== LaTeX Compile Simulation =====
  function runLatexCompile() {
    const buildState = document.getElementById('latexBuildState');
    if (!buildState) return;

    const dot = buildState.querySelector('.build-state-dot');
    const strong = buildState.querySelector('strong');
    const small = buildState.querySelector('small');

    if (dot) {
      dot.style.background = 'var(--brand-400)';
      dot.style.boxShadow = '0 0 0 3px var(--brand-500-soft)';
      dot.style.animation = 'pulse 1.5s ease-in-out infinite';
    }
    if (strong) strong.textContent = '编译中...';
    if (small) small.textContent = '正在编译 PDF';

    showToast('正在编译 LaTeX...', 'info');

    setTimeout(() => {
      if (dot) {
        dot.style.background = 'var(--success)';
        dot.style.boxShadow = '0 0 0 3px var(--success-bg)';
        dot.style.animation = 'none';
      }
      if (strong) strong.textContent = '编译成功';
      if (small) small.textContent = '刚刚完成 · 18 页';
      showToast('PDF 编译成功！18 页 · 零错误', 'success');
    }, 2500);
  }

  // ===== Education Privacy Preflight =====
  function runEduPrivacyPreflight() {
    const card = document.getElementById('eduPrivacyCard');
    if (!card) return;

    card.classList.add('invalid');
    const icon = card.querySelector('.privacy-card-icon');
    const strong = card.querySelector('strong');
    const small = card.querySelector('small');
    const statusSpan = card.querySelector('span:last-child');

    if (icon) icon.textContent = '⚠';
    if (strong) strong.textContent = '隐私检查中...';
    if (small) small.textContent = '正在进行字段脱敏检查和差分隐私预算计算';
    if (statusSpan) {
      statusSpan.textContent = '检查中';
      statusSpan.style.color = 'var(--warning)';
    }

    showToast('正在进行隐私合规检查...', 'info');

    setTimeout(() => {
      card.classList.remove('invalid');
      if (icon) icon.textContent = '🔒';
      if (strong) strong.textContent = '隐私合规检查通过';
      if (small) small.textContent = '所有字段均已脱敏 · 差分隐私预算充足';
      if (statusSpan) {
        statusSpan.textContent = '✓ 安全';
        statusSpan.style.color = 'var(--success)';
      }
      showToast('隐私合规检查通过', 'success');
    }, 2000);
  }

  function runEduAnalysis() {
    showToast('分析任务已启动，正在运行中...', 'info');
    setTimeout(() => {
      showToast('教育数据分析完成！查看右侧预览结果', 'success');
    }, 3000);
  }

  // ===== Project Switch =====
  function switchProject(projectName) {
    const nameEl = document.getElementById('currentProjectName');
    if (nameEl) nameEl.textContent = projectName;
    showToast('已切换到项目：' + projectName, 'success');
  }

  // ===== Task Creation =====
  function createTask() {
    closeModal('newTask');
    showToast('任务创建成功！', 'success');
  }

  // ===== Import =====
  function doImport() {
    closeModal('import');
    showToast('正在导入文献...', 'info');
    setTimeout(() => {
      showToast('成功导入 12 篇文献', 'success');
    }, 2000);
  }

  // ===== Review View Toggle =====
  function setReviewView(el, view) {
    const parent = el.closest('.segmented');
    if (parent) {
      parent.querySelectorAll('span').forEach(s => s.classList.remove('active'));
    }
    el.classList.add('active');
    showToast('已切换到' + (view === 'judge' ? '审稿人' : '作者') + '视角', 'info');
  }

  // ===== Keyboard Shortcuts =====
  function handleKeydown(event) {
    // Cmd/Ctrl + K: Command Palette
    if ((event.metaKey || event.ctrlKey) && event.key === 'k') {
      event.preventDefault();
      openModal('cmdPalette');
      return;
    }

    // Escape: Close modals
    if (event.key === 'Escape') {
      const openModals = document.querySelectorAll('.modal-backdrop.open');
      if (openModals.length > 0) {
        openModals.forEach(m => m.classList.remove('open'));
        return;
      }
    }

    // Number keys 1-9: Quick view switch (with meta key)
    if (event.metaKey || event.ctrlKey) {
      const viewMap = {
        '1': 'dashboard',
        '2': 'project',
        '3': 'literature',
        '4': 'verify',
        '5': 'lean',
        '6': 'writing',
        '7': 'review',
        '8': 'education',
        '9': 'runs'
      };
      if (viewMap[event.key]) {
        event.preventDefault();
        switchView(viewMap[event.key]);
        return;
      }
    }
  }

  // ===== Initialize =====
  function init() {
    // Set initial mode
    handleModeChange('FULL');

    // Keyboard shortcuts
    document.addEventListener('keydown', handleKeydown);

    // Project switcher button
    const projectSwitcher = document.getElementById('projectSwitcherBtn');
    if (projectSwitcher) {
      projectSwitcher.addEventListener('click', (e) => {
        e.preventDefault();
        openModal('projectSwitch');
      });
    }

    // Command palette button
    const cmdBtn = document.getElementById('cmdPaletteBtn');
    if (cmdBtn) {
      cmdBtn.addEventListener('click', (e) => {
        e.preventDefault();
        openModal('cmdPalette');
      });
    }

    console.log('智学数研 · 科研工作台 已加载');
    console.log('快捷键：⌘K 命令面板 · ⌘1-9 快速切换视图');
  }

  // ===== Expose to global =====
  window.switchView = switchView;
  window.switchTab = switchTab;
  window.handleModeChange = handleModeChange;
  window.switchMode = switchMode;
  window.toggleRunDrawer = toggleRunDrawer;
  window.toggleEvidencePanel = toggleEvidencePanel;
  window.openModal = openModal;
  window.closeModal = closeModal;
  window.closeModalOnBackdrop = closeModalOnBackdrop;
  window.showToast = showToast;
  window.runLeanBuild = runLeanBuild;
  window.cancelLeanBuild = cancelLeanBuild;
  window.runVerification = runVerification;
  window.runLatexCompile = runLatexCompile;
  window.runEduPrivacyPreflight = runEduPrivacyPreflight;
  window.runEduAnalysis = runEduAnalysis;
  window.switchProject = switchProject;
  window.createTask = createTask;
  window.doImport = doImport;
  window.setReviewView = setReviewView;

  // Initialize on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
