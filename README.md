# hoyoTTS

擷取原神的遊戲畫面，用 OCR 辨識劇情對話的角色和台詞，再用本機的 GPT-SoVITS 角色語音模型念出來。

---

## 動機

在原神等遊戲中，許多支線劇情沒有配音，這對以下群體不太友善：
1. **不識字或視障玩家**：無法閱讀劇情文字。
2. **普通玩家**：長時間閱讀文字容易感到乏味，降低遊戲動力。

hoyoTTS 旨在解決這些問題，自動偵測劇情文字並生成 AI 配音，讓玩家用聽的享受遊戲劇情。

---

## 功能

- **遊戲畫面擷取**：用 Windows Graphics Capture 直接擷取原神視窗，被其他視窗蓋住也拍得到。
- **對話偵測**：靠對話框的金色分隔線判斷是否在劇情對話中，不會念到地圖上的其他文字。
- **角色配音**：依畫面上的角色名找對應的語音模型；找不到的 NPC 用後備聲音（預設「空」），沒有角色名的旁白用「旁白」。
- **對話選項**：旅行者的對話選項用「空」的聲音念。
- **跟著劇情走**：玩家點到下一句時會立刻打斷上一句；台詞打字動畫跑完才開始念。
- **全本機執行**：語音合成跑在自己的顯示卡上，不需要網路 API 或金鑰。
- **圖形介面**：狀態燈、目前對話、設定、角色對應、模型下載、試聽。

---

## 系統需求

