from pathlib import Path
import re
import subprocess
html_path = Path("planner.html")
out_path = Path("/tmp/planner-script.js")
if not html_path.exists():

    raise FileNotFoundError("planner.html was not found in the current folder.")

html = html_path.read_text()

scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.S | re.I)

out_path.write_text("\n\n".join(scripts))

print(f"Extracted {len(scripts)} script block(s) to {out_path}")

subprocess.run(["node", "--check", str(out_path)], check=True)

