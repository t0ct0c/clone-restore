#!/bin/bash
# ECR Image Management - Tag current image with date-based name and cleanup

set -e

REPO_NAME="wp-k8s-service"
AWS_REGION="us-east-1"
ACCOUNT_ID="044514005641"
ECR_URL="$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

echo "📦 ECR Image Management"
echo "======================"
echo ""

# Get current date
TODAY=$(date +%Y%m%d)
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

# Get current image digest from deployment
CURRENT_IMAGE=$(kubectl get deployment wp-k8s-service -n wordpress-staging -o jsonpath='{.spec.template.spec.containers[0].image}')
CURRENT_TAG=$(echo $CURRENT_IMAGE | cut -d: -f2)

echo "🔍 Current production image: $CURRENT_TAG"
echo "📅 Today's date: $TODAY"
echo ""

# Create new tag name
NEW_TAG="${TODAY}-production"

echo "🏷️  Creating new tag: $NEW_TAG"
echo ""

# Get the image digest
DIGEST=$(aws ecr describe-images \
    --repository-name $REPO_NAME \
    --region $AWS_REGION \
    --image-ids imageTag=$CURRENT_TAG \
    --query 'imageDetails[0].imageDigest' \
    --output text)

echo "📌 Image digest: $DIGEST"
echo ""

# Tag the image with new name
echo "🏷️  Tagging image with $NEW_TAG..."
aws ecr put-image \
    --repository-name $REPO_NAME \
    --region $AWS_REGION \
    --image-tag $NEW_TAG \
    --image-digest $DIGEST > /dev/null 2>&1

echo "✅ Tagged successfully!"
echo ""

# Update 'latest' to point to current production
echo "🔄 Updating 'latest' tag..."
aws ecr put-image \
    --repository-name $REPO_NAME \
    --region $AWS_REGION \
    --image-tag latest \
    --image-digest $DIGEST > /dev/null 2>&1
echo "✅ Latest updated!"
echo ""

# Update deployment to use new tag
echo "📝 Updating Kubernetes deployment..."
kubectl set image deployment/wp-k8s-service \
    wp-k8s-service=$ECR_URL/$REPO_NAME:$NEW_TAG \
    dramatiq-worker=$ECR_URL/$REPO_NAME:$NEW_TAG \
    -n wordpress-staging

echo "⏳ Waiting for rollout..."
kubectl rollout status deployment/wp-k8s-service -n wordpress-staging --timeout=120s

echo ""
echo "✅ Deployment updated to: $NEW_TAG"
echo ""

# Also clean up wp-k8s-service-clone repository
echo "🧹 Cleaning up wp-k8s-service-clone repository..."
CLONE_REPO="wp-k8s-service-clone"
CURRENT_CLONE=$(grep "warm_pod_image" kubernetes/wp-k8s-service/app/warm_pool_controller.py | cut -d'"' -f2 | cut -d: -f2)

echo "   Current warm pool image: $CURRENT_CLONE"

# Keep only optimized-v8 and optimized-v9, delete others
aws ecr list-images --repository-name $CLONE_REPO --region $AWS_REGION --query 'imageIds[*].imageTag' --output text | tr ' ' '\n' | grep -v "^None$" | while read TAG; do
    if [[ "$TAG" == "optimized-v8" ]] || [[ "$TAG" == "optimized-v9" ]] || [[ "$TAG" == "latest" ]]; then
        echo "   ✅ Keeping: $TAG"
    else
        echo "   🗑️  Deleting: $TAG"
        aws ecr batch-delete-image \
            --repository-name $CLONE_REPO \
            --region $AWS_REGION \
            --image-ids imageTag=$TAG \
            --output text > /dev/null 2>&1 || true
    fi
done

echo ""
echo "🎉 Complete!"
echo ""
echo "📊 Summary:"
echo "   New production tag: $NEW_TAG"
echo "   Latest tag: Updated"
echo "   Deployment: Updated"
echo "   Clone repo: Cleaned up"
