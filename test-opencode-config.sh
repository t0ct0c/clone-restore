#!/bin/bash
echo "Testing opencode configuration..."
echo "================================"

# Test 1: Validate JSON syntax
echo "1. Validating JSON syntax..."
python3 -m json.tool opencode.jsonc > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "   ✓ JSON syntax is valid"
else
    echo "   ✗ JSON syntax error"
    exit 1
fi

# Test 2: Check if opencode-cli can parse config
echo "2. Testing opencode-cli config parsing..."
# Try to run opencode briefly to see if it accepts config
timeout 2 opencode-cli --config opencode.jsonc 2>&1 | grep -i "error\|invalid" > /tmp/opencode-test.txt
if [ $? -eq 124 ]; then
    echo "   ✓ opencode-cli started (timeout after 2 seconds)"
elif [ -s /tmp/opencode-test.txt ]; then
    echo "   ✗ opencode-cli reported error:"
    cat /tmp/opencode-test.txt | head -3
else
    echo "   ✓ opencode-cli accepted configuration"
fi

# Test 3: Check EKS MCP server command
echo "3. Testing EKS MCP server command..."
uvx awslabs.eks-mcp-server@latest --help > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "   ✓ EKS MCP server command works"
else
    echo "   ✗ EKS MCP server command failed"
fi

# Test 4: Check Terraform MCP server command
echo "4. Testing Terraform MCP server command..."
uvx awslabs.terraform-mcp-server@latest --help > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "   ✓ Terraform MCP server command works"
else
    echo "   ✗ Terraform MCP server command failed"
fi

# Test 5: Check AWS access
echo "5. Testing AWS CLI access..."
aws eks describe-cluster --name wp-clone-restore --region us-east-1 --query 'cluster.status' --output text > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "   ✓ AWS CLI can access wp-clone-restore cluster"
else
    echo "   ✗ AWS CLI cannot access wp-clone-restore cluster"
fi

echo ""
echo "Configuration Summary:"
echo "======================"
echo "MCP Server name: aws-eks-mcp"
echo "Command: uvx awslabs.eks-mcp-server@latest --allow-write --allow-sensitive-data-access"
echo "Environment: AWS_REGION=us-east-1, FASTMCP_LOG_LEVEL=INFO"
echo ""
echo "MCP Server name: terraform-mcp"
echo "Command: uvx awslabs.terraform-mcp-server@latest"
echo ""
echo "When you run opencode in this directory, it will:"
echo "1. Load the EKS MCP server configuration"
echo "2. Load the Terraform MCP server configuration"
echo "3. Start both MCP servers"
echo "4. Make EKS and Terraform management tools available"
echo ""
echo "Note: Configuration uses server name 'aws-eks-mcp' instead of 'eks'"
echo "to avoid potential conflicts with reserved names."