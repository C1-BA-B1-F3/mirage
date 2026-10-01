import glob
import json

path = glob.glob("/notion/databases/*/database.json")[0]
with open(path) as f:
    print(json.load(f)["name"])
