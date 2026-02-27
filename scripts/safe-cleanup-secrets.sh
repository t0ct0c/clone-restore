#!/bin/bash
# SAFE cleanup - only deletes secrets for pods/services that don't exist

NAMESPACE="wordpress-staging"

echo "=== SAFE Secret Cleanup ==="
echo ""
echo "Checking which secrets are safe to delete..."
echo ""

# Get all current pods
CURRENT_PODS=$(kubectl get pods -n $NAMESPACE -o jsonpath='{.items[*].metadata.name}')

# Get all current services  
CURRENT_SERVICES=$(kubectl get services -n $NAMESPACE -o jsonpath='{.items[*].metadata.name}')

SECRETS_TO_DELETE=""
SAFE_COUNT=0
PROTECTED_COUNT=0

# Check each secret
for SECRET in $(kubectl get secrets -n $NAMESPACE -o name | grep -E "secret/(wordpress-warm-|load-test-)" | sed 's/secret\///'); do
    RESOURCE_NAME="${SECRET%-credentials}"
    
    # Check if pod exists
    if echo "$CURRENT_PODS" | grep -wq "$RESOURCE_NAME"; then
        echo "  PROTECTED: $SECRET (pod exists)"
        PROTECTED_COUNT=$((PROTECTED_COUNT + 1))
        continue
    fi
    
    # Check if service exists (for clone secrets)
    if echo "$CURRENT_SERVICES" | grep -wq "$RESOURCE_NAME"; then
        echo "  PROTECTED: $SECRET (service exists)"
        PROTECTED_COUNT=$((PROTECTED_COUNT + 1))
        continue
    fi
    
    # Safe to delete
    SECRETS_TO_DELETE="$SECRETS_TO_DELETE $SECRET"
    SAFE_COUNT=$((SAFE_COUNT + 1))
done

echo ""
echo "Summary:"
echo "  Protected (active): $PROTECTED_COUNT"
echo "  Safe to delete: $SAFE_COUNT"
echo ""

if [ $SAFE_COUNT -eq 0 ]; then
    echo "No orphaned secrets to delete!"
    exit 0
fi

read -p "Delete $SAFE_COUNT orphaned secrets? (y/n) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    for SECRET in $SECRETS_TO_DELETE; do
        kubectl delete secret -n $NAMESPACE "$SECRET" 2>/dev/null && echo "  Deleted: $SECRET"
    done
    echo ""
    echo "✓ Cleanup complete"
else
    echo "Cancelled"
fi
