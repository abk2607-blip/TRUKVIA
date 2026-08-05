# Auth Testing Playbook (Emergent Google OAuth)

## Step 1: Create Test User & Session in MongoDB

```bash
mongosh --eval "
use('test_database');
var userId = 'test-user-' + Date.now();
var sessionToken = 'test_session_' + Date.now();
db.users.insertOne({
  user_id: userId,
  email: 'test.user.' + Date.now() + '@example.com',
  name: 'Test Owner',
  picture: 'https://via.placeholder.com/150',
  created_at: new Date().toISOString()
});
db.user_sessions.insertOne({
  user_id: userId,
  session_token: sessionToken,
  expires_at: new Date(Date.now() + 7*24*60*60*1000).toISOString(),
  created_at: new Date().toISOString()
});
print('Session token: ' + sessionToken);
print('User ID: ' + userId);
"
```

## Step 2: Backend API Tests

```bash
API_URL=$(grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d '=' -f2)

# /api/auth/me
curl -s -X GET "$API_URL/api/auth/me" -H "Authorization: Bearer YOUR_SESSION_TOKEN"

# /api/dashboard
curl -s -X GET "$API_URL/api/dashboard" -H "Authorization: Bearer YOUR_SESSION_TOKEN"

# /api/customers (POST)
curl -s -X POST "$API_URL/api/customers" -H "Authorization: Bearer YOUR_SESSION_TOKEN" -H "Content-Type: application/json" -d '{"name":"Test Customer","gstin":"37ABCDE1234F1Z5","state":"Andhra Pradesh"}'

# /api/trips (POST)
curl -s -X POST "$API_URL/api/trips" -H "Authorization: Bearer YOUR_SESSION_TOKEN" -H "Content-Type: application/json" -d '{"customer_id":"CUST_ID","date":"2026-02-01","vehicle_number":"AP16TA1234","tons":25.5,"freight_mode":"per_ton","rate_per_ton":1200,"expenses":{"diesel":8000,"toll":500,"batta":1000,"repair":0,"other":0}}'
```

## Step 3: Browser Test (Playwright)

```python
await page.context.add_cookies([{
    "name": "session_token",
    "value": "YOUR_SESSION_TOKEN",
    "domain": "trip-billing-pro-1.preview.emergentagent.com",
    "path": "/",
    "httpOnly": True,
    "secure": True,
    "sameSite": "None"
}])
await page.goto("https://trip-billing-pro-1.preview.emergentagent.com/dashboard")
```

## Cleanup

```bash
mongosh --eval "
use('test_database');
db.users.deleteMany({email: /test\.user\./});
db.user_sessions.deleteMany({session_token: /test_session/});
db.customers.deleteMany({name: /^Test Customer/});
db.trips.deleteMany({vehicle_number: 'AP16TA1234'});
db.invoices.deleteMany({});
db.companies.deleteMany({});
"
```

## Success Indicators
- ✅ /api/auth/me returns user data
- ✅ /api/dashboard returns stats
- ✅ Cookie-based auth works for protected routes
