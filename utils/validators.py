import re

def validate_name(name: str) -> bool:
    return bool(re.match(r'^[A-Za-zА-Яа-я\s-]+$', name))