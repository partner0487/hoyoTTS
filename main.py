import sys
import parrots
from parrots import TextToSpeech
from playsound import playsound 
import torch
from loguru import logger
import screen_ocr

sys.path.append('..')
parrots_path = parrots.__path__[0]
sys.path.append(parrots_path)

ocr_reader = screen_ocr.Reader.create_quality_reader()
# To read a cropped region, add bounding_box=(left, top, right, bottom).
bounding_box=(0, 910, 1920, 1000)
results = ocr_reader.read_screen(bounding_box).as_string().replace(" ", "")
print(results)

device = "cuda" if torch.cuda.is_available() else "cpu"
logger.info(f"device: {device}")
half = True if device == "cuda" else False

m = TextToSpeech(
    speaker_model_path="shibing624/parrots-gpt-sovits-speaker-maimai",
    speaker_name="MaiMai",
    device=device,
    half=half
)

m.predict(
    text=results,
    text_language="auto",
    output_path="main.wav"
)
playsound("main.wav", block=True)
