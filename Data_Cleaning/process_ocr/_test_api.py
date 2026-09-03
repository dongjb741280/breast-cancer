from paddleocr import PaddleOCR
ocr = PaddleOCR(
    text_detection_model_name="PP-OCRv5_server_det",
    text_recognition_model_name="PP-OCRv5_server_rec",
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
    lang="ch",
)
res = ocr.predict("pages/pg-030.png")
r = res[0]
print("=== type:", type(r).__name__)
txts = r.get('rec_texts') if hasattr(r, 'get') else getattr(r, 'rec_texts', None)
print("=== rec_texts ===")
for t in (txts or []):
    print(repr(t))
boxes = r.get('rec_boxes') if hasattr(r, 'get') else getattr(r, 'rec_boxes', None)
print("=== boxes sample ===")
for b in (boxes or [])[:5]:
    print(type(b), b)
