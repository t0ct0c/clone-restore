#!/bin/bash
# Complete cleanup script for load tests
# This script cleans up ALL resources created during load testing:
# - Deployments (assigned clones)
# - Services
# - Ingresses
# - Secrets
# - Warm pool pods
# - Redis queue

set -e

NAMESPACE="wordpress-staging"
PATTERN="${1:-load-test}"  # Default pattern is "load-test"

echo "================================================================================"
echo "COMPREHENSIVE CLEANUP - Test Resources"
echo "Pattern: $PATTERN"
echo "Namespace: $NAMESPACE"
echo "================================================================================"
echo ""

# Function to count resources
count_resources() {
    local resource_type=$1
    local filter=$2
    if [ -z "$filter" ]; then
        kubectl get $resource_type -n $NAMESPACE --no-headers 2>/dev/null | wc -l
    else
        kubectl get $resource_type -n $NAMESPACE --no-headers 2>/dev/null | grep "$filter" | wc -l
    fi
}

# Show current state
echo "CURRENT STATE:"
echo "  Test Deployments: $(count_resources deployments $PATTERN)"
echo "  Test Services: $(count_resources services $PATTERN)"
echo "  Test Ingresses: $(count_resources ingress $PATTERN)"
echo "  Test Secrets: $(count_resources secrets "${PATTERN}.*-credentials")"
echo "  Warm Pool Pods: $(kubectl get pods -n $NAMESPACE -l pool-type=warm --no-headers 2>/dev/null | wc -l)"
echo "  Assigned Pods: $(kubectl get pods -n $NAMESPACE -l pool-type=assigned --no-headers 2>/dev/null | wc -l)"
echo ""

read -p "Continue with cleanup? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cleanup aborted."
    exit 0
fi

echo ""
echo "================================================================================"
echo "STEP 1: Deleting Test Clone Deployments"
echo "================================================================================"
DEPLOYMENTS=$(kubectl get deployments -n $NAMESPACE -l app=wordpress-clone --no-headers 2>/dev/null | grep "^$PATTERN" | awk '{print $1}')
if [ -z "$DEPLOYMENTS" ]; then
    echo "  No test deployments found matching pattern: $PATTERN"
else
    echo "$DEPLOYMENTS" | while read deployment; do
        echo "  Deleting deployment: $deployment"
        kubectl delete deployment $deployment -n $NAMESPACE --grace-period=0 --force 2>/dev/null || true
    done
    echo "  ✓ Test deployments deleted"
fi

echo ""
echo "================================================================================"
echo "STEP 2: Deleting Test Services"
echo "================================================================================"
SERVICES=$(kubectl get services -n $NAMESPACE --no-headers 2>/dev/null | grep "^$PATTERN" | awk '{print $1}')
if [ -z "$SERVICES" ]; then
    echo "  No test services found matching pattern: $PATTERN"
else
    echo "$SERVICES" | while read service; do
        echo "  Deleting service: $service"
        kubectl delete service $service -n $NAMESPACE 2>/dev/null || true
    done
    echo "  ✓ Test services deleted"
fi

echo ""
echo "================================================================================"
echo "STEP 3: Deleting Test Ingresses"
echo "================================================================================"
INGRESSES=$(kubectl get ingress -n $NAMESPACE --no-headers 2>/dev/null | grep "^$PATTERN" | awk '{print $1}')
if [ -z "$INGRESSES" ]; then
    echo "  No test ingresses found matching pattern: $PATTERN"
else
    echo "$INGRESSES" | while read ingress; do
        echo "  Deleting ingress: $ingress"
        kubectl delete ingress $ingress -n $NAMESPACE 2>/dev/null || true
    done
    echo "  ✓ Test ingresses deleted"
fi

echo ""
echo "================================================================================"
echo "STEP 4: Deleting Test Secrets"
echo "================================================================================"
SECRETS=$(kubectl get secrets -n $NAMESPACE --no-headers 2>/dev/null | grep "^$PATTERN.*-credentials" | awk '{print $1}')
if [ -z "$SECRETS" ]; then
    echo "  No test secrets found matching pattern: $PATTERN"
