import sys, re

def main():
    src = sys.argv[1]
    dst = sys.argv[2]
    with open(src, encoding="utf-8") as f:
        raw = f.read()
    # collapse 3+ blank lines into 2
    body = re.sub(r"\n{3,}", "\n\n", raw).strip() + "\n"
    title = "# 2026 CSCO 乳腺癌诊疗指南\n\n"
    with open(dst, "w", encoding="utf-8") as f:
        f.write(title + body)

if __name__ == "__main__":
    main()
