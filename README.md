# WordPress Clone & Restore System

## Architecture

```mermaid
graph TD
    A["User / API Client"] --> B["Management Server<br/>13.222.20.138:8000"]
    
    B --> C["Browser Automation<br/>(Playwright)"]
    C --> D["Source WordPress<br/>(e.g., bonnel.ai)"]
    
    B --> E["Target EC2<br/>10.0.13.72"]
    E --> F["MySQL Container<br/>(Shared DB)"]
    E --> G["Clone Container 1<br/>(WordPress + Apache)"]
    E --> H["Clone Container 2<br/>(WordPress + Apache)"]
    E --> I["Nginx<br/>(Reverse Proxy)"]
    
    J["ALB<br/>wp-targets-alb-*.elb.amazonaws.com"] --> I
    I --> G
    I --> H
    
    G --> F
    H --> F
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
