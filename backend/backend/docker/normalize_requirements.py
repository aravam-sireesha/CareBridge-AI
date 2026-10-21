"""requirements.txt may be saved as UTF-16 with CRLF (Windows). pip inside Linux needs plain UTF-8, so convert if needed."""
import sys

raw = open(sys.argv[1], "rb").read()
text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")
open(sys.argv[2], "w", encoding="utf-8", newline="\n").write(text.replace("\r\n", "\n"))
