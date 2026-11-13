# 反應複誦 Bot

成員在訊息上按 ➕ 反應 → Bot 用該成員的**伺服器頭像與伺服器暱稱**（透過 Webhook）把那則訊息的文字再發一次。

## 一、建立 Bot（Discord Developer Portal）

1. 到 https://discord.com/developers/applications → **New Application**
2. 左側 **Bot**：
   - 按 **Reset Token** 複製 Token（之後填進 `.env`）
   - 往下開啟 **Privileged Gateway Intents** 中的
     - ✅ **SERVER MEMBERS INTENT**
     - ✅ **MESSAGE CONTENT INTENT**
3. 左側 **OAuth2 → URL Generator**：
   - Scopes：勾 `bot`
   - Bot Permissions：勾
     - View Channels（檢視頻道）
     - Read Message History（讀取訊息歷史）
     - Manage Webhooks（管理 Webhook）
     - Send Messages in Threads（在討論串中傳送訊息，若要支援討論串）
   - 複製產生的網址，用瀏覽器開啟，把 Bot 邀請到伺服器

## 二、設定與啟動（Windows）

1. 安裝 Python 3.10 以上（安裝時勾選 *Add Python to PATH*）
2. 把 `.env.example` 複製一份改名為 `.env`，填入 `DISCORD_TOKEN=你的Token`
3. 雙擊 `start.bat`（第一次會自動建立虛擬環境並安裝套件）

看到 `已登入：...` 就代表成功。

手動啟動方式：
```
pip install -r requirements.txt
python bot.py
```

## 三、設定選項（.env）

| 變數 | 說明 | 預設 |
|---|---|---|
| `TARGET_EMOJI` | 觸發的表情。自訂表情填名稱或 ID；留空 = 任何表情 | `➕` |
| `ALLOWED_CHANNEL_IDS` | 只在這些頻道運作（逗號分隔 ID）；留空 = 全部 | 空 |

> 頻道 ID：Discord 設定 → 進階 → 開啟「開發者模式」，再對頻道按右鍵 →「複製頻道 ID」。

## 說明

- 頭像與名稱使用成員的**伺服器個人檔案**（伺服器暱稱、伺服器頭像）；沒設定的話會用帳號本身的。
- 複誦的訊息不會觸發任何 @ 提及。
- 訊息沒有文字但有附件時，會改送附件連結。
- 若出現「權限不足」的訊息，請確認 Bot 在該頻道有「管理 Webhook」權限。
