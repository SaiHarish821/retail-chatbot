import json, base64

path = r'C:\Users\SAIHARISHGURRAM\.gemini\antigravity-ide\brain\2216aab9-bc82-4bbe-877a-a19200dcce27\.system_generated\steps\31\content.md'
data = open(path, encoding='utf-8').read()
start = data.find('{"sha"')
j = json.loads(data[start:].strip())
content = base64.b64decode(j['content'])
open(r'c:\Projects\retail-chatbot\scratch\reference_app.py', 'wb').write(content)
print('Done:', len(content), 'bytes')
