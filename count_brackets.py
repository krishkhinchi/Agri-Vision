with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

print("Opening '[':", content.count('['))
print("Closing ']':", content.count(']'))
print("Opening '(':", content.count('('))
print("Closing ')':", content.count(')'))
print("Opening '{':", content.count('{'))
print("Closing '}':", content.count('}'))
