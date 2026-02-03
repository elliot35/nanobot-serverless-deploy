#!/bin/bash
# Script to destroy/cleanup all GCP resources created for nanobot deployment

# Don't exit on error - we want to continue even if some resources don't exist
set +e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-}"
SERVICE_NAME="${GCP_SERVICE_NAME:-nanobot-gateway}"
REGION="${GCP_REGION:-us-central1}"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

# Get the script directory and change to project root to find .env
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Try to load Telegram bot token from .env file if not set
if [ -z "$TELEGRAM_BOT_TOKEN" ] && [ -f "$PROJECT_ROOT/.env" ]; then
    export TELEGRAM_BOT_TOKEN=$(grep "^TELEGRAM_BOT_TOKEN=" "$PROJECT_ROOT/.env" | cut -d '=' -f2 | tr -d '"' | tr -d "'")
fi

echo -e "${RED}🗑️  Destroying nanobot GCP resources${NC}\n"

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}✗ gcloud CLI is not installed${NC}"
    echo "Install it from: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Check if PROJECT_ID is set
if [ -z "$PROJECT_ID" ]; then
    echo -e "${YELLOW}⚠ GCP_PROJECT_ID not set. Attempting to get default project...${NC}"
    PROJECT_ID=$(gcloud config get-value project 2>/dev/null || echo "")
    
    if [ -z "$PROJECT_ID" ]; then
        echo -e "${RED}✗ No GCP project ID found${NC}"
        echo "Set it with: export GCP_PROJECT_ID=your-project-id"
        echo "Or run: gcloud config set project YOUR_PROJECT_ID"
        exit 1
    fi
fi

echo -e "${BLUE}Using project: ${PROJECT_ID}${NC}"
echo -e "${BLUE}Service name: ${SERVICE_NAME}${NC}"
echo -e "${BLUE}Region: ${REGION}${NC}"
echo -e "${BLUE}Image: ${IMAGE_NAME}${NC}\n"

# Set the project
gcloud config set project "$PROJECT_ID" > /dev/null 2>&1

# Get service URL before deletion (needed for webhook removal)
SERVICE_URL=""
if gcloud run services describe "$SERVICE_NAME" \
    --platform managed \
    --region "$REGION" \
    --project "$PROJECT_ID" > /dev/null 2>&1; then
    SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
        --platform managed \
        --region "$REGION" \
        --format 'value(status.url)' \
        --project "$PROJECT_ID" 2>/dev/null || echo "")
fi

# Confirmation prompt
echo -e "${YELLOW}⚠ WARNING: This will delete the following resources:${NC}"
echo "  - Cloud Run service: ${SERVICE_NAME}"
if [ -n "$SERVICE_URL" ]; then
    echo "  - Service URL: ${SERVICE_URL}"
fi
echo "  - Container image: ${IMAGE_NAME}"
if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
    echo "  - Telegram webhook (if configured)"
fi
echo ""
read -p "Are you sure you want to continue? (yes/no): " -r
echo

if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    echo -e "${YELLOW}Aborted. No resources were deleted.${NC}"
    exit 0
fi

