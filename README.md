# hoyoTTS
通過ORC偵測劇情文字和角色，並藉由AI配音，由語音念出劇情

## Motivation
其實原神中有許多支線劇情都不錯，但沒有配音
1. 對不識字亦或是盲人來說都不太友善
2. 過程中的乏味會使人缺少動力

## Description
### Reference
AI 語音來源：[原神、星穹铁道、崩坏3、绝区零、鸣潮TTS（语音合成）AI模型合集](https://www.bilibili.com/read/cv26659988/) \
ORC 文字偵測來源：[screen-ocr](https://github.com/wolfmanstout/screen-ocr) 

### Install：
```shell
git clone https://github.com/partner0487/genshin_dialog_TTS.git
cd genshin_dialog_TTS
pip install -r requirements.txt
```

點開遊戲，運行code會抓取螢幕上的文字\
記得不要擋到文字喔(目前僅支援全螢幕)
```python
python main.py
```

## Future
大致功能已成形，再來是優化
1. 實際遊戲測試，目前僅支援圖片
2. 背景自動化運行

### 如果有想法可以告訴我！！
