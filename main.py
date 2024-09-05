# Simple script to perform OCR on the current screen contents.

import screen_ocr
import requests
import json
from playsound import playsound 
import urllib.request
from opencc import OpenCC
import os
from dotenv import load_dotenv

load_dotenv()
access_token = os.getenv("access_token")

cc = OpenCC('t2s')
ocr_reader = screen_ocr.Reader.create_quality_reader()
# To read a cropped region, add bounding_box=(left, top, right, bottom).
bounding_box=(800, 800, 1020, 890)
results = ocr_reader.read_screen(bounding_box)
speaker = results.as_string().replace(" ", "").replace("\n", "")
if speaker == "青雀":
    speaker += "【星穹铁道 】"
else:
    speaker += "【原神】"
speaker = cc.convert(speaker)
print(speaker)

bounding_box=(0, 800, 1920, 980)
results = ocr_reader.read_screen(bounding_box)
text = results.as_string().replace(" ", "").replace("\n", "")
text = cc.convert(text)
print(text)

url = 'https://infer.acgnai.top/infer/gen'
headers = {
    "content-type": "application/json"
}
payload = {
        "access_token": access_token,
        "type": "tts",
        "brand": "gpt-sovits",
        "name": "anime",
        "method": "api",
        "prarm": {
            "speaker": speaker,
            "emotion": "开心_happy",
            "text": text,
            "text_language":"中文",
            "text_split_method": "按标点符号切",
            "fragment_interval": 0.3,
            "batch_size": 10,
            "batch_threshold": 0.75,
            "parallel_infer": True,
            "split_bucket": True,
            "top_k": 10,
            "top_p": 1.0,
            "temperature": 1.0,
            "speed_factor": 1.0
    }
}

res_json = requests.post(url, json.dumps(payload))
responseData = res_json.json()
print(f"message: {responseData['message']}")
print(f"audio: {responseData['audio']}")
urllib.request.urlretrieve(responseData['audio'], "main.wav")
playsound("main.wav", block=True)
