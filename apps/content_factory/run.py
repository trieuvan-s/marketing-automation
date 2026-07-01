from pathlib import Path
print("="*40)
print("TW Content Factory MVP v0.1.0")
for d in ["storage/documents","storage/logs","storage/output"]:
 Path(d).mkdir(parents=True,exist_ok=True)
print("Bootstrap OK")
