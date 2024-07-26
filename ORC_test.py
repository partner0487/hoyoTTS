# Simple script to perform OCR on the current screen contents.

import screen_ocr

ocr_reader = screen_ocr.Reader.create_quality_reader()
# To read a cropped region, add bounding_box=(left, top, right, bottom).
bounding_box=(0, 910, 1920, 1000)
results = ocr_reader.read_screen(bounding_box)
print(results.as_string().replace(" ", ""))