#!/bin/sh
set -e

# Firestore / FCM の Service Account 鍵を env から実体化する。
# Coolify には SA JSON 全文を GOOGLE_CREDENTIALS_JSON という secret env で入れる。
# (ホスト側にファイルを置かずに済み、再現性が高い)
if [ -n "$GOOGLE_CREDENTIALS_JSON" ]; then
  printf '%s' "$GOOGLE_CREDENTIALS_JSON" > /tmp/sa.json
  export GOOGLE_APPLICATION_CREDENTIALS=/tmp/sa.json
fi

# 42 client creds はサーバ上のマウントファイルから読む(Coolify env の不調 / 256byte 制限を回避)。
# set -a で source した変数を export し、Coolify が空で注入した値も上書きする。
if [ -f /secrets/ft.env ]; then
  set -a
  . /secrets/ft.env
  set +a
fi

exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
