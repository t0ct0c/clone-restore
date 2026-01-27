# WordPress Clone & Restore System

## Architecture

```mermaid
graph TD
    A["User / API Client"] --> B["ALB<br/>wp-targets-alb-*.elb.amazonaws.com<br/>(Path-based routing)"]
    
    B -->|"/clone-xxx/*"| C["EC2 Instance 1"]
    B -->|"/clone-yyy/*"| D["EC2 Instance 2"]
    B -->|"/clone-zzz/*"| E["EC2 Instance 3"]
    
    C --> F["Nginx"]
    C --> G["MySQL Container"]
    F --> H["WordPress clone-xxx"]
    H --> G
    
    D --> I["Nginx"]
    D --> J["MySQL Container"]
    I --> K["WordPress clone-yyy"]
    K --> J
    
    E --> L["Nginx"]
    E --> M["MySQL Container"]
    L --> N["WordPress clone-zzz"]
    N --> M
    
    O["Management Server<br/>13.222.20.138:8000"] --> P["Browser Automation<br/>(Playwright)"]
    P --> Q["Source WordPress<br/>(e.g., bonnel.ai)"]
    O --> B
```

---

## Postman API Collection

### Request 1: Create Clone
- **Method**: `POST`
- **URL**: `http://13.222.20.138:8000/clone`
- **Headers**: 
  - `Content-Type: application/json`
- **Body** (raw JSON):
```json
{
  "source": {
    "url": "https://bonnel.ai",
    "username": "Charles",
    "password": "xkZ%HL6v5Z5)MP9K"
  }
}
```

### Request 2: Restore Clone to Production
- **Method**: `POST`
- **URL**: `http://13.222.20.138:8000/restore`
- **Headers**: 
  - `Content-Type: application/json`
- **Body** (raw JSON):
```json
{
  "source": {
    "url": "http://wp-targets-alb-1392351630.us-east-1.elb.amazonaws.com/clone-YYYYMMDD-HHMMSS",
    "username": "admin",
    "password": "password-from-clone-response"
  },
  "target": {
    "url": "https://betaweb.ai",
    "username": "Charles",
    "password": "xkZ%HL6v5Z5)MP9K"
  },
  "preserve_themes": false,
  "preserve_plugins": false
}
```

### Request 3: Test Clone REST API Export
- **Method**: `POST`
- **URL**: `http://wp-targets-alb-1392351630.us-east-1.elb.amazonaws.com/clone-YYYYMMDD-HHMMSS/index.php?rest_route=/custom-migrator/v1/export`
- **Headers**: 
  - `X-Migrator-Key: migration-master-key`
- **Body**: (empty)

### Request 4: Health Check
- **Method**: `GET`
- **URL**: `http://13.222.20.138:8000/health`
- **Headers**: (none needed)
- **Body**: (empty)
