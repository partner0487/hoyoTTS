import sys
import parrots
from parrots import TextToSpeech
import json
import time
import string
from playsound import playsound 

sys.path.append('..')
parrots_path = parrots.__path__[0]
sys.path.append(parrots_path)

with open('GenshinDialog\extracted_dialog\\raw_dialog_CHT.jsonl', 'r') as json_file:
    json_list = list(json_file)

m = TextToSpeech(
    speaker_model_path="shibing624/parrots-gpt-sovits-speaker-maimai",
    speaker_name="MaiMai",
)

last_role = ""
content = "啟動"
for json_str in json_list:
    result = json.loads(json_str)
    for i in result:
        if last_role != i["role"] :
            m.predict(
                text=content,
                text_language="auto",
                output_path="output_audio.wav"
            )
            playsound("output_audio.wav", block=True)
            content = ""
            last_role = i["role"]
        text_load = i["content"].replace("{F妳}{M你}","你").replace("{NICKNAME}","旅行者")
        content = content + text_load + "。"

json_file.close()
