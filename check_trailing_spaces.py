
import sys

filename = r'c:\Users\faraw\Documents\Trade_Scan\governance\SOP\trade_scan_preflight_agent.md'
with open(filename, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"Total lines in Python: {len(lines)}")

print(f"Line 27: {repr(lines[26])}")
print(f"Line 28: {repr(lines[27])}")
print(f"Line 29: {repr(lines[28])}")
