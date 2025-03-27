import os
import sys
import json

matrix = {'include': []}

if len(sys.argv) == 1 or (len(sys.argv) == 2 and sys.argv[1] == ''):
    files = os.listdir('.')
    projects = [f for f in files if f.endswith('.json')]
else:
    projects = [p for p in sys.argv[1:]]

for p in projects:
    matrix['include'].append({'project_name': p})

print(json.dumps(matrix))
