import re

with open('app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    # Count quotes, ignoring escaped ones
    quotes = len(re.findall(r'(?<!\\)"', line))
    if quotes % 2 != 0:
        # Ignore comments and triple quotes
        if '"""' not in line and not line.strip().startswith('#'):
             print(f"Line {i+1} has {quotes} quotes: {line.strip()}")
