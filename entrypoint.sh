#!/bin/sh
set -e

# Firestore / FCM の Service Account 鍵を env から実体化する。
# Coolify には SA JSON 全文を GOOGLE_CREDENTIALS_JSON という secret env で入れる。
# (ホスト側にファイルを置かずに済み、再現性が高い)
if [ -n "$GOOGLE_CREDENTIALS_JSON" ]; then
  printf '%s' "$GOOGLE_CREDENTIALS_JSON" > /tmp/sa.json
  export GOOGLE_APPLICATION_CREDENTIALS=/tmp/sa.json
fi

exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
