"""Accept a complete JSON response, optionally wrapped in one Markdown fence."""
import re

def parse(text,model):
    if not isinstance(text,str):raise TypeError('Model response must be text')
    value=text.strip()
    fence=re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```',value,re.I|re.S)
    if fence:value=fence.group(1).strip()
    return model.model_validate_json(value)
