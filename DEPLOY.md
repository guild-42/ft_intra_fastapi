# DEPLOY.md — ft_intra42 backend デプロイ / リリース運用書

FastAPI backend を **Coolify(自前サーバ）** にデプロイするための完全手順。
**サーバが変わっても同じ手順で再現できる**ように、何が「サーバ非依存(クラウド側)」で
何が「サーバ毎に作る」かを分けて記述する。実際に動作確認済み(2026-05-30)。

repo: **`guild-42/ft_intra_fastapi`**(public)/ 内部ポート **8000**

```
[Flutter app] ──OAuth──▶ 42 API
     │  push ◀───────────────── FCM (Firebase)
     └─ POST /api/* ─▶ Cloudflare ─▶ cloudflared(tunnel) ─▶ Traefik(:443)
                                                              └─▶ ft-intra-backend:8000
                                                                    ├─▶ Firestore (DB)
                                                                    └─▶ FCM (push)
```

- **compute(この backend)だけ自前サーバ**。DB=Firestore / push=FCM は GCP に残す(箱に依存しない)。
- secret は **Coolify の env に入れない**(後述の理由)。**サーバ上のファイルをマウント**して渡す。

---

## A. サーバ非依存(クラウド側・一度作れば使い回す)

サーバを変えても**これらは作り直さない**。新サーバはこれらに繋ぐだけ。

### A-1. Firebase / GCP プロジェクト
| 項目 | 値 |
|---|---|
| Project ID | `ft-intra-flutter` |
| Project number | `1021337077830` |
| Firestore | `(default)` / **Native mode** / `asia-northeast1` |
| 用途 | **Firestore(DB)+ FCM(push)のみ**。compute は載せない |

### A-2. Service Account(Firestore + FCM 用)
| 項目 | 値 |
|---|---|
| SA | `firebase-adminsdk-fbsvc@ft-intra-flutter.iam.gserviceaccount.com` |
| **必須ロール** | **`roles/datastore.user`**(これが無いと Firestore が `Missing or insufficient permissions`)|

ロール付与(一度だけ。プロジェクトに紐づくのでサーバ変更で消えない):
```bash
gcloud projects add-iam-policy-binding ft-intra-flutter \
  --member="serviceAccount:firebase-adminsdk-fbsvc@ft-intra-flutter.iam.gserviceaccount.com" \
  --role="roles/datastore.user" --condition=None
```

**SA 鍵 JSON の取得**(新サーバに置くため):
Firebase Console → `ft-intra-flutter` → ⚙️ 設定 → サービスアカウント → 「新しい秘密鍵を生成」→ JSON。
または:
```bash
gcloud iam service-accounts keys create sa.json \
  --iam-account=firebase-adminsdk-fbsvc@ft-intra-flutter.iam.gserviceaccount.com \
  --project ft-intra-flutter
```
> この JSON は秘密。**git 禁止**。サーバへは scp で運ぶ(後述)。

### A-3. 42 OAuth Application
| 項目 | 値 |
|---|---|
| 取得元 | https://profile.intra.42.fr/oauth/applications |
| `FT_API_CLIENT_ID` | `u-s4t2ud-4a065c9c...e5ea`(UID。app の `constants.dart` にも入っている非機密値)|
| `FT_API_CLIENT_SECRET` | アプリページの SECRET(秘密)|
| **Redirect URI(必須登録)** | **`ft-intra42://callback`**(無いとログインが redirect mismatch で失敗)|

---

## B. サーバ毎の構築(新サーバではここをやる)

### B-1. Coolify をインストール
対象サーバに Coolify を入れる。Traefik(`coolify-proxy`、host の 80/443)が立つ。

### B-2. secret ファイルを **サーバ上に**置く(Coolify env は使わない)
> ⚠️ **Coolify の env は値が 256 byte 上限**で、SA 鍵 JSON(約2.4KB）が入らない。
> さらに env が空文字で注入される不調もあった。よって **secret は全てファイル方式**にする。

```bash
# サーバに SSH して
sudo mkdir -p /opt/ft-intra-secrets

# (1) SA 鍵 JSON を配置(ローカルから scp 等で運ぶ。例: gcloud compute scp)
sudo mv /tmp/sa.json /opt/ft-intra-secrets/sa.json

# (2) 42 creds を配置
sudo tee /opt/ft-intra-secrets/ft.env >/dev/null <<'EOF'
FT_API_CLIENT_ID=u-s4t2ud-4a065c9caaecc660cbfc6a25c16142b54fdb125b9250f10da7c78163e08ae5ea
FT_API_CLIENT_SECRET=<42 の SECRET>
EOF

sudo chown root:root /opt/ft-intra-secrets/*
sudo chmod 600 /opt/ft-intra-secrets/*
```
`docker-compose.yaml` がこの2ファイルを read-only mount する(repo に入るのは**パスだけ**):
- `/opt/ft-intra-secrets/sa.json → /secrets/sa.json`(`GOOGLE_APPLICATION_CREDENTIALS=/secrets/sa.json`)
- `/opt/ft-intra-secrets/ft.env → /secrets/ft.env`(`entrypoint.sh` が `set -a; . /secrets/ft.env` で export)

### B-3. Coolify でリソース作成
1. **+ New Resource** → **Public Repository** → `https://github.com/guild-42/ft_intra_fastapi`(branch `main`)
2. Build Pack: **Docker Compose**(repo の `docker-compose.yaml` を使用。`.yaml` 拡張子・`version:` なし・`coolify` network 必須)
3. Strip Prefixes: **OFF**
4. Coolify env は**設定不要**(secret は B-2 のファイル方式)。

### B-4. Domains(Traefik ルート)
リソース → **Domains** に `https://ft-intra.guild42.net` を設定 → **Deploy**。
これで Traefik に `Host(ft-intra.guild42.net)` のルートができ、`:443` で backend を返す。

### B-5. Cloudflare Tunnel(外部公開)
Zero Trust → tunnel → **Public Hostname** に追加:
| 項目 | 値 |
|---|---|
| Subdomain / Domain | `ft-intra` / `guild42.net` |
| Service Type | **HTTPS** |
| URL | **`localhost:443`** |
| TLS → **No TLS Verify** | **ON** |

> なぜ :443 か:`localhost:8000`=Coolify ダッシュボード、`localhost:80`=Traefik が https へ 302 リダイレクト(ループ)。
> `localhost:443`=Traefik の https 入口が backend を直接返す。No TLS Verify は内部自己署名証明書を通すため
> (公開側 TLS は Cloudflare が担当)。
> 既存サービスが `:80` 統一なら、代わりに Coolify Domains を `http://ft-intra.guild42.net:8000` にして
> tunnel を `http://localhost:80` でも可(http→https リダイレクトが消える)。

### B-6. アプリ側
`guild-42/ft_intra_app` の `lib/config/constants.dart` の `backendBaseUrl` を
`https://ft-intra.guild42.net`(= Coolify ドメイン)にしてビルド。`--dart-define=BACKEND_URL=` でも可。

---

## C. リリース / 更新の手順(コード変更後)

1. `backend/` を編集 → `guild-42/ft_intra_fastapi` に push
2. Coolify → リソース → **Redeploy**(または **Stop → Deploy**)
   - ⚠️ `docker restart` では env/設定が反映されない。必ず **Redeploy**(コンテナ再生成)。
3. 下記 D で確認。

> secret(SA 鍵 / 42 creds)を変える時は **サーバ上の `/opt/ft-intra-secrets/*` を直接書き換え** → Redeploy。

---

## D. 動作確認

```bash
# 1) /health が ok か(Firestore 接続込み)
curl https://ft-intra.guild42.net/health
# 期待: {"status":"ok","poller":{...},"valid_cookies":0,...}
#   {"status":"error","detail":"...permissions..."} → SA に datastore.user が無い (A-2)
#   /login にリダイレクト → tunnel が :8000(Coolify) を向いている (B-5)

# 2) 42 client 認証が通るか(ダミー code)
curl -X POST https://ft-intra.guild42.net/api/oauth/exchange \
  -H 'Content-Type: application/json' \
  -d '{"code":"dummy","redirect_uri":"ft-intra42://callback"}'
# 期待: "invalid_grant"  → client 認証 OK(code が無効なだけ。正常)
#   "invalid_client"     → ft.env の creds が空/誤り (B-2)、または rotate 済みで旧値
```

ログ:
```bash
ssh <server> "sudo docker logs ft-intra-backend --tail 30"   # 現サーバ: gcloud compute ssh guild42-vm-01 --zone=asia-northeast1-b
```

> 補足: `docker exec ... echo $FT_API_CLIENT_ID` は **空に見える**が正常。`exec` は entrypoint を通らず
> source 済みの値が見えないだけ。実際の uvicorn プロセスは保持している(D-2 の invalid_grant が証明)。

---

## E. サーバ移行チェックリスト(臨時 VPS → 本サーバ等)

state(Firestore/FCM)はクラウド固定なので、**DB 移行は発生しない**。compute だけ移す:

- [ ] 新サーバに Coolify インストール(B-1)
- [ ] `/opt/ft-intra-secrets/sa.json` と `ft.env` を配置(B-2。鍵は旧サーバから運ぶか A-2 で再取得)
- [ ] SA に `roles/datastore.user` があるか確認(A-2。プロジェクト側なので普通は残っている)
- [ ] Coolify で `guild-42/ft_intra_fastapi` を接続・Deploy(B-3〜B-4)
- [ ] Cloudflare Tunnel の Public Hostname を**新サーバの cloudflared**に向ける(B-5)
      ／ または既存 tunnel のままなら DNS/tunnel の向き先を新サーバへ
- [ ] `curl https://ft-intra.guild42.net/health` が ok(D)
- [ ] **app は無変更**(ドメイン `ft-intra.guild42.net` が変わらなければ再ビルド不要)
- [ ] 旧サーバのリソース停止

---

## F. ハマりどころ早見表(今回の実績)

| 症状 | 原因 | 対処 |
|---|---|---|
| `/login` にリダイレクト | tunnel が `localhost:8000`(Coolify 本体)を向く | tunnel を `https://localhost:443` に (B-5) |
| 302 ループ | Domains が `https://` で tunnel が `:80` | tunnel を `:443`、または Domains を `http://...:8000` |
| `Docker Compose file not found .yaml` | ファイル名が `.yml` | `docker-compose.yaml` にする |
| env 値が空で注入 / 256byte で弾かれる | Coolify env の制限・不調 | secret は**ファイル方式**(B-2) |
| `insufficient authentication scopes` | SA 鍵が無く GCE 既定 SA にフォールバック | SA 鍵をマウント (B-2) |
| `Missing or insufficient permissions` | SA に Firestore ロール無し | `roles/datastore.user` 付与 (A-2) + コンテナ再起動 |
| `invalid_client` | 42 creds が空/誤り | `/opt/ft-intra-secrets/ft.env` を確認 |
| ログイン redirect mismatch | 42 app に redirect_uri 未登録 | `ft-intra42://callback` を登録 (A-3) |
| 設定変えたのに反映されない | `docker restart` した | Coolify から **Redeploy** |
