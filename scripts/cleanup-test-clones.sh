#!/bin/bash
# Cleanup test clones - deletes services, ingresses, secrets, and assigned pods

NAMESPACE="wordpress-staging"
PATTERN="${1:-load-test}"  # Default pattern is "load-test"

echo "=== Cleaning up test clones matching pattern: $PATTERN ==="
echo ""

# Delete ingresses
echo "Deleting ingresses..."
kubectl get ingress -n $NAMESPACE | grep "^$PATTERN" | awk '{print $1}' | xargs -I {} kubectl delete ingress -n $NAMESPACE {} 2>/dev/null
echo "✓ Ingresses deleted"

# Delete services
echo "Deleting services..."
kubectl get service -n $NAMESPACE | grep "^$PATTERN" | awk '{print $1}' | xargs -I {} kubectl delete service -n $NAMESPACE {} 2>/dev/null
echo "✓ Services deleted"

# Delete secrets
echo "Deleting secrets..."
kubectl get secrets -n $NAMESPACE | grep "^$PATTERN.*-credentials" | awk '{print $1}' | xargs -I {} kubectl delete secret -n $NAMESPACE {} 2>/dev/null
echo "✓ Secrets deleted"

# Delete assigned pods (warm pods assigned to clones)
echo "Deleting assigned pods..."
kubectl delete pods -n $NAMESPACE -l pool-type=assigned 2>/dev/null
echo "✓ Assigned pods deleted"

echo ""
echo "=== Cleanup complete ==="
echo ""
echo "Remaining resources:"
echo "  Services: $(kubectl get service -n $NAMESPACE | grep -v NAME | grep -v redis | grep -v wp-k8s | wc -l)"
echo "  Ingresses: $(kubectl get ingress -n $NAMESPACE | grep -v NAME | grep -v wp-k8s | wc -l)"
echo "  Assigned pods: $(kubectl get pods -n $NAMESPACE -l pool-type=assigned --no-headers | wc -l)"
echo "  Warm pods: $(kubectl get pods -n $NAMESPACE -l pool-type=warm --no-headers | wc -l)"
