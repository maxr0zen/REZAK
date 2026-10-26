"""Local lexical retrieval over inspected reference cards; no training claims."""
import hashlib
import json
import re
from pathlib import Path

PATH=Path(__file__).with_name('shorts_references.json')

def fingerprint():
    return hashlib.sha256(PATH.read_bytes()).hexdigest()

def retrieve(text,limit=2):
    tokens=set(re.findall(r'[\w]+',text.lower()))
    cards=json.loads(PATH.read_text(encoding='utf-8'))
    def score(card):
        terms=set(re.findall(r'[\w]+',(card['tags']+' '+card['notes']).lower()))
        return sum(1 for term in tokens if len(term)>3 and any(t.startswith(term[:5]) for t in terms))
    ranked=sorted(cards,key=score,reverse=True)
    return [c for c in ranked if score(c)>0][:limit]

def context(text):
    return [{'id':c['id'],'notes':c['notes'],'focus':c['focus']} for c in retrieve(text)]
