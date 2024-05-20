# genshin_dialog_TTS
導入劇情文本，並藉由AI配音，將文本轉成語音

## Motivation
其實原神中有許多支線劇情都不錯，但沒有配音
1. 對不識字亦或是盲人來說都不太友善
2. 是過程中的乏味會使人缺少動力

## Description
### Reference
AI 語音來源：[parrots](https://github.com/shibing624/parrots.git) \
劇情文本來源：[AnimeGameData](https://gitlab.com/Dimbreath/AnimeGameData) \
劇情文本轉換來源：[GenshinDialog](https://github.com/mrzjy/GenshinDialog.git) 

### Install：
```shell
pip install torch
git clone --recurse-submodules https://github.com/partner0487/genshin_dialog_TTS.git
cd genshin_dialog_TTS
pip install -r requirements.txt
pip install parrots
```

但AnimeGameData的路徑為gitlab 所以可能要手動clone
 ```shell
git clone https://gitlab.com/Dimbreath/AnimeGameData.git
```

然後去GenshinDialog產生jsonl的文本檔案
```shell
cd GenshinDialog
python extract_dialogs.py --repo=../AnimeGameData --lang=CHT
cd ..
```

我撰寫了一個模板可以TTS jsonl檔的文本，並自動撥放 \
語音檔會存放在 output_audio.wav
```python
python test.py
```

## Future
及時抓取劇情文字，並將其轉成語音，可能方向：
1. catch genshin data flow
2. AI screen text capture
如果有想法可以告訴我！！
