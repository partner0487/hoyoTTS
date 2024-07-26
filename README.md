# genshin_dialog_TTS
通過ORC偵測劇情文字，並藉由AI配音，由語音念出劇情

## Motivation
其實原神中有許多支線劇情都不錯，但沒有配音
1. 對不識字亦或是盲人來說都不太友善
2. 過程中的乏味會使人缺少動力

## Description
### Reference
AI 語音來源：[parrots](https://github.com/shibing624/parrots.git) \
ORC 文字偵測來源：[screen-ocr](https://github.com/wolfmanstout/screen-ocr) 

### Install：
```shell
pip install torch
git clone https://github.com/partner0487/genshin_dialog_TTS.git
cd genshin_dialog_TTS
pip install -r requirements.txt
pip install parrots
```

點開遊戲，運行code會抓取螢幕上高度在920~1000位置的文字\
記得不要擋到文字喔
```python
python main.py
```

## Future
大致功能已成形，再來是優化
1. 訓練原神中遊戲角色的聲音做為AI語音
2. 加速TTS速度，目前大概一句話花費90秒
3. 背景自動化運行

### 如果有想法可以告訴我！！
