import json
import os


# Paths (read/write from data/education)
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_EDU_DIR = os.path.join(BASE_DIR, 'data', 'education')
POSTUPI_PATH = os.path.join(DATA_EDU_DIR, 'postupi_msk.ndjson')
STEPIK_PATH = os.path.join(DATA_EDU_DIR, 'stepik.ndjson')
NETOLOGY_PATH = os.path.join(DATA_EDU_DIR, 'netology.ndjson')
SKILLFACTORY_PATH = os.path.join(DATA_EDU_DIR, 'skillfactory.ndjson')
DETAILED_PATH = os.path.join(DATA_EDU_DIR, 'education_detailed.json')
COMPARISON_PATH = os.path.join(DATA_EDU_DIR, 'education_comparison.json')

# Read ndjson files
def read_ndjson(path):
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]

postupi = read_ndjson(POSTUPI_PATH)
stepik = read_ndjson(STEPIK_PATH)
netology = read_ndjson(NETOLOGY_PATH)
skillfactory = read_ndjson(SKILLFACTORY_PATH)


# Merge all entries and build detailed dict

detailed = {}
for entry in postupi + stepik + netology + skillfactory:
    if not isinstance(entry, dict):
        continue
    name = entry.get('title', '').strip()
    if name:
        detailed[name] = entry

# Save detailed json (now as dict)
with open(DETAILED_PATH, 'w', encoding='utf-8') as f:
    json.dump(detailed, f, ensure_ascii=False, indent=2)


# Build comparison dict
comparison = {}
for name, entry in detailed.items():
    desc = entry.get('description', '').strip()
    typ = entry.get('type', '').strip()
    text = f"{name}\nТип: {typ}\nОписание: {desc}"
    comparison[name] = text

# Save comparison json
with open(COMPARISON_PATH, 'w', encoding='utf-8') as f:
    json.dump(comparison, f, ensure_ascii=False, indent=2)

print('Done!')
