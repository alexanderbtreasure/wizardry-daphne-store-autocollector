# Wizardry Variants Daphne 商店自動領取工具

[[English](README.md) | 繁體中文]

這個 repo 用來領取 Wizardry Variants Daphne 網頁商店的免費獎勵。Global 與 Japan 兩個商店都能領獎，但登入方式與執行環境不同。

## 商店差異

| 項目 | Global Webstore | Japan Webstore |
| --- | --- | --- |
| 腳本 | `main.py` | `main_jp.py` |
| Workflow | `Global Webstore Autocollector` | `Japan Webstore Autocollector` |
| 商店網址 | `https://store.wizardry.info/` | `https://webstore.wizardry.info/` |
| 需要的憑證 | 遊戲內 User ID | Email 與密碼 |
| 帳號設定 | 不需要註冊網頁商店帳號 | 需要註冊 JP webstore 帳號，再綁定 player ID |
| IP 需求 | 不需要日本 IP | 領取請求必須來自日本地區 IP |
| GitHub runner | GitHub-hosted runner 即可 | 需要在日本的 self-hosted runner |
| 獎勵 | 每週 50 寶石，第一次額外 800 寶石 | 每週 50 寶石，第一次額外 800 寶石 |
| 設定難度 | 簡單 | 較麻煩 |

兩邊能領的數量一樣：每週 50 寶石，第一次能額外領 800 個寶石。獎勵當然是越多越好，可以依照自己的帳號狀態設定 Global 與 Japan workflow。

## Workflow 差異

```mermaid
flowchart TD
  subgraph Global["Global Webstore"]
    G1["設定 WIZARDRY_USER_ID secret"]
    G2["GitHub-hosted runner"]
    G3["執行 main.py"]
    G4["用遊戲內 User ID 登入"]
    G5["從 store.wizardry.info 領獎"]
    G1 --> G2 --> G3 --> G4 --> G5
  end

  subgraph Japan["Japan Webstore"]
    J1["註冊 JP webstore 帳號"]
    J2["綁定 player ID"]
    J3["建立 OCI 日本 VM"]
    J4["註冊 oci,jp labels 的 self-hosted runner"]
    J5["設定 WIZARDRY_JP_EMAIL 與 WIZARDRY_JP_PASSWORD secrets"]
    J6["從日本 IP 執行 main_jp.py"]
    J7["從 webstore.wizardry.info 領獎"]
    J1 --> J2 --> J3 --> J4 --> J5 --> J6 --> J7
  end

  G5 -. "獎勵數量相同" .- J7
```

## Global 設定

1. Fork 這個 repository。
2. 開啟 `Settings -> Secrets and variables -> Actions -> New repository secret`。
3. 新增 `WIZARDRY_USER_ID`，值填遊戲內 User ID。
4. 開啟 `Actions -> Global Webstore Autocollector -> Run workflow`。

Global workflow 也會在每週一 11:00 UTC 自動執行。若要改排程，編輯 `.github/workflows/python-app.yml`。

## Japan 設定

Japan webstore 領取獎勵時需要日本 IP。這個 repo 使用日本地區的 Oracle Cloud Free Tier VM 作為 self-hosted GitHub Actions runner。

完整 SOP 請看 [OCI_JAPAN_RUNNER.zh-TW.md](OCI_JAPAN_RUNNER.zh-TW.md)。

注意事項：

- 註冊 Oracle Cloud 需要有效信用卡。
- 保持 Oracle Cloud Free Tier，不要升級到 Pay As You Go。
- Oracle 表示 Free Tier 驗證扣款或授權保留款會由發卡機構退回。
- 建議使用 `VM.Standard.E2.1.Micro` 並加上 swap。
- 2026 年在熱門區域幾乎拿不到 Always Free `VM.Standard.A1.Flex` 容量。

Runner 上線後，在 repository secrets 新增：

```text
WIZARDRY_JP_EMAIL
WIZARDRY_JP_PASSWORD
```

然後執行 `Actions -> Japan Webstore Autocollector -> Run workflow`。

## 本機執行

Global：

```sh
pip install -r requirements.txt
python main.py YOUR_WIZARDRY_USER_ID
```

Japan：

```sh
pip install -r requirements.txt
playwright install chromium
WIZARDRY_JP_EMAIL='you@example.com' WIZARDRY_JP_PASSWORD='password' python main_jp.py
```

Japan 腳本需要從日本 IP 執行。非日本 IP 可以登入，但領取獎勵會被區域限制擋下。
