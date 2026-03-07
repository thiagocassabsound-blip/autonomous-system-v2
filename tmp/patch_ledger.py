import os

pth = r'c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2\system_governance\implementation_ledger.md'

with open(pth, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if "⏳" in line and "NEEDS_AUDIT" in line:
        line = line.replace("⏳", "✅").replace("NEEDS_AUDIT", "IMPLEMENTED")
    elif "⏳" in line and line.strip().startswith(tuple(str(i) for i in range(10))):
        # For things like `490 ⏳ P8.6...`
        line = line.replace("⏳", "✅")
    
    if "496 ✅ P10.4 — SYSTEM ARCHITECTURE AUDITOR" in line or "496 🟡 P10.4 — SYSTEM ARCHITECTURE AUDITOR" in line:
        line = line.replace("🟡", "✅")
        # Ensure we add P11 if not already there
        new_lines.append(line)
        new_lines.append("497 🟡 P11 — FULL SYSTEM AUDIT\n")
        continue
        
    if "497 🟡 P11 — FULL SYSTEM AUDIT" in line:
        continue # Avoid duplicating
        
    new_lines.append(line)

with open(pth, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