- Windows 10/11
- NVIDIA 顯示卡（建議 8GB 以上顯示記憶體；在 RTX 4090 上一句約 2–4 秒）
- 原神 PC 版，**繁體中文**介面，16:9 畫面（以 1920×1080 量測，其他 16:9 解析度會等比換算）
- [Anaconda / Miniconda](https://docs.conda.io/)
- 角色模型全部下載約 52GB（可以只下載需要的角色）

---

## 安裝

```powershell
git clone --recursive https://github.com/partner0487/hoyoTTS.git
cd hoyoTTS

conda create -n hoyoTTS python=3.11 -y
conda activate hoyoTTS
conda install -c conda-forge ffmpeg cmake -y

# PyTorch（CUDA 12.8）
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
pip install torchcodec

# GPT-SoVITS 的依賴
pip install -r GPT-SoVITS/extra-req.txt --no-deps
pip install -r GPT-SoVITS/requirements.txt

# hoyoTTS 的依賴（會把 numpy 固定在 2 以下）
pip install -r requirements.txt

# GPT-SoVITS 底模、G2PW、NLTK、Open JTalk 字典
python tools/setup_gsv.py
```

已經 clone 過但沒有 `--recursive`：執行 `git submodule update --init`。

### 下載角色模型

可以在介面的「模型下載」分頁下載，或用指令：

```powershell
python -m hoyotts.voices            # 下載全部（約 52GB，中斷後可續傳）
python -m hoyotts.voices 派蒙 空 旁白  # 只下載指定角色（簡體名）
```

預設存到 `D:\hoyoTTS_models`，可以在介面的「設定」改。至少要有「空」和「旁白」，它們是後備、選項與旁白的預設聲音。

下載後可以檢查每個模型能不能用（逐一合成一句短句，全部約 25 分鐘）：

```powershell
python tools/check_models.py
```

已知上游有少數模型缺檔（例如「塔杰·拉德卡尼」少了 SoVITS 權重），這些會自動略過、改用後備聲音。「拉齐」的參考音只有一句「呜呜…」，合成出來幾乎沒聲音，建議在「角色對應」把它指定給別的聲音。合成有隨機性，偶爾某句很短是正常的，重跑一次即可。

---

## 使用

雙擊 `run.bat`，或：

```powershell
conda activate hoyoTTS
python main.py
```

1. 開啟原神（全螢幕或視窗都可以，但**不能最小化**）。
2. 開啟 hoyoTTS，按「開始」（預設開程式就會自動開始）。第一次會花約 30 秒啟動 TTS 伺服器。
3. 進入劇情對話，台詞就會被念出來。

| 快捷鍵 | 功能 |
| :-- | :-- |
| Ctrl+F7 | 停止這句 |
| Ctrl+F8 | 暫停／繼續朗讀 |
| Ctrl+F9 | 重念上一句 |

快捷鍵可以在「設定」改。原神以系統管理員身分執行，如果在遊戲裡按快捷鍵沒反應，請用系統管理員身分開啟 hoyoTTS。

### 角色對應

遇到沒有模型的角色（例如一般 NPC、你的旅行者名字），會用後備聲音念，並列在「角色對應」分頁。雙擊角色名，選一個模型按「新增」，之後就會用那個聲音。

### 擷取預覽

按「擷取預覽」會顯示目前拍到的畫面，框出角色名、台詞、選項三個辨識區域，並顯示辨識結果。念錯或沒反應時先看這裡。區域座標在 `config.json` 的 `regions`（以 1920×1080 為基準）。

### 不開介面

```powershell
python main.py --nogui
```

---

## 運作方式

```
遊戲視窗 ──WGC──▶ 畫面 ──▶ 偵測對話框分隔線 ──▶ Windows OCR（角色名／台詞／選項）
                                                        │ 繁轉簡、比對角色名
                                                        ▼
            喇叭 ◀── 播放 ◀── GPT-SoVITS api_v2（本機，tts_server.py 啟動）
```

- `hoyotts/capture.py`：擷取遊戲視窗（WGC，失敗時改用 GDI）。
- `hoyotts/dialogue.py`：判斷對話、OCR。亮背景上 Windows OCR 放大 2 倍會漏字，所以會再用原尺寸辨識一次，補回漏掉的字。
- `hoyotts/engine.py`：主流程。台詞連續兩幀相同才念（等打字動畫），用相似度比對避免背景動畫造成的 OCR 雜訊重複觸發。
- `hoyotts/voices.py`：角色模型的下載、載入與角色名比對（容忍 OCR 錯一兩個字）。
- `hoyotts/tts.py`：啟動與呼叫 GPT-SoVITS、播放。
- `tts_server.py`：啟動 GPT-SoVITS 的 `api_v2.py`。另外做了兩件事：關掉 `cudnn.benchmark`（每句長度都不同，開著每句會多 4–5 秒），以及加上 `/stop` 讓玩家點下一句時能中止合成。

---

## 常見問題

- **狀態顯示「遊戲已最小化」**：全螢幕的原神切到其他視窗時會最小化，切回遊戲就會恢復。
- **第一句很慢**：TTS 伺服器啟動後第一次合成要暖機，之後每句約 2–4 秒；換角色時要載入權重，多約 3 秒。
- **某個角色念成別人的聲音**：到「角色對應」把它指定給正確的模型，或下載該角色的模型。

---

## 致謝與授權

- 語音合成：[GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)（MIT）
- 角色模型：[AI Hobbyist](https://www.ai-hobbyist.com/) 的 [GPT-SoVITS_Model_Collection](https://www.modelscope.cn/models/aihobbyist/GPT-SoVITS_Model_Collection)，以 [CC-BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) 授權，訓練資料來自 [Genshin_Datasets](https://github.com/AI-Hobbyist/Genshin_Datasets)。**禁止商業用途與二次散布模型。**
- 原神的角色、語音等版權屬於米哈遊。
- OCR：[screen-ocr](https://github.com/wolfmanstout/screen-ocr)（Windows OCR）

本專案程式碼採用 [MIT 授權](LICENSE)。

---

## 貢獻

歡迎提交 Issue 或 Pull Request 來改進此專案！
如果有任何想法或建議，請聯繫：
- 電子郵件：partner0487@gmail.com
- GitHub：[partner0487](https://github.com/partner0487)
