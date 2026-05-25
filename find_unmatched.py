with open('app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

open_brackets = 0
for i, line in enumerate(lines):
    for char in line:
        if char == '[':
            open_brackets += 1
        elif char == ']':
            open_brackets -= 1
            if open_brackets < 0:
                print(f"Unmatched ']' at line {i+1}: {line.strip()}")
if open_brackets > 0:
    print(f"End of file: {open_brackets} open brackets remain")
elif open_brackets < 0:
    print(f"End of file: {abs(open_brackets)} extra closing brackets")
