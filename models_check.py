import urllib.request, json

req = urllib.request.Request(
    'https://openrouter.ai/api/v1/models',
    headers={'Authorization': 'Bearer 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'}
)
with urllib.request.urlopen(req) as r:
    data = json.loads(r.read())

models = data.get('data', [])
for m in sorted(models, key=lambda x: x['id']):
    print(m['id'])