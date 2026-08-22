path = r'c:\Users\Mike\Desktop\youtube\Shorts\fifa\frontend\src\components\FifaStudio.jsx'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Find and fix the broken ranking_font line
idx = content.find('ranking_font:')
if idx != -1:
    snippet = content[idx:idx+80]
    print("Before fix:", repr(snippet))

# Replace the broken form with the correct one
old = 'ranking_font: " arial\\, ranking_bold: false'
new = 'ranking_font: "arial", ranking_bold: false'
if old in content:
    content = content.replace(old, new)
    print("Replacement applied")
else:
    # Try alternate - just blast the whole line
    import re
    content = re.sub(
        r'ranking_font_size: 28, ranking_font: [^,]+, ranking_bold: [^,]+,',
        'ranking_font_size: 28, ranking_font: "arial", ranking_bold: false,',
        content
    )
    print("Regex replacement applied")

idx = content.find('ranking_font:')
if idx != -1:
    snippet = content[idx:idx+80]
    print("After fix:", repr(snippet))

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Done")
