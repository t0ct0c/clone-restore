# MCP Server Configuration for OpenCode

## Successfully Configured MCP Servers

All 7 MCP servers are now configured and connected:

### 1. **fetch** ✅
- **Package**: `mcp-server-fetch` (Python/uvx)
- **Purpose**: Web content fetching and conversion for efficient LLM usage
- **Status**: Connected

### 2. **memory** ✅  
- **Package**: `@modelcontextprotocol/server-memory` (Node.js/npx)
- **Purpose**: Knowledge graph-based persistent memory system
- **Status**: Connected

### 3. **filesystem** ✅
- **Package**: `@modelcontextprotocol/server-filesystem` (Node.js/npx)
- **Purpose**: Secure file operations with configurable access controls
- **Root Directory**: `/home/chaz`
- **Status**: Connected

### 4. **eks** ✅
- **Package**: `awslabs.eks-mcp-server` (Python/uvx)
- **Purpose**: AWS EKS cluster management with write and sensitive data access
- **Environment**: 
  - AWS_REGION: us-east-1
  - AWS_DEFAULT_REGION: us-east-1
- **Status**: Connected

### 5. **terraform** ✅
- **Package**: `awslabs.terraform-mcp-server` (Python/uvx)
- **Purpose**: Terraform infrastructure management
- **Status**: Connected

### 6. **code-index** ✅
- **Package**: `code-index-mcp` (Python/uvx)
- **Purpose**: Semantic code search and indexing for better codebase understanding
- **Status**: Connected

### 7. **sequential-thinking** ✅
- **Package**: `@modelcontextprotocol/server-sequential-thinking` (Node.js/npx)
- **Purpose**: Enhanced reasoning through structured, step-by-step thinking process
- **Status**: Connected

## Configuration Files

### Global Configuration
**Location**: `/home/chaz/opencode.json`

This configuration applies to all OpenCode sessions system-wide.

### Project Configuration  
**Location**: `/home/chaz/Desktop/clone-restore/opencode.json`

This configuration applies when working in this specific project directory.

Both files have identical MCP server configurations.

## How to Use

### Starting a New OpenCode Session
To use these MCP servers, **restart OpenCode** or start a new session:

```bash
opencode
```

The MCP servers will be automatically loaded and available as tools in your AI assistant.

### Checking MCP Server Status
```bash
# In project directory
cd /home/chaz/Desktop/clone-restore
opencode mcp list

# Globally
cd ~
opencode mcp list
```

### Testing MCP Servers
Once you start a new OpenCode session, the AI assistant will have access to additional tools from these MCP servers:

- **fetch tools**: Fetch and convert web content
- **memory tools**: Store and retrieve persistent knowledge
- **filesystem tools**: Read/write files securely within `/home/chaz`
- **eks tools**: Manage EKS clusters, pods, services, deployments
- **terraform tools**: Plan, apply, and manage Terraform infrastructure
- **code-index tools**: Perform semantic code search and analyze code structure
- **sequential-thinking tools**: Engage in structured reasoning for complex problem-solving

## Important Notes

1. **Current Session**: The MCP servers are configured but not available in THIS conversation session. You need to start a **new OpenCode session** to access them.

2. **AWS Credentials**: The eks and terraform servers require valid AWS credentials configured in `~/.aws/credentials` with appropriate permissions for us-east-1 region.

3. **Security**: The filesystem server is restricted to `/home/chaz` directory for security.

4. **Package Management**: 
   - Python packages (fetch, eks, terraform) are managed via `uvx` (uv's execution tool)
   - Node.js packages (memory, filesystem) are managed via `npx` (npm's execution tool)

## Troubleshooting

If servers show as "failed":

1. Check package installation:
   ```bash
   uvx mcp-server-fetch --version
   npx -y @modelcontextprotocol/server-memory --version
   ```

2. Check AWS credentials (for eks/terraform):
   ```bash
   aws configure list
   aws sts get-caller-identity
   ```

3. View detailed logs in OpenCode with `--log-level DEBUG`

## Next Steps

To start using the MCP servers:

1. Exit the current OpenCode session
2. Start a new session: `opencode`
3. The AI assistant will now have access to all 5 MCP server tools

