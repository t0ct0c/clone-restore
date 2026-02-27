#!/bin/bash
# Clean up orphaned secrets for warm pods and clones that no longer exist

NAMESPACE="wordpress-staging"

echo "=== Cleaning up orphaned secrets ==="
echo ""

# Get all pod names (both warm and assigned)
EXISTING_PODS=$(kubectl get pods -n $NAMESPACE -o jsonpath='{.items[*].metadata.name}' | tr ' ' '\n')

# Get all secrets matching our patterns
SECRETS=$(kubectl get secrets -n $NAMESPACE -o name | grep -E "secret/(wordpress-warm-|load-test-)" | sed 's/secret\///')

DELETED_COUNT=0
KEPT_COUNT=0

for SECRET in $SECRETS; do
    # Extract pod/clone name from secret (remove -credentials suffix)
    RESOURCE_NAME="${SECRET%-credentials}"
    
    # Check if corresponding pod exists
    if echo "$EXISTING_PODS" | grep -q "^${RESOURCE_NAME}$"; then
        KEPT_COUNT=$((KEPT_COUNT + 1))
    else
        # Check if service exists (for clone secrets)
        SERVICE_EXISTS=$(kubectl get service -n $NAMESPACE "$RESOURCE_NAME" 2>/dev/null)
        if [ -z "$SERVICE_EXISTS" ]; then
            # Neither pod nor service exists - delete orphaned secret
            echo "Deleting orphaned secret: $SECRET"
            kubectl delete secret -n $NAMESPACE "$SECRET" 2>/dev/null
            DELETED_COUNT=$((DELETED_COUNT + 1))
        else
            KEPT_COUNT=$((KEPT_COUNT + 1))
        fi
    fi
done

echo ""
echo "=== Cleanup complete ==="
echo "  Deleted: $DELETED_COUNT orphaned secrets"
echo "  Kept: $KEPT_COUNT active secrets"
echo ""
echo "Remaining secrets:"
kubectl get secrets -n $NAMESPACE | grep -E "wordpress-warm-|load-test-" | wc -l
