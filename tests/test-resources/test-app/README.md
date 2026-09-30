# Test Application

A simple login test application for testing the QA Agent's authentication capabilities.

## Test Credentials

- **Email**: `test@example.com`
- **Password**: `SecurePass123!`

## Files

- `login.html` - Login page with form validation
- `dashboard.html` - Protected dashboard page (requires authentication)

## Running the Test App

```bash
cd tests/test-resources/test-app
uv run python -m http.server 8080
```

Then open: http://localhost:8080/login.html

## Testing with QA Agent

### 1. Store Credentials

```python
import asyncio
from src.auth.credential_storage import CredentialStorage
from src.database.database import AppDatabase

db = AppDatabase.getInstance()
storage = CredentialStorage(db.getDatabase())
asyncio.run(storage.set("testapp", {
    "email": "test@example.com",
    "password": "SecurePass123!",
}))
```

### 2. Configure Agent with Authentication

```python
import asyncio
from src.agents.exploratory import ExploratoryAgent

agent = ExploratoryAgent({
    "baseUrl": "http://localhost:8080/login.html",
    "auth": {
        "required": True,
        "appIdentifier": "testapp",
        "autoLogin": True,
    },
})
asyncio.run(agent.start())
```

### 3. Or Use Environment Variables

```bash
# .env
AUTH_TESTAPP_EMAIL=test@example.com
AUTH_TESTAPP_PASSWORD=SecurePass123!
```

## Features

- ✅ Modern, responsive design
- ✅ Form validation
- ✅ Success/Error messages
- ✅ Session persistence (localStorage)
- ✅ Protected dashboard route
- ✅ Logout functionality
- ✅ Test credentials displayed on login page

## Authentication Flow

1. User enters credentials on `login.html`
2. JavaScript validates against hardcoded credentials
3. On success: Sets `localStorage` and redirects to `dashboard.html`
4. On failure: Shows error message
5. Dashboard checks `localStorage` and redirects to login if not authenticated
6. Logout clears `localStorage` and redirects to login
