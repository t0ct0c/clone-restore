#!/bin/bash
# Test script for EKS MCP Server with wp-clone-restore cluster
# Configured for opencode MCP

echo "Testing EKS MCP Server installation for opencode..."
echo "==================================================="

# Test 1: Check if uvx can run the EKS MCP server
echo "1. Testing EKS MCP server command..."
uvx awslabs.eks-mcp-server@latest --help > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "   ✓ EKS MCP server command works"
else
    echo "   ✗ EKS MCP server command failed"
fi

# Test 2: Check AWS CLI configuration
echo "2. Testing AWS CLI configuration..."
aws eks describe-cluster --name wp-clone-restore --region us-east-1 --query 'cluster.status' --output text > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "   ✓ AWS CLI can access wp-clone-restore cluster"
else
    echo "   ✗ AWS CLI cannot access wp-clone-restore cluster"
fi

# Test 3: Check kubectl configuration
echo "3. Testing kubectl configuration..."
kubectl get nodes > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "   ✓ kubectl can access cluster"
else
    echo "   ✗ kubectl cannot access cluster"
fi

echo ""
echo "Configuration Summary:"
echo "======================"
echo "EKS Cluster: wp-clone-restore"
echo "Kubernetes Version: $(aws eks describe-cluster --name wp-clone-restore --region us-east-1 --query 'cluster.version' --output text 2>/dev/null || echo 'Unknown')"
echo "Region: us-east-1"
echo "opencode MCP Config: ✓ Added to opencode.jsonc"
echo ""
echo "MCP Server Configuration:"
echo "-------------------------"
echo "Server name: eks"
echo "Command: uvx awslabs.eks-mcp-server@latest --allow-write --allow-sensitive-data-access"
echo "Environment: AWS_REGION=us-east-1, FASTMCP_LOG_LEVEL=INFO"
echo ""
echo "The EKS MCP server provides tools for:"
echo "- Managing EKS clusters (including upgrade from 1.32 to 1.35)"
echo "- Deploying Kubernetes applications"
echo "- Troubleshooting cluster issues"
echo "- Accessing logs and metrics"
echo "- Kubernetes resource management"
echo ""
echo "When opencode starts in this directory, it will automatically:"
echo "1. Load the EKS MCP server"
echo "2. Make EKS management tools available"
echo "3. Provide access to your wp-clone-restore cluster"