# Remove Telegram webhook (do this before deleting the service)
if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$SERVICE_URL" ]; then
    echo -e "\n${YELLOW}Removing Telegram webhook...${NC}"
    WEBHOOK_URL="${SERVICE_URL}/api/webhook/telegram"
    
    # Delete webhook by setting it to empty
    RESPONSE=$(curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/deleteWebhook" 2>/dev/null)
    
    if echo "$RESPONSE" | grep -q '"ok":true'; then
        echo -e "${GREEN}✓ Telegram webhook removed${NC}"
    else
        # Try to get webhook info first to see if it exists
        WEBHOOK_INFO=$(curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo" 2>/dev/null)
        if echo "$WEBHOOK_INFO" | grep -q '"url":""'; then
            echo -e "${YELLOW}⚠ Telegram webhook was not set${NC}"
        else
            echo -e "${YELLOW}⚠ Failed to remove Telegram webhook (may not exist or token invalid)${NC}"
            echo -e "${YELLOW}  You can manually remove it with:${NC}"
            echo -e "${YELLOW}  curl -X POST \"https://api.telegram.org/bot\${TELEGRAM_BOT_TOKEN}/deleteWebhook\"${NC}"
        fi
    fi
elif [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo -e "\n${YELLOW}⚠ TELEGRAM_BOT_TOKEN not set - skipping webhook removal${NC}"
    echo -e "${YELLOW}  Set TELEGRAM_BOT_TOKEN environment variable or ensure .env file exists${NC}"
fi

# Delete Cloud Run service
echo -e "\n${YELLOW}Deleting Cloud Run service...${NC}"
if gcloud run services describe "$SERVICE_NAME" \
    --platform managed \
    --region "$REGION" \
    --project "$PROJECT_ID" > /dev/null 2>&1; then
    gcloud run services delete "$SERVICE_NAME" \
        --platform managed \
        --region "$REGION" \
        --project "$PROJECT_ID" \
        --quiet
    echo -e "${GREEN}✓ Cloud Run service deleted${NC}"
else
    echo -e "${YELLOW}⚠ Cloud Run service not found (may already be deleted)${NC}"
fi

# Delete container image
echo -e "\n${YELLOW}Deleting container image...${NC}"
# Try to list images first to check if repository exists
if gcloud container images list-tags "$IMAGE_NAME" --limit=1 > /dev/null 2>&1; then
    # Delete all tags of the image
    gcloud container images delete "$IMAGE_NAME" --force-delete-tags --quiet 2>/dev/null
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Container image deleted${NC}"
    else
        echo -e "${YELLOW}⚠ Failed to delete container image (may already be deleted)${NC}"
    fi
else
    echo -e "${YELLOW}⚠ Container image not found (may already be deleted)${NC}"
fi

# Delete GCS bucket (optional - ask user)
GCS_BUCKET_NAME="${GCS_BUCKET_NAME:-${PROJECT_ID}-nanobot-files}"
if command -v gsutil &> /dev/null && gsutil ls -b "gs://${GCS_BUCKET_NAME}" > /dev/null 2>&1; then
    echo -e "\n${YELLOW}GCS bucket found: ${GCS_BUCKET_NAME}${NC}"
    read -p "Do you want to delete the GCS bucket and all its files? (yes/no): " -r
    echo
    
    if [[ $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
        echo -e "${YELLOW}Deleting GCS bucket...${NC}"
        gsutil -m rm -r "gs://${GCS_BUCKET_NAME}" 2>/dev/null
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✓ GCS bucket deleted${NC}"
        else
            echo -e "${YELLOW}⚠ Failed to delete GCS bucket (may have files or permissions issue)${NC}"
            echo -e "${YELLOW}  You can manually delete it with: gsutil -m rm -r gs://${GCS_BUCKET_NAME}${NC}"
        fi
    else
        echo -e "${YELLOW}⚠ GCS bucket preserved: ${GCS_BUCKET_NAME}${NC}"
    fi
fi

# Optional: Delete Cloud Build history (commented out by default)
# Uncomment the following section if you want to delete build history too
# echo -e "\n${YELLOW}Deleting Cloud Build history...${NC}"
# BUILD_IDS=$(gcloud builds list --filter="source.storageSource.bucket~'${PROJECT_ID}_cloudbuild'" --format="value(id)" --limit=100 2>/dev/null || echo "")
# if [ -n "$BUILD_IDS" ]; then
#     for BUILD_ID in $BUILD_IDS; do
#         gcloud builds delete "$BUILD_ID" --quiet 2>/dev/null || true
#     done
#     echo -e "${GREEN}✓ Cloud Build history cleaned${NC}"
# else
#     echo -e "${YELLOW}⚠ No build history found${NC}"
# fi

# Summary
echo -e "\n${GREEN}✓ Cleanup completed!${NC}"
echo -e "\n${BLUE}Summary:${NC}"
if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$SERVICE_URL" ]; then
    echo "  - Telegram webhook: removed"
fi
echo "  - Cloud Run service: ${SERVICE_NAME} (deleted)"
echo "  - Container image: ${IMAGE_NAME} (deleted)"
GCS_BUCKET_NAME="${GCS_BUCKET_NAME:-${PROJECT_ID}-nanobot-files}"
if command -v gsutil &> /dev/null && gsutil ls -b "gs://${GCS_BUCKET_NAME}" > /dev/null 2>&1; then
    echo "  - GCS bucket: ${GCS_BUCKET_NAME} (preserved or deleted based on your choice)"
fi
echo ""
echo -e "${YELLOW}Note: IAM bindings and API enablements were not removed.${NC}"
echo -e "${YELLOW}Note: External services (MongoDB Atlas, OpenRouter API) were not modified.${NC}"
echo -e "${YELLOW}Note: MongoDB data (sessions, chat history, agent actions) were not deleted.${NC}"
echo -e "${YELLOW}If you want to remove those as well, you can run:${NC}"
echo ""
echo "  # Remove Cloud Build service account permissions (optional):"
echo "  gcloud projects remove-iam-policy-binding $PROJECT_ID \\"
echo "    --member=\"serviceAccount:${PROJECT_ID}@cloudbuild.gserviceaccount.com\" \\"
echo "    --role=\"roles/storage.admin\""
echo ""
echo "  gcloud projects remove-iam-policy-binding $PROJECT_ID \\"
echo "    --member=\"serviceAccount:${PROJECT_ID}@cloudbuild.gserviceaccount.com\" \\"
echo "    --role=\"roles/run.admin\""
echo ""
echo "  gcloud projects remove-iam-policy-binding $PROJECT_ID \\"
echo "    --member=\"serviceAccount:${PROJECT_ID}@cloudbuild.gserviceaccount.com\" \\"
echo "    --role=\"roles/iam.serviceAccountUser\""
