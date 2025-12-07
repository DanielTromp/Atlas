# Setting Up Foreman API Token for Atlas

## Foreman Version 1.24.3

This guide explains how to create a Personal Access Token (PAT) in Foreman 1.24.3 for use with Atlas.

## Creating a Personal Access Token

### Method 1: Using the Foreman Web UI

1. **Log into Foreman** at `https://foreman.service.ispworks.net`
2. **Navigate to your user profile**:
   - Click on your username in the top-right corner
   - Select **"My Account"** or go to **Administer > Users** and select your user
3. **Go to Personal Access Tokens tab**:
   - Click on the **"Personal Access Tokens"** tab
   - Click **"Add Personal Access Token"** button
4. **Configure the token**:
   - Enter a descriptive **Name** (e.g., "Atlas Integration")
   - Optionally set an **Expires** date (leave blank for no expiration)
   - Click **"Submit"**
5. **Copy the token**:
   - **Important**: Copy the token immediately after creation
   - The token will be displayed only once and cannot be retrieved later
   - Store it securely

### Method 2: Using Hammer CLI

If you have `hammer` CLI installed:

```bash
hammer user access-token create --user <your_username> --name "Atlas Integration"
```

Replace `<your_username>` with your Foreman username.

### Method 3: Using the API

```bash
curl -X POST \
  --user <username>:<password> \
  -H "Content-Type: application/json" \
  -d '{"name": "Atlas Integration"}' \
  https://foreman.service.ispworks.net/api/v2/users/<user_id>/personal_access_tokens
```

## Adding Token to Atlas

Once you have your Personal Access Token, add it to Atlas using one of these methods:

### Using CLI

You can provide the token in two ways:

**Option 1: Combined format (username:token)**
```bash
uv run atlas foreman create \
  --name "ISPWorks Foreman" \
  --url "https://foreman.service.ispworks.net" \
  --token "danielt:srAJt2TsUO6sW_M0Fkdl8Q" \
  --verify-ssl
```

**Option 2: Separate username and token**
```bash
uv run atlas foreman create \
  --name "ISPWorks Foreman" \
  --url "https://foreman.service.ispworks.net" \
  --username "danielt" \
  --token "srAJt2TsUO6sW_M0Fkdl8Q" \
  --verify-ssl
```

**Note**: For Foreman 1.24.3, you can use either format:
- Combined: `--token "username:token"` (username and token separated by colon)
- Separate: `--username "username" --token "token"`

### Using API

```bash
curl -X POST http://localhost:8000/api/foreman/configs \
  -H "Authorization: Bearer <atlas_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ISPWorks Foreman",
    "base_url": "https://foreman.service.ispworks.net",
    "token": "<username>:<personal_access_token>",
    "verify_ssl": true
  }'
```

## Token Format

For Foreman 1.24.3, use HTTP Basic Authentication format:
- **Format**: `username:token`
- **Example**: `daniel:abc123xyz789token`

The Atlas integration will use this as Basic Auth credentials when making API requests to Foreman.

## Testing the Connection

After adding the token, test the connection:

```bash
uv run atlas foreman test <config_id>
```

Or via API:

```bash
curl -X GET http://localhost:8000/api/foreman/configs/<config_id>/test \
  -H "Authorization: Bearer <atlas_token>"
```

## Security Notes

1. **Store tokens securely**: Personal Access Tokens are sensitive credentials
2. **Use service accounts**: Consider creating a dedicated Foreman user for Atlas integration
3. **Set expiration dates**: For production, set token expiration dates
4. **Rotate tokens regularly**: Update tokens periodically for better security
5. **Limit permissions**: Grant only necessary permissions to the Foreman user

## Troubleshooting

### Authentication Errors

If you get authentication errors:
1. Verify the token format is `username:token`
2. Check that the token hasn't expired
3. Ensure the Foreman user has appropriate API permissions
4. Verify SSL certificate settings if using self-signed certs

### Token Not Found

If the token was lost:
- You'll need to create a new token (old tokens cannot be retrieved)
- Revoke the old token if possible
- Create a new token and update Atlas configuration

