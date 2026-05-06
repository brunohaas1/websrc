#!/usr/bin/env python3
# Hook advanced features into finance_cashflow.js

import re

with open('app/static/finance_cashflow.js', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Hook renderCashflow to initialize all panels
old_render_start = '''async function renderCashflow(entries) {
  const tbody = byId("finCashflowTableBody");
  if (!tbody) return;'''

new_render_start = '''async function renderCashflow(entries) {
  const tbody = byId("finCashflowTableBody");
  if (!tbody) return;
  
  // Load and render analytics
  try {
    const month = FIN.cashflowMonth || new Date().toISOString().slice(0, 7);
    const resp = await finFetch(`/api/finance/analytics?month=${month}`);
    if (resp.ok) FIN.cashflowAnalytics = await resp.json();
  } catch (e) { /* ignore */ }
  
  // Render quick stats
  const statsPanel = byId("finQuickStatsPanel");
  if (statsPanel) statsPanel.innerHTML = renderQuickStatsPanel();
  
  // Render analytics panel
  const analyticsPanel = byId("finAnalyticsPanel");
  if (analyticsPanel) analyticsPanel.innerHTML = renderAnalyticsPanel();
  
  // Render filter panel
  const filterPanel = byId("finAdvancedFiltersPanel");
  if (filterPanel) filterPanel.innerHTML = renderCashflowFiltersPanel();
  
  // Check budget alerts
  checkBudgetAlerts();'''

if old_render_start in content:
    content = content.replace(old_render_start, new_render_start)
    print("✓ Hooked panels into renderCashflow")

# 2. Initialize filters after render
if 'initAdvancedFilters()' not in content:
    # Find the end of renderCashflow and add initialization
    pattern = r'(renderCashflow\(entries\) \{[^}]*tbody\.innerHTML = rows\.join\("").*;'
    match = re.search(pattern, content, re.DOTALL)
    if match:
        # Find where to add - after rendering table rows
        if 'tbody.innerHTML = rows.join("")' in content:
            old_line = 'tbody.innerHTML = rows.join("")'
            new_line = '''tbody.innerHTML = rows.join("");
  
  // Initialize advanced filters
  setTimeout(() => initAdvancedFilters(), 100);'''
            
            content = content.replace(old_line, new_line)
            print("✓ Added initAdvancedFilters call")

# 3. Hook add/edit buttons to show templates in context
old_add_modal = '''function openAddCashflowModal() {
  openFinModal("Adicionar Lançamento", generateCashflowForm());'''

new_add_modal = '''function openAddCashflowModal(prefill = {}) {
  const form = generateCashflowForm(prefill);
  openFinModal("Adicionar Lançamento", form);
  
  // Add "Use Template" button if context available
  const modalFooter = document.querySelector(".fin-modal-footer");
  if (modalFooter && !modalFooter.querySelector(".btn-templates")) {
    const btn = document.createElement("button");
    btn.className = "btn-text btn-templates";
    btn.textContent = "📋 Templates";
    btn.style.fontSize = ".85em";
    btn.onclick = (e) => { e.preventDefault(); showTemplatesMenu(); };
    modalFooter.insertBefore(btn, modalFooter.firstChild);
  }'''

if old_add_modal in content:
    content = content.replace(old_add_modal, new_add_modal)
    print("✓ Added templates menu to add modal")

# 4. Add context menu with "Save as Template" option to each row
# Find renderCashflow table row rendering
old_row_actions = '''data-action="editCashflow" data-entry-id="${entry.id}">Edit</button>
          <button class="btn-small" data-action="deleteCashflow" data-entry-id="${entry.id}">Delete</button>'''

new_row_actions = '''data-action="editCashflow" data-entry-id="${entry.id}">Edit</button>
          <button class="btn-small" data-action="deleteCashflow" data-entry-id="${entry.id}">Delete</button>
          <button class="btn-small" data-action="saveAsTemplate" data-entry-id="${entry.id}">📋</button>'''

if old_row_actions in content:
    content = content.replace(old_row_actions, new_row_actions)
    print("✓ Added template save button to rows")

# 5. Register the new action handler for templates
if 'case "saveAsTemplate":' not in content:
    # Find where other actions are handled
    if 'case "deleteCashflow":' in content:
        old_case = '''    case "deleteCashflow":'''
        new_case = '''    case "saveAsTemplate":
      openSaveAsTemplateModal(entryId);
      break;
    case "deleteCashflow":'''
        
        content = content.replace(old_case, new_case)
        print("✓ Added saveAsTemplate action handler")

# 6. Add templates menu function if missing
if 'function showTemplatesMenu()' not in content:
    templates_menu = '''
// Show saved templates menu
function showTemplatesMenu() {
  const keys = Object.keys(localStorage).filter(k => k.startsWith('cashflow_template_'));
  if (!keys.length) {
    showToast("Nenhum template salvo");
    return;
  }
  
  const items = keys.map(k => {
    const tpl = JSON.parse(localStorage.getItem(k) || '{}');
    return `<button class="btn-full" style="text-align:left;padding:8px;border:none;background:rgba(255,255,255,0.05);border-bottom:1px solid rgba(255,255,255,0.1);cursor:pointer;" onclick="applyTemplate('${k.replace(/'/g, "\\\\'")}')">
      <strong>${escapeHtml(tpl.name || 'Sem nome')}</strong>
      <div style="font-size:.75em;color:#94a3b8;">${escapeHtml(tpl.category || '')} • ${formatBRL(tpl.fixed_amount || 0)}</div>
    </button>`;
  }).join('');
  
  openFinModal("Usar Template", `
    <div style="max-height:400px;overflow-y:auto;">
      ${items}
    </div>
  `);
}

// Use template from localStorage
function applyTemplateFromStorage(key) {
  const json = localStorage.getItem(key);
  if (json) applyTemplate(json);
  closeFinModal();
}
'''
    
    # Insert before the last function or at end
    if 'function showToast(' in content:
        # Add before showToast
        insert_pos = content.find('function showToast(')
        if insert_pos > 0:
            content = content[:insert_pos] + templates_menu + content[insert_pos:]
            print("✓ Added showTemplatesMenu function")

# 7. Add CSV import button to page
if 'btnImportCSV' not in content:
    # Find where to add button (in a menu or toolbar)
    # For now, just add to the function list so it's available
    csv_html = '''
// Open CSV import from context
function openCSVImportFromUI() {
  openCSVImportModal();
}
'''
    if 'function showTemplatesMenu()' in content:
        content = content.replace('function showTemplatesMenu()', csv_html + '\n\nfunction showTemplatesMenu()')
        print("✓ Added CSV import function")

with open('app/static/finance_cashflow.js', 'w', encoding='utf-8') as f:
    f.write(content)

print("✓✓ finance_cashflow.js integrated with advanced features")
