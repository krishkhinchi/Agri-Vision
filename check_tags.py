with open('templates/results.html', 'r', encoding='utf-8') as f:
    content = f.read()

def count_tags(tag):
    opening = content.count(f'<{tag}')
    closing = content.count(f'</{tag}>')
    print(f"Tag <{tag}>: opening={opening}, closing={closing}")

for t in ['section', 'div', 'ul', 'li', 'table', 'tr', 'th', 'td', 'script', 'button']:
    count_tags(t)
