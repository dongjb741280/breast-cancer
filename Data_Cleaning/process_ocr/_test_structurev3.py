from paddleocr import PPStructureV3
import json
import os

pipe = PPStructureV3(
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
    use_seal_recognition=False,
    use_formula_recognition=False,
    use_chart_recognition=False,
    use_table_recognition=True,
    lang="ch",
)

result = pipe.predict("pages/pg-030.png")
r = result[0]

print("=== result keys ===")
print(list(r.keys()))

parsing = r["parsing_res_list"]
print(f"\n=== {len(parsing)} blocks ===")
for i, b in enumerate(parsing):
    label = b.label
    content = b.content
    if not isinstance(content, str):
        content = repr(content)
    preview = content.replace("\n", "\\n")
    if len(preview) > 400:
        preview = preview[:400] + "…"
    print(f"[{i}] {label} bbox={b.bbox}: {preview}")

os.makedirs("output", exist_ok=True)
with open("output/structurev3_pg030.json", "w", encoding="utf-8") as f:
    json.dump([b.to_dict() for b in parsing], f, ensure_ascii=False, indent=2, default=str)
print("\nsaved output/structurev3_pg030.json")
