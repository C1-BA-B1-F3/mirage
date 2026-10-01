import os

for name in ["first", "bad", "later", "after", "last"]:
    os.stat("/data/" + name)
for name in ["first", "bad", "later"]:
    with open("/data/" + name, "w") as f:
        f.write("new")
try:
    os.stat("/data/missing")
except OSError:
    pass
with open("/data/after", "w") as f:
    f.write("discarded inline")
try:
    os.stat("/data/also_missing")
except OSError:
    pass
with open("/data/last", "w") as f:
    f.write("discarded at completion")
