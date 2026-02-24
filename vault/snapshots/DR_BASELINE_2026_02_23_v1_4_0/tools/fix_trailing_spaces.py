
import sys

filename = r'c:\Users\faraw\Documents\Trade_Scan\governance\SOP\trade_scan_preflight_agent.md'
with open(filename, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Target lines to clean (broad range to catch off-by-one errors)
# Lines 40-50 (1-based) cover the area of interest in both view_file and python
start_line = 40
end_line = 50

new_lines = []
for i, line in enumerate(lines):
    line_num = i + 1
    if start_line <= line_num <= end_line:
        # Strip trailing whitespace (spaces, tabs) but keep newline
        # rstrip() removes \n too, so we add it back
        original_newline = '\n'
        if line.endswith('\r\n'):
            original_newline = '\r\n'
        elif line.endswith('\r'):
            original_newline = '\r'
            
        content = line.rstrip() # Remves \n, \r, \t, space
        new_line = content + original_newline
        new_lines.append(new_line)
        if line != new_line:
            print(f"Fixed formatting on line {line_num}")
    else:
        new_lines.append(line)

with open(filename, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("File update complete.")
