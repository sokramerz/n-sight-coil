import re, html, csv
import xml.etree.ElementTree as ET
from collections import Counter

root = ET.parse('mplus_topics.xml').getroot()

def clean(s):
    s = html.unescape(s or '')
    s = re.sub(r'<[^>]+>', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()

rows, group_counts = [], Counter()
for t in root.findall('health-topic'):
    if t.get('language') != 'English':
        continue
    groups = [clean(g.text) for g in t.findall('group')]
    group_counts.update(groups)
    mesh = t.findall('mesh-heading/descriptor')
    rows.append({
        'id': t.get('id'),
        'title': t.get('title'),
        'url': t.get('url'),
        'meta_desc': clean(t.get('meta-desc')),
        'also_called': '|'.join(clean(a.text) for a in t.findall('also-called')),
        'see_reference': '|'.join(clean(s.text) for s in t.findall('see-reference')),
        'mesh_names': '|'.join(clean(d.text) for d in mesh),
        'mesh_ids': '|'.join(d.get('id') for d in mesh),
        'groups': '|'.join(groups),
        'summary': clean(t.findtext('full-summary')),
    })

print(len(rows), 'English topics')
for g, n in group_counts.most_common():
    print(n, g)

with open('medlineplus_topics.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=rows[0].keys())
    w.writeheader()
    w.writerows(rows)