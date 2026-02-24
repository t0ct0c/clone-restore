#!/bin/bash
# ECR Image Cleanup Script for wp-k8s-service
# Keeps: current production images + last 5 dated images
# Removes: old test/debug images

set -e

REPO_NAME="wp-k8s-service"
AWS_REGION="us-east-1"
ACCOUNT_ID="044514005641"

echo "🔍 Analyzing ECR repository: $REPO_NAME"
echo "=========================================="

# Get current images in use
CURRENT_MAIN=$(kubectl get deployment wp-k8s-service -n wordpress-staging -o jsonpath='{.spec.template.spec.containers[0].image}' | cut -d: -f2)
CURRENT_DRAMATIQ=$(kubectl get deployment wp-k8s-service -n wordpress-staging -o jsonpath='{.spec.template.spec.containers[1].image}' | cut -d: -f2)
WARM_POOL_IMAGE=$(grep "warm_pod_image" kubernetes/wp-k8s-service/app/warm_pool_controller.py | cut -d'"' -f2 | cut -d: -f2)

echo "📦 Currently in use:"
echo "   Main container:     $CURRENT_MAIN"
echo "   Dramatiq worker:    $CURRENT_DRAMATIQ"
echo "   Warm pool clone:    $WARM_POOL_IMAGE"
echo ""

# Get all image tags
ALL_TAGS=$(aws ecr list-images --repository-name $REPO_NAME --region $AWS_REGION --query 'imageIds[*].imageTag' --output text | tr ' ' '\n' | grep -v "^None$" | sort -r)

# Tags to ALWAYS keep (current production)
KEEP_TAGS=("$CURRENT_MAIN" "$CURRENT_DRAMATIQ" "latest")

# Get today's date for new naming convention
TODAY=$(date +%Y%m%d)
echo "📅 Today's date: $TODAY"
echo ""

# Count images to delete
DELETE_COUNT=0
KEEP_COUNT=0

echo "🗑️  Images to delete:"
echo "-------------------------------------------"

for TAG in $ALL_TAGS; do
    # Skip if in keep list
    if [[ " ${KEEP_TAGS[@]} " =~ " ${TAG} " ]]; then
        ((KEEP_COUNT++))
        continue
    fi
    
    # Skip if it's today's image (recent work)
    if [[ $TAG == *"$TODAY"* ]]; then
        ((KEEP_COUNT++))
        continue
    fi
    
    # Skip if it's a named release (final, async, etc with dates)
    if [[ $TAG =~ ^(20260221-final|20260221-fix|async-20260220) ]]; then
        ((KEEP_COUNT++))
        continue
    fi
    
    # Mark for deletion
    echo "   ❌ $TAG"
    ((DELETE_COUNT++))
done

echo ""
echo "📊 Summary:"
echo "   Keeping:  $KEEP_COUNT images"
echo "   Deleting: $DELETE_COUNT images"
echo ""

if [ $DELETE_COUNT -eq 0 ]; then
    echo "✅ No images to delete!"
    exit 0
fi

# Confirm deletion
read -p "⚠️  Proceed with deletion? (y/N): " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ Cancelled"
    exit 0
fi

# Delete images
echo ""
echo "🗑️  Deleting images..."
for TAG in $ALL_TAGS; do
    if [[ " ${KEEP_TAGS[@]} " =~ " ${TAG} " ]]; then
        continue
    fi
    
    if [[ $TAG == *"$TODAY"* ]]; then
        continue
    fi
    
    if [[ $TAG =~ ^(20260221-final|20260221-fix|async-20260220) ]]; then
        continue
    fi
    
    aws ecr batch-delete-image \
        --repository-name $REPO_NAME \
        --region $AWS_REGION \
        --image-ids imageTag=$TAG \
        --query 'imageIds[0].imageTag' \
        --output text > /dev/null 2>&1 && echo "   ✅ Deleted: $TAG" || echo "   ⚠️  Failed: $TAG"
done

echo ""
echo "✅ Cleanup complete!"
