#!/bin/bash
# One-command deployment script for Google Cloud Run

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-}"
SERVICE_NAME="${GCP_SERVICE_NAME:-nanobot-gateway}"
REGION="${GCP_REGION:-us-central1}"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

# Get the script directory and change to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo -e "${GREEN}🚀 Deploying nanobot to Google Cloud Run${NC}\n"

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

echo -e "${GREEN}✓ Using project: ${PROJECT_ID}${NC}"

# Set the project
gcloud config set project "$PROJECT_ID"

# Enable required APIs and grant permissions
echo -e "\n${YELLOW}Enabling required APIs and setting up permissions...${NC}"

# Enable required APIs
gcloud services enable cloudbuild.googleapis.com --project "$PROJECT_ID" 2>/dev/null || true
gcloud services enable run.googleapis.com --project "$PROJECT_ID" 2>/dev/null || true
gcloud services enable containerregistry.googleapis.com --project "$PROJECT_ID" 2>/dev/null || true
gcloud services enable storage-component.googleapis.com --project "$PROJECT_ID" 2>/dev/null || true
gcloud services enable storage-api.googleapis.com --project "$PROJECT_ID" 2>/dev/null || true

# Get the Cloud Build service account email
CLOUD_BUILD_SA="${PROJECT_ID}@cloudbuild.gserviceaccount.com"

# Grant Cloud Build service account necessary permissions
echo -e "${YELLOW}Granting permissions to Cloud Build service account...${NC}"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${CLOUD_BUILD_SA}" \
    --role="roles/storage.admin" \
    --condition=None 2>/dev/null || true

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${CLOUD_BUILD_SA}" \
    --role="roles/run.admin" \
    --condition=None 2>/dev/null || true

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${CLOUD_BUILD_SA}" \
    --role="roles/iam.serviceAccountUser" \
    --condition=None 2>/dev/null || true

echo -e "${GREEN}✓ APIs enabled and permissions granted${NC}"

# Create GCS bucket for file storage (if not exists)
GCS_BUCKET_NAME="${GCS_BUCKET_NAME:-${PROJECT_ID}-nanobot-files}"
echo -e "\n${YELLOW}Setting up GCS bucket for file storage...${NC}"

if gsutil ls -b "gs://${GCS_BUCKET_NAME}" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ GCS bucket already exists: ${GCS_BUCKET_NAME}${NC}"
else
    echo -e "${YELLOW}Creating GCS bucket: ${GCS_BUCKET_NAME}${NC}"
    gsutil mb -p "$PROJECT_ID" -l "$REGION" "gs://${GCS_BUCKET_NAME}" 2>/dev/null || {
        # Try with different location constraint
        gsutil mb -p "$PROJECT_ID" "gs://${GCS_BUCKET_NAME}" 2>/dev/null || {
            echo -e "${YELLOW}⚠ Failed to create bucket (may already exist or need different name)${NC}"
            echo -e "${YELLOW}  You can create it manually: gsutil mb gs://${GCS_BUCKET_NAME}${NC}"
        }
    }
    
    if gsutil ls -b "gs://${GCS_BUCKET_NAME}" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ GCS bucket created: ${GCS_BUCKET_NAME}${NC}"
        
        # Set bucket lifecycle (optional - to manage costs)
        echo -e "${YELLOW}Configuring bucket settings...${NC}"
        
        # Make bucket uniform access (recommended)
        gsutil uniformbucketlevelaccess set on "gs://${GCS_BUCKET_NAME}" 2>/dev/null || true
        
        # Set public access prevention (security)
        gsutil pap set enforced "gs://${GCS_BUCKET_NAME}" 2>/dev/null || true
    fi
fi

