#!/usr/bin/env python3
# Integrate advanced features into HTML template

with open('app/templates/finance.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Add script import for finance_advanced.js (before closing body tag)
if '<script src="/static/finance_bootstrap.js"></script>' in content:
    content = content.replace(
        '<script src="/static/finance_bootstrap.js"></script>',
        '<script src="/static/finance_advanced.js"></script>\n  <script src="/static/finance_bootstrap.js"></script>'
    )
    print("✓ Added finance_advanced.js import")

# Add quick stats and analytics container in cashflow section
# Find the cashflow container and add panels before it
old_cashflow_section = '''          <div id="finCashflowTableContainer">
            <table id="finCashflowTable" class="fin-table">
              <thead>'''

new_cashflow_section = '''          <div id="finQuickStatsPanel"></div>
          <div id="finAnalyticsPanel"></div>
          <div id="finAdvancedFiltersPanel"></div>
          <div id="finCashflowTableContainer">
            <table id="finCashflowTable" class="fin-table">
              <thead>'''

if old_cashflow_section in content:
    content = content.replace(old_cashflow_section, new_cashflow_section)
    print("✓ Added panels for stats, analytics, filters")

with open('app/templates/finance.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("✓✓ finance.html updated")