else
    echo "$SECRETS" | while read secret; do
        echo "  Deleting secret: $secret"
        kubectl delete secret $secret -n $NAMESPACE 2>/dev/null || true
    done
    echo "  ✓ Test secrets deleted"
fi

echo ""
echo "================================================================================"
echo "STEP 5: Deleting Assigned Pods (Warm Pool)"
echo "================================================================================"
ASSIGNED_PODS=$(kubectl get pods -n $NAMESPACE -l pool-type=assigned --no-headers 2>/dev/null | awk '{print $1}')
if [ -z "$ASSIGNED_PODS" ]; then
    echo "  No assigned pods found"
else
    echo "$ASSIGNED_PODS" | while read pod; do
        echo "  Deleting assigned pod: $pod"
        kubectl delete pod $pod -n $NAMESPACE --grace-period=0 --force 2>/dev/null || true
    done
    echo "  ✓ Assigned pods deleted"
fi

echo ""
echo "================================================================================"
echo "STEP 6: Deleting Warm Pool Pods"
echo "================================================================================"
WARM_PODS=$(kubectl get pods -n $NAMESPACE -l pool-type=warm --no-headers 2>/dev/null | awk '{print $1}')
if [ -z "$WARM_PODS" ]; then
    echo "  No warm pool pods found"
else
    echo "$WARM_PODS" | while read pod; do
        echo "  Deleting warm pod: $pod"
        kubectl delete pod $pod -n $NAMESPACE --grace-period=0 --force 2>/dev/null || true
    done
    echo "  ✓ Warm pool pods deleted"
fi

echo ""
echo "================================================================================"
echo "STEP 7: Clearing Redis Queue"
echo "================================================================================"
echo "  Getting Redis password..."
REDIS_PASSWORD=$(kubectl get secret redis -n $NAMESPACE -o jsonpath='{.data.redis-password}' 2>/dev/null | base64 -d)
if [ -z "$REDIS_PASSWORD" ]; then
    echo "  ✗ Could not get Redis password"
else
    echo "  Checking queue depth..."
    QUEUE_DEPTH=$(kubectl exec -n $NAMESPACE redis-master-0 -- redis-cli -a "$REDIS_PASSWORD" LLEN clone_jobs 2>&1 | grep -v "Warning:" || echo "0")
    echo "  Queue depth: $QUEUE_DEPTH"
    
    if [ "$QUEUE_DEPTH" -gt "0" ]; then
        echo "  Clearing queue..."
        kubectl exec -n $NAMESPACE redis-master-0 -- redis-cli -a "$REDIS_PASSWORD" DEL clone_jobs 2>&1 | grep -v "Warning:" || true
        echo "  ✓ Redis queue cleared"
    else
        echo "  ✓ Queue is empty"
    fi
fi

echo ""
echo "================================================================================"
echo "STEP 8: Running Orphaned Secrets Cleanup"
echo "================================================================================"
if [ -f "scripts/cleanup-orphaned-secrets.sh" ]; then
    echo "  Running cleanup-orphaned-secrets.sh..."
    bash scripts/cleanup-orphaned-secrets.sh
else
    echo "  ⚠ cleanup-orphaned-secrets.sh not found, skipping"
fi

echo ""
echo "================================================================================"
echo "CLEANUP COMPLETE"
echo "================================================================================"
echo ""
echo "FINAL STATE:"
echo "  Test Deployments: $(count_resources deployments $PATTERN)"
echo "  Test Services: $(count_resources services $PATTERN)"
echo "  Test Ingresses: $(count_resources ingress $PATTERN)"
echo "  Test Secrets: $(count_resources secrets "${PATTERN}.*-credentials")"
echo "  Warm Pool Pods: $(kubectl get pods -n $NAMESPACE -l pool-type=warm --no-headers 2>/dev/null | wc -l)"
echo "  Assigned Pods: $(kubectl get pods -n $NAMESPACE -l pool-type=assigned --no-headers 2>/dev/null | wc -l)"
echo ""
echo "All test pods:"
kubectl get pods -n $NAMESPACE -l app=wordpress-clone 2>/dev/null || echo "  No clone pods remaining"
echo ""
echo "================================================================================"
echo "DONE"
echo "================================================================================"
