#!/bin/bash
# Deploy backend to Cloud Run (with Firestore)
set -e

PROJECT_ID="ft-intra-flutter"
SERVICE_NAME="ft-intra"
REGION="asia-northeast1"

echo "==> Deploying $SERVICE_NAME to Cloud Run ($REGION)..."

gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --port 8000 \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 1 \
  --max-instances 2 \
  --timeout 300 \
  --set-env-vars "POLL_INTERVAL_SECONDS=300" \
  --set-env-vars "FT_API_CLIENT_ID=${FT_API_CLIENT_ID:?set FT_API_CLIENT_ID env before deploy}" \
  --set-secrets "FT_API_CLIENT_SECRET=ft-api-client-secret:latest"

URL=$(gcloud run services describe "$SERVICE_NAME" --region "$REGION" --format='value(status.url)')
echo "==> Deployed: $URL"
echo "==> Test: curl $URL/health"
