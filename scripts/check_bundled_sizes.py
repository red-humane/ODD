import os

toc_path = "build_new/ODD/Analysis-00.toc"
if not os.path.exists(toc_path):
    print("TOC not found")
    exit()

with open(toc_path, "r", encoding="utf-8", errors="ignore") as f:
    lines = f.readlines()

binaries = []
for l in lines:
    parts = l.strip().split(",")
    if len(parts) >= 2:
        p = parts[1].strip(" '\"")
        if os.path.exists(p) and os.path.isfile(p):
            sz = os.path.getsize(p)
            binaries.append((sz, p))

binaries.sort(reverse=True)
seen = set()
print("Top 25 largest files bundled in ODD.exe:")
for sz, p in binaries:
    if p not in seen:
        seen.add(p)
        print(f"{sz/(1024*1024):.2f} MB: {p}")
        if len(seen) >= 25:
            break
