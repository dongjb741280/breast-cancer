# Initialize PaddleOCR instance
from paddleocr import PaddleOCR
import json
import os

# 创建OCR实例，禁用一些不需要的功能以提高性能
ocr = PaddleOCR(
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
    lang='ch'       # 指定中文语言
)

# 对本地图片进行OCR识别
print("开始OCR识别...")
result = ocr.predict("pages/pg-030.png")

# 输出结果
print("\n=== OCR识别结果 ===")
res = result[0]
rec_texts = res["rec_texts"]
rec_scores = res["rec_scores"]
rec_polys = res["rec_polys"]

all_text = []
detailed_results = []
for text, confidence, bbox in zip(rec_texts, rec_scores, rec_polys):
    bbox = bbox.tolist() if hasattr(bbox, "tolist") else list(bbox)
    print(f"文本: {text}")
    print(f"置信度: {confidence:.4f}")
    print(f"位置: {bbox}")
    print("-" * 50)
    all_text.append(text)
    detailed_results.append({
        "text": text,
        "confidence": float(confidence),
        "bbox": bbox,
    })

# 输出所有识别的文本
print("\n=== 提取的所有文本 ===")
print("\n".join(all_text))

# 保存结果到JSON文件
result_data = {
    "image": "pages/pg-030.png",
    "total_texts": len(all_text),
    "texts": all_text,
    "detailed_results": detailed_results,
}

os.makedirs("output", exist_ok=True)
with open("output/ocr_results.json", "w", encoding="utf-8") as f:
    json.dump(result_data, f, ensure_ascii=False, indent=2)

print(f"\n结果已保存到 ocr_results.json 文件")
