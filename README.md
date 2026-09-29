# Drive-Thru Voice Ordering

A voice-powered drive-thru ordering app built with Amazon Nova Sonic, Strands Agents SDK, and React. Customers talk to an AI attendant who takes their order, browses the menu, and manages the entire UI — all through natural conversation.

![Screenshot](screenshot.png)

## Demo

<video src="demo.mp4" controls width="100%"></video>

## Architecture

![Architecture Diagram](architecture.png)

**Key design decisions:**
- **Agent controls the UI** — the agent has a single `update_ui` tool that sets the entire frontend display state. The frontend just renders what it receives.
- **No direct AWS calls from browser** — the frontend doesn't talk to DynamoDB or S3 directly. All data flows through the agent via WebSocket.
- **JSON protocol** — all WebSocket communication is JSON (audio is base64-encoded). Strands BidiAgent handles routing natively.
- **OAuth auth** — Cognito JWT token via `Sec-WebSocket-Protocol` header for WebSocket authentication.

## Prerequisites

- Node.js 18+
- Python 3.11+
- Docker (for building the agent container)
- AWS CLI configured with credentials
- AWS CDK CLI (`npm install -g aws-cdk`)
- Amazon Bedrock Nova Sonic access in us-east-1

## Project Structure

```
agent/            – Strands BidiAgent (FastAPI + Nova Sonic, containerized)
frontend/         – React SPA (Vite + TypeScript)
cdk/              – Two CDK stacks (BackendStack + FrontendStack)
data/             – Menu data (JSON) and food images
deploy.sh         – One-command deploy
generate_config.py – Generates frontend config from CDK outputs
```

## Deploy

### One command

```bash
./deploy.sh
```

This runs five steps:
1. Builds the frontend
2. Deploys BackendStack (DynamoDB, S3, CloudFront, Cognito, AgentCore Runtime, seeds menu data + images)
3. Generates `frontend/public/runtime-config.json` from backend outputs
4. Deploys FrontendStack (uploads to S3, invalidates CloudFront)
5. Runs `smoke_test.py` against the live site

The smoke test checks what a browser actually hits, which a healthy CloudFormation stack doesn't guarantee: the Content-Security-Policy allows the Cognito and agent endpoints, `runtime-config.json` matches the stack, every menu image is served as an image, and the agent WebSocket rejects unauthenticated clients. Run it on its own any time with `python3 smoke_test.py`.

### Step by step

```bash
# 1. Deploy backend
cd cdk
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cdk bootstrap    # first time only
cdk deploy BackendStack --outputs-file backend-outputs.json

# 2. Generate frontend config
cd ..
python generate_config.py

# 3. Build frontend
cd frontend && npm ci && npm run build && cd ..

# 4. Deploy frontend
cd cdk
BUCKET=$(python3 -c "import json; print(json.load(open('backend-outputs.json'))['BackendStack']['HostingBucketName'])")
DIST=$(python3 -c "import json; print(json.load(open('backend-outputs.json'))['BackendStack']['DistributionId'])")
cdk deploy FrontendStack --context hostingBucketName="$BUCKET" --context distributionId="$DIST"
```

## Create a Cognito User

```bash
aws cognito-idp admin-create-user \
  --user-pool-id <UserPoolId> \
  --username your@email.com \
  --temporary-password TempPass123! \
  --user-attributes Name=email,Value=your@email.com Name=email_verified,Value=true

aws cognito-idp admin-set-user-password \
  --user-pool-id <UserPoolId> \
  --username your@email.com \
  --password YourPassword123! \
  --permanent
```

## How It Works

1. **Sign in** → Cognito Authenticator handles sign-in and password reset (accounts are created by an admin, see above)
2. **Start Your Order** → big centered button, connects WebSocket to AgentCore
3. **Agent loads menu** → calls `load_menu` tool, sends full menu to frontend via `update_ui`
4. **Voice conversation** → bidirectional audio streaming with Nova Sonic
5. **Agent controls the screen** → highlights categories, shows item details, updates order panel
6. **Build Your Own Burger** → interactive burger builder modal with real-time visual assembly
7. **Place order** → agent persists to DynamoDB, shows confirmation

## Sample Menu

Seeded automatically on deploy from `data/menu_items.json`:

| Category | Items |
|----------|-------|
| Build Your Own | Build Your Own Burger (custom patty + toppings) |
| Burgers  | Classic Burger, Cheeseburger, Double Burger, Veggie Burger |
| Chicken  | Crispy Chicken Sandwich, Spicy Chicken, Nuggets 6pc/10pc |
| Sides    | French Fries, Onion Rings, Mozzarella Sticks, Side Salad |
| Drinks   | Cola, Lemonade, Iced Tea, Chocolate/Vanilla Milkshake |
| Desserts | Apple Pie, Hot Fudge Sundae, Chocolate Chip Cookie |

Edit `data/menu_items.json` and redeploy to update.

## Local Development

```bash
cd frontend
npm install
npm run dev
```

Create `frontend/public/runtime-config.json` with your deployed resource IDs for local dev.

## Agent Tools

| Tool | Purpose |
|------|---------|
| `load_menu` | Loads full menu from DynamoDB, sends to frontend |
| `get_categories` | Returns menu categories |
| `get_items_by_category` | Returns items in a category |
| `get_recommendations` | Returns featured items |
| `add_to_order` | Adds item with optional special instructions |
| `build_custom_burger` | Builds a custom burger with chosen patty, toppings, and sauces |
| `remove_from_order` | Removes item from order |
| `get_order_summary` | Returns current order |
| `place_order` | Persists order to DynamoDB |
| `cancel_order` | Clears the order |
| `update_ui` | Highlights a category or item, and shows the burger builder (the order, menu and all prices are written only by the tools above) |
| `get_ui_context` | Returns what the customer is looking at |

## Redeploying

```bash
./deploy.sh
```

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.