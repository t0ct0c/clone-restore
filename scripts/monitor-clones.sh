#!/bin/bash
# Real-time clone system monitor
# Shows queue depth, processing status, and completion rate

NAMESPACE="wordpress-staging"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

while true; do
    clear
    echo "================================================================================"
    echo "                    CLONE SYSTEM MONITOR - $(date '+%H:%M:%S')"
    echo "================================================================================"
    echo ""
    
    # Get Redis password
    REDIS_PASSWORD=$(kubectl get secret redis -n $NAMESPACE -o jsonpath='{.data.redis-password}' | base64 -d 2>/dev/null)
    
    # Queue depth
    QUEUE_DEPTH=$(kubectl exec -n $NAMESPACE redis-master-0 -- redis-cli -a "$REDIS_PASSWORD" --no-auth-warning LLEN "dramatiq:clone-queue" 2>/dev/null || echo "0")
    
    # Pod counts
    WARM_PODS=$(kubectl get pods -n $NAMESPACE -l pool-type=warm --no-headers 2>/dev/null | wc -l)
    ASSIGNED_PODS=$(kubectl get pods -n $NAMESPACE -l pool-type=assigned --no-headers 2>/dev/null | wc -l)
    TOTAL_CLONE_PODS=$(kubectl get pods -n $NAMESPACE -l app=wordpress-clone --no-headers 2>/dev/null | wc -l)
    
    # Test deployments (completed clones)
    TEST_DEPLOYMENTS=$(kubectl get deployments -n $NAMESPACE -l app=wordpress-clone --no-headers 2>/dev/null | wc -l)
    
    # Problem pods
    CRASH_PODS=$(kubectl get pods -n $NAMESPACE --no-headers 2>/dev/null | grep -c "CrashLoopBackOff" || echo "0")
    ERROR_PODS=$(kubectl get pods -n $NAMESPACE --no-headers 2>/dev/null | grep -c "Error" || echo "0")
    PENDING_PODS=$(kubectl get pods -n $NAMESPACE --no-headers 2>/dev/null | grep -c "Pending" || echo "0")
    
    # Calculate processing
    PROCESSING=$((ASSIGNED_PODS - TEST_DEPLOYMENTS))
    if [ $PROCESSING -lt 0 ]; then
        PROCESSING=0
    fi
    
    # Display status
    echo "📊 QUEUE STATUS:"
    if [ "$QUEUE_DEPTH" -gt 0 ]; then
        echo -e "  ${YELLOW}⏳ Jobs in queue: $QUEUE_DEPTH${NC}"
    else
        echo -e "  ${GREEN}✓ Queue is empty${NC}"
    fi
    echo ""
    
    echo "🔄 PROCESSING STATUS:"
    if [ "$PROCESSING" -gt 0 ]; then
        echo -e "  ${BLUE}⚙️  Currently processing: $PROCESSING${NC}"
    else
        echo "  ⚙️  Currently processing: 0"
    fi
    echo ""
    
    echo "📦 PODS:"
    echo "  🔵 Warm pool (ready): $WARM_PODS"
    echo "  🟡 Assigned (in use): $ASSIGNED_PODS"
    echo "  📊 Total clone pods: $TOTAL_CLONE_PODS"
    echo ""
    
    echo "✅ COMPLETED:"
    if [ "$TEST_DEPLOYMENTS" -gt 0 ]; then
        echo -e "  ${GREEN}✓ Finished clones: $TEST_DEPLOYMENTS${NC}"
    else
        echo "  ✓ Finished clones: 0"
    fi
    echo ""
    
    # Problems
    if [ "$CRASH_PODS" -gt 0 ] || [ "$ERROR_PODS" -gt 0 ] || [ "$PENDING_PODS" -gt 0 ]; then
        echo "⚠️  PROBLEMS:"
        [ "$CRASH_PODS" -gt 0 ] && echo -e "  ${RED}✗ CrashLoopBackOff: $CRASH_PODS${NC}"
        [ "$ERROR_PODS" -gt 0 ] && echo -e "  ${RED}✗ Error: $ERROR_PODS${NC}"
        [ "$PENDING_PODS" -gt 0 ] && echo -e "  ${YELLOW}⏸  Pending: $PENDING_PODS${NC}"
        
        if [ "$CRASH_PODS" -gt 0 ]; then
            echo ""
            echo "  Crashed pods:"
            kubectl get pods -n $NAMESPACE --no-headers 2>/dev/null | grep "CrashLoopBackOff" | awk '{print "    - " $1 " (Age: " $5 ")"}'
        fi
        echo ""
    fi
    
    # Worker stats
    echo "💻 WORKER STATUS:"
    WP_REPLICAS=$(kubectl get deployment wp-k8s-service -n $NAMESPACE -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "0")
    WP_READY=$(kubectl get deployment wp-k8s-service -n $NAMESPACE -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    echo "  Replicas: $WP_READY/$WP_REPLICAS ready"
    
    WP_RESOURCES=$(kubectl top pod -n $NAMESPACE -l app=wp-k8s-service --no-headers 2>/dev/null)
    if [ ! -z "$WP_RESOURCES" ]; then
        CPU=$(echo "$WP_RESOURCES" | awk '{print $2}')
        MEM=$(echo "$WP_RESOURCES" | awk '{print $3}')
        echo "  CPU: $CPU | Memory: $MEM"
    fi
    echo ""
    
    # Progress summary
    echo "================================================================================"
    TOTAL_JOBS=$((QUEUE_DEPTH + PROCESSING + TEST_DEPLOYMENTS))
    if [ "$TOTAL_JOBS" -gt 0 ]; then
        COMPLETED_PCT=$((TEST_DEPLOYMENTS * 100 / TOTAL_JOBS))
        PROCESSING_PCT=$((PROCESSING * 100 / TOTAL_JOBS))
        QUEUED_PCT=$((QUEUE_DEPTH * 100 / TOTAL_JOBS))
        
        echo "PROGRESS: Total jobs detected: $TOTAL_JOBS"
        echo ""
        echo "  Completed: $TEST_DEPLOYMENTS ($COMPLETED_PCT%)"
        echo "  Processing: $PROCESSING ($PROCESSING_PCT%)"
        echo "  Queued: $QUEUE_DEPTH ($QUEUED_PCT%)"
        echo ""
        
        # Progress bar
        BAR_WIDTH=60
        COMPLETED_BARS=$((COMPLETED_PCT * BAR_WIDTH / 100))
        PROCESSING_BARS=$((PROCESSING_PCT * BAR_WIDTH / 100))
        QUEUED_BARS=$((QUEUED_PCT * BAR_WIDTH / 100))
        
        echo -n "  ["
        for i in $(seq 1 $COMPLETED_BARS); do echo -n "█"; done
        for i in $(seq 1 $PROCESSING_BARS); do echo -n "▒"; done
        for i in $(seq 1 $QUEUED_BARS); do echo -n "░"; done
        REMAINING=$((BAR_WIDTH - COMPLETED_BARS - PROCESSING_BARS - QUEUED_BARS))
        for i in $(seq 1 $REMAINING); do echo -n " "; done
        echo "]"
        echo ""
        echo "  Legend: █ Completed  ▒ Processing  ░ Queued"
    else
        echo "No active jobs detected"
    fi
    echo "================================================================================"
    echo ""
    echo "Press Ctrl+C to exit | Refreshing every 5 seconds..."
    
    sleep 5
done
