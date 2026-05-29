# DEPLOY.md — ft_intra42 backend を Guild42 Coolify にデプロイ

FastAPI backend を **Guild42 の Coolify(`ssh.cocoyo.org`)** に docker-compose でデプロイする手順。
`~/.claude/skills/infra-coolify-expert` の規約に準拠。
DB は **Firestore(クラウド固定)**、push は **FCM**。どちらも GCP に残し、SA 鍵 1 枚で繋ぐ。
compute(この backend)だけ Coolify で動かす。

```
Flutter app ──OAuth──▶ 42 API
     │  push ◀──────────────── FCM (Firebase, 無料の中継)
     └─ POST /api/* ──▶ FastAPI (Coolify / ssh.cocoyo.org) ──┬─▶ Firestore (DB)
                          + APScheduler 4 poller (常時CPUで安定)  └─▶ FCM
```

## Coolify 環境(固定)

| Component | Value |
|---|---|
| Server | `ssh.cocoyo.org`(`ssh kakun@ssh.cocoyo.org`)|
| Reverse Proxy | Traefik v3 |
| DNS / SSL | Cloudflare(SSL: Full)|
| Docker Network | `coolify`(external)|
| repo | `guild-42/ft_intra_fastapi`(public)|
| 内部ポート | `8000` |

---

## 1. Service Account 鍵を用意(Firestore + FCM 兼用)

Firebase Console → プロジェクト `ft-intra-flutter` → ⚙️ 設定 → **サービス アカウント** →
「新しい秘密鍵を生成」→ JSON ダウンロード。

- この 1 枚で **Firestore 読み書き + FCM 送信**の両方ができる。
- **git に入れない**。次の手順で Coolify の secret env に貼るだけ。
- ロールは最小に(Firestore User / Firebase Cloud Messaging API Sender 相当)。

## 2. Coolify でリソース作成(Docker Compose)

1. Coolify Dashboard → 対象 Project → **+ New Resource**
2. **Docker Compose**(または Public Repository → Compose)を選び、ソースを
   `guild-42/ft_intra_fastapi`(branch `main`)に接続。
3. Compose ファイルは repo の `docker-compose.yaml`(`build: .` で Dockerfile からビルド)。Coolify の **Docker Compose Location** はデフォルトの `/docker-compose.yaml` でOK(`.yml` ではなく `.yaml`)。
4. **Strip Prefixes は OFF**(API パスをそのまま渡す)。

## 3. Environment Variables(ここが全て)

リソース → **Environment Variables** に登録。`docker-compose.yaml` の `${...}` が参照する。

| Key | 値 | 必須 |
|---|---|---|
| `FT_API_CLIENT_ID` | 42 の client_id(`u-s4t2ud-...`)| ✅ |
| `FT_API_CLIENT_SECRET` | 42 の client_secret(**secret**)| ✅ |
| `GOOGLE_CREDENTIALS_JSON` | 手順1の SA JSON **全文を貼る**(**secret**)| ✅ |
| `POLL_INTERVAL_SECONDS` 他 | 省略可(default は compose 参照)| — |

> `GOOGLE_CREDENTIALS_JSON` は JSON を改行込みでそのまま貼ってよい。`entrypoint.sh` が
> コンテナ内 `/tmp/sa.json` に書き出し `GOOGLE_APPLICATION_CREDENTIALS` を自動設定する。
> ホスト側に鍵ファイルを置く必要なし。

## 4. Domains & DNS(Traefik + Cloudflare)

1. Cloudflare(該当ゾーン)→ DNS → A レコード追加: `ft-intra` → サーバ IP(**Proxied**)。SSL は Full(ゾーン設定済み)。
2. Coolify リソース → **Domains** に次を設定:
   ```
   http://ft-intra.<zone>:8000
   ```
   - **`http://` で書く**(`https://` だと 302 リダイレクトループ)。
   - ポートは**コンテナ内部の 8000**(Traefik のルーティング先)。外部アクセスは `https://ft-intra.<zone>`(443, Cloudflare 終端)。

> サブドメインは確定後にこの `<zone>` を実値に置換(既存サービスは `actraise.org` ゾーン配下)。
> このドメインを Flutter app の `BACKEND_URL` に使う。**後で本サーバへ移す時は DNS を向け直すだけ**(アプリ無変更)。

## 5. デプロイ & 確認

1. **Deploy** → Coolify が Dockerfile をビルド・起動
2. healthcheck が緑になるのを待つ
3. 動作確認:
   ```bash
   curl https://ft-intra.<zone>/health
   # {"status":"ok","poller":{"last_run":"..."},"valid_cookies":0,"registered_devices":0}
   ```
   `last_run` が更新されれば APScheduler(4 poller)が稼働。**Coolify は常時 CPU があるので Cloud Run のような throttle 問題は起きない。**

ログ確認:
```bash
ssh kakun@ssh.cocoyo.org "sudo docker logs ft-intra-backend --tail 30"
```

## 6. Flutter app を向け直す

`guild-42/ft_intra_app` の `lib/config/constants.dart` の `backendBaseUrl`
(`--dart-define=BACKEND_URL=...`)を手順4のドメインに設定してビルド。

## 7. あとで「臨時 VPS → 本サーバ」へ移すとき

state はクラウド(Firestore / FCM)にあり**箱に依存しない**ので移行はほぼ再デプロイだけ:

1. 本サーバの Coolify で同じ repo を接続(手順2〜3 を再現、env 再入力)
2. Deploy
3. **Cloudflare DNS を本サーバ IP に向け直す**(アプリ無変更)
4. 臨時側リソースを停止/削除

**DB(Firestore)は動かさない** → データ移行作業ゼロ。

---

## トラブルシューティング(SKILL より)

| 症状 | 原因 | 対策 |
|---|---|---|
| 302 リダイレクトループ | Domains が `https://` | `http://` に変更 |
| 504 Gateway Timeout | coolify network 未接続 | compose の `networks: coolify` を確認 |
| 接続タイムアウト | Domains にプロトコル無し | `http://` を付ける |
| "services" section not found | compose に `version:` がある | 削除(本 compose は既に無し)|
| リクエストが届かない | Domains のポート違い | コンテナ内部ポート `8000` を指定 |

## 補足

- `deploy.sh` は旧 Cloud Run 用(**現在は未使用**)。Coolify では使わない。参考用に残置。
- secret は **git 禁止**。`.gitignore` で `.env` / `*-sa.json` 等を除外済み。
- 42 client_secret は過去コードにベタ書きされていたので、**運用前にローテート推奨**
  (42 Application 設定で再発行 → Coolify env を更新)。
- デプロイ完了後、SKILL の「既存サービス一覧」に `ft-intra` 行を追記すること。
