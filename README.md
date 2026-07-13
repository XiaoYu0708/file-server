# File Server

Windows HTTP 檔案伺服器，手機透過瀏覽器即可上傳/下載檔案。

## 快速開始

下載 `dist/file_server.exe` 並執行：

```
雙擊 file_server.exe
```

- **第一次執行**會跳出檔案總管，選擇共享目錄
- **終端機**顯示 QR Code 與 6 位數配對碼
- **iPhone Safari** 掃描 QR Code 或輸入 `http://<IP>:5000`
- 輸入配對碼後即可操作

## 功能

| 功能 | 說明 |
|------|------|
| 上傳檔案 | 點擊上傳區選取檔案，支援拖曳 |
| 上傳資料夾 | 切換至「資料夾」模式，可選整個目錄 |
| 下載檔案 | 點擊「下載」按鈕 |
| 下載資料夾 | 自動壓縮為 ZIP 下載 |
| 刪除 | 點擊「刪除」按鈕 |
| 安全性 | 每次啟動隨機配對碼，關閉即失效 |

## 認證流程

```
終端機（實體主機）    手機瀏覽器
   顯示 QR Code     掃碼開啟網頁
   顯示配對碼  ───→   輸入配對碼  →  操作檔案
```

配對碼僅顯示在伺服器終端機畫面，手機網頁需輸入才能使用。關閉瀏覽器分頁或按「鎖定」即登出。

## 從原始碼建置

需要 Docker Desktop。

```powershell
.\build.ps1
```

或手動：

```powershell
docker build -t file-server-builder .
$id = docker create file-server-builder
docker cp ${id}:/src/dist/file_server.exe dist/
docker rm $id
```

## 專案結構

```
file_server/
├── dist/file_server.exe     ← 執行檔（直接執行）
├── src/
│   ├── server.py            ← Flask 主程式
│   └── templates/index.html ← Web 介面
├── Dockerfile               ← 交叉編譯用
├── build.ps1                ← 建置腳本
└── requirements.txt         ← Python 依賴
```

## 技術

- **後端**: Python Flask（PyInstaller 打包為單一 .exe）
- **前端**: 原生 HTML/CSS/JS，無框架依賴
- **建置**: Docker + Wine 交叉編譯 Windows 執行檔
- **認證**: 隨機配對碼（Header `X-Pair-Code` 或 URL 參數 `?code=`）
