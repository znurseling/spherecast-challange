from app.consolidation import find_substitutes, search_by_material
print("Subs for 'vitamin c':", find_substitutes("vitamin c"))
print("Search for 'vitamin c':", search_by_material("vitamin c")["count"])
print("Subs for 'ascorbic acid':", find_substitutes("ascorbic acid"))
print("Search for 'ascorbic acid':", search_by_material("ascorbic acid")["count"])