# Grant Cloud Run service account access to GCS bucket
CLOUD_RUN_SA="${PROJECT_ID}@appspot.gserviceaccount.com"
echo -e "${YELLOW}Granting Cloud Run service account access to GCS bucket...${NC}"
gsutil iam ch "serviceAccount:${CLOUD_RUN_SA}:roles/storage.objectAdmin" "gs://${GCS_BUCKET_NAME}" 2>/dev/null || {
    echo -e "${YELLOW}⚠ Could not grant bucket permissions (may need manual setup)${NC}"
    echo -e "${YELLOW}  Run: gsutil iam ch serviceAccount:${CLOUD_RUN_SA}:roles/storage.objectAdmin gs://${GCS_BUCKET_NAME}${NC}"
}

echo -e "${GREEN}✓ GCS bucket setup completed${NC}"
echo -e "${BLUE}  Bucket name: ${GCS_BUCKET_NAME}${NC}"
echo -e "${BLUE}  Set GCS_BUCKET_NAME environment variable if you want to use a different bucket${NC}"

# Check if required environment variables are set
echo -e "\n${YELLOW}Checking required environment variables...${NC}"

REQUIRED_VARS=(
    "NANOBOT_OPENROUTER_API_KEY"
    "TELEGRAM_BOT_TOKEN"
    "TELEGRAM_ALLOWED_USERS"
)

MISSING_VARS=()
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        MISSING_VARS+=("$var")
    fi
done

if [ ${#MISSING_VARS[@]} -ne 0 ]; then
    echo -e "${RED}✗ Missing required environment variables:${NC}"
    for var in "${MISSING_VARS[@]}"; do
        echo "  - $var"
    done
    echo -e "\nSet them with: export $var=value"
    exit 1
fi

echo -e "${GREEN}✓ All required environment variables are set${NC}"

# Build and push Docker image
echo -e "\n${YELLOW}Building Docker image...${NC}"
gcloud builds submit --config gcp/cloudbuild.yaml --substitutions=_IMAGE_NAME="$IMAGE_NAME" --project "$PROJECT_ID" .

# Prepare environment variables for Cloud Run
ENV_VARS=(
    "NANOBOT_OPENROUTER_API_KEY=${NANOBOT_OPENROUTER_API_KEY}"
    "NANOBOT_MODEL=${NANOBOT_MODEL:-anthropic/claude-opus-4-5}"
    "TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}"
    "TELEGRAM_ALLOWED_USERS=${TELEGRAM_ALLOWED_USERS}"
    "GCP_PROJECT_ID=${PROJECT_ID}"
    "GCS_BUCKET_NAME=${GCS_BUCKET_NAME}"
)

# Add optional variables if set
[ -n "$BRAVE_SEARCH_API_KEY" ] && ENV_VARS+=("BRAVE_SEARCH_API_KEY=${BRAVE_SEARCH_API_KEY}")
[ -n "$LOG_LEVEL" ] && ENV_VARS+=("LOG_LEVEL=${LOG_LEVEL}")

# Deploy to Cloud Run
echo -e "\n${YELLOW}Deploying to Cloud Run...${NC}"
gcloud run deploy "$SERVICE_NAME" \
    --image "$IMAGE_NAME" \
    --platform managed \
    --region "$REGION" \
    --allow-unauthenticated \
    --set-env-vars "$(IFS=,; echo "${ENV_VARS[*]}")" \
    --memory 512Mi \
    --cpu 1 \
    --timeout 300 \
    --max-instances 10 \
    --project "$PROJECT_ID"

# Get the service URL
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
    --platform managed \
    --region "$REGION" \
    --format 'value(status.url)' \
    --project "$PROJECT_ID")

echo -e "\n${GREEN}✓ Deployment successful!${NC}"
echo -e "${GREEN}Service URL: ${SERVICE_URL}${NC}"
echo -e "\n${YELLOW}Next steps:${NC}"
echo "1. Set Telegram webhook:"
echo "   curl -X POST \"https://api.telegram.org/bot\${TELEGRAM_BOT_TOKEN}/setWebhook?url=${SERVICE_URL}/api/webhook/telegram\""
echo ""
echo "2. Test health check:"
echo "   curl ${SERVICE_URL}/api/health"
echo ""
echo "3. View logs:"
echo "   gcloud run logs read $SERVICE_NAME --region $REGION --project $PROJECT_ID"