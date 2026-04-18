import sys
import os

# Add the project root to sys.path to allow importing from 'app'
sys.path.append('/Users/melihkayhan/Desktop/spherecast-challange/agnes')

from app import consolidation

try:
    data = consolidation.load_all()
    print("Schema:", data['s'])
    print("Products count:", len(data['products']))
    print("BOM Components count:", len(data['bcs']))
    
    candidates = consolidation.consolidation_candidates()
    print("Candidates count:", len(candidates))
except Exception as e:
    import traceback
    traceback.print_exc()
