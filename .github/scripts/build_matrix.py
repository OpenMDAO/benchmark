import os
import sys
import json

matrix = {'include': []}

print(f"{sys.argv=}")

if len(sys.argv) > 1:
    projects = sys.argv[1:]
else:
    projects = os.listdir('.')
    projects = [f for f in projects if f.endswith('.json')]

for p in projects:
    matrix['include'].append({'project_name': p})

print(json.dumps(matrix))
