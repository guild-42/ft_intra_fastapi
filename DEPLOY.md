# DEPLOY.md — ft_intra42 backend を Coolify にデプロイ

FastAPI backend を **Coolify(自前 VPS / Ubuntu サーバ)** に docker-compose で載せる手順。
DB は **Firestore(クラウド固定)**、push は **FCM**。どちらも GCP に残し、SA 鍵で繋ぐ。
compute(この backend)だけ自前サーバで動かす構成。

```
Flutter app ──OAuth──▶ 42 API
     │  push ◀──────────────── FCM (Firebase, 無料の中継)
     └─ POST /api/* ──▶ FastAPI (Coolify/VPS) ──┬─▶ Firestore (DB)
                         + APScheduler 4 poller  └─▶ FCM
```

---

## 0. 前提

- Coolify が VPS にインストール済み
- backend を push 済みの GitHub repo(例: `guild42/ft-intra-backend`)
- 独立したドメイン or サブドメイン(例: `api.ft-intra.example.com`)← **強く推奨**(後述の移行で効く)
- Firebase プロジェクト `ft-intra-flutter` の **Service Account 鍵(JSON)**

---

## 1. Service Account 鍵を用意する(Firestore + FCM 両用)

Firebase Console → プロジェクト `ft-intra-flutter` → ⚙️ プロジェクトの設定 →
**サービス アカウント** → 「新しい秘密鍵を生成」→ JSON ダウンロード。

- この JSON 1枚で **Firestore 読み書き + FCM 送信**の両方ができる。
- **git には絶対入れない**。次の手順で Coolify の secret env に貼るだけ。
- SA のロールは最小に(Firestore User / Firebase Cloud Messaging API Sender 相当)。

---

## 2. Coolify で新規リソースを作成

1. Coolify → 対象 Project/Server → **+ New Resource**
2. ソースを **Git Repository**(`guild42/ft-intra-backend`、branch `main`)に接続
3. Build Pack は **Docker Compose** を選択(repo ルートの `docker-compose.yml` を使う)
4. もし repo が monorepo で backend がサブディレクトリの場合は **Base Directory = `/`**(別 repo 構成なら不要)

---

## 3. Environment Variables を設定(ここが全て)

Coolify のリソース → **Environment Variables** に以下を登録。`docker-compose.yml` の `${...}` がこれを参照する。

| Key | 値 | 必須 |
|---|---|---|
| `FT_API_CLIENT_ID` | 42 の client_id(`u-s4t2ud-...`) | ✅ |
| `FT_API_CLIENT_SECRET` | 42 の client_secret(**secret 扱い**) | ✅ |
| `GOOGLE_CREDENTIALS_JSON` | 手順1の SA JSON **全文を貼り付け**(**secret 扱い**) | ✅ |
| `POLL_INTERVAL_SECONDS` 他 | 省略可(default は compose 参照) | — |

> `GOOGLE_CREDENTIALS_JSON` は JSON をそのまま(改行込みで)貼ってよい。`entrypoint.sh` が
> コンテナ内 `/tmp/sa.json` に書き出し、`GOOGLE_APPLICATION_CREDENTIALS` を自動設定する。
> ホスト側にファイルを置く必要はない。

---

## 4. ドメイン & TLS

Coolify のリソース → **Domains** に `https://api.ft-intra.example.com` を設定。
Coolify が Let's Encrypt で TLS を自動発行、内部の 8000 番にプロキシする。

> **重要:** ここで決めたドメインを Flutter app の `BACKEND_URL` に使う。
> 1ヶ月後に臨時 VPS → 本サーバへ移す時は **DNS を本サーバに向け直すだけ**で、
> アプリの再ビルド/再配布が不要になる(URL が変わらない)。

---

## 5. デプロイ & 確認

1. **Deploy** を押す → Coolify が Dockerfile をビルドして起動
2. 数十秒後、healthcheck が緑になるのを確認
3. 動作確認:

```bash
curl https://api.ft-intra.example.com/health
# {"status":"ok","poller":{"last_run":"..."},"valid_cookies":0,"registered_devices":0}
```

`last_run` が更新されていけば APScheduler(4 poller)が回っている。
**Coolify のコンテナは常時 CPU があるので、Cloud Run のような throttle 問題は起きない。**

---

## 6. Flutter app 側を向け直す

`app/lib/config/constants.dart` の `backendBaseUrl`(`--dart-define=BACKEND_URL=...`)を
手順4のドメインに設定してビルドする。

---

## 7. あとで「臨時 VPS → 本サーバ」へ移すとき

state はクラウド(Firestore / FCM)にあり**箱に依存しない**ので、移行はほぼ再デプロイだけ:

1. 本サーバに Coolify をインストール
2. 同じ GitHub repo を接続(手順2〜3を再現。env を再入力)
3. Deploy
4. **DNS を本サーバの IP に向け直す**(アプリは無変更)
5. 臨時 VPS のリソースを停止/削除

**DB(Firestore)は一切動かさない。** だからデータ移行作業は発生しない。

---

## 補足

- `deploy.sh` は旧 Cloud Run 用(現在は未使用)。Coolify では使わない。残すなら参考用。
- secret は **git 禁止**。`.gitignore` で `.env` / `*-sa.json` 等を除外済み。
- 42 の client_secret は一度コードにベタ書きされていたので、**push 前にローテート推奨**
  (42 の Application 設定で再発行 → Coolify env を更新)。
