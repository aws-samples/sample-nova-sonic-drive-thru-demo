# Drive-Thru Voice Ordering

A voice-powered drive-thru ordering app built with Amazon Nova Sonic, Strands Agents SDK, and React. Customers talk to an AI attendant who takes their order, browses the menu, and manages the entire UI — all through natural conversation.

![Screenshot](screenshot.png)

## Demo

<video src="demo.mp4" controls width="100%"></video>

## Architecture

![Architecture Diagram](architecture.png)

**Key design decisions:**
- **Voice only, server owns the screen** — customers only talk; the screen only displays. Each conversation's order and screen state live in a server-side session, and every tool that changes the screen sends the new state. The browser only ever sends microphone audio.
- **Survives dropped connections** — the browser keeps one AgentCore session ID per order and reconnects with it after a drop, which reaches the same session: the order, the screen and the conversation carry on.
- **No direct AWS calls from browser** — the frontend doesn't talk to DynamoDB or S3 directly. All data flows through the agent via WebSocket.
- **One typed protocol** — `agent/protocol.py` defines every WebSocket message once, as Pydantic models. Audio goes both ways as binary frames of raw 16 kHz mono 16-bit PCM, with no base64 or JSON around it. The server's other messages are JSON, shaped like [AG-UI](https://docs.ag-ui.com) events: a `CUSTOM` `menu` event once per connection, a `STATE_SNAPSHOT` with an `epoch` and `version` after every change (the browser ignores out-of-date ones), `bidi_interruption` to stop the agent's voice, and a `CUSTOM` `session_ended` event with the reason before the server closes a session. The browser's TypeScript types are generated from the models (see [Changing the protocol](#changing-the-protocol)).
- **Gapless playback** — each chunk of the agent's voice is scheduled on the Web Audio clock to start exactly when the previous one ends.
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
smoke_test.py     – Post-deploy check of the live site (run by deploy.sh)
.github/workflows – CI: agent, frontend and CDK tests on every push and pull request
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
3. **Server sets up the screen** → sends the menu and screen state, then the agent greets the customer
4. **Voice conversation** → bidirectional audio streaming with Nova Sonic
5. **Agent controls the screen** → shows items and categories, updates the order panel
6. **Build Your Own Burger** → burger builder modal that assembles the burger as the customer chooses
7. **Place order** → agent persists to DynamoDB and says goodbye; the confirmation shows briefly, then the screen resets for the next car

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

## Tests

CI runs these on every push to `main` and every pull request (`.github/workflows/ci.yml`). None of them need AWS access.

```bash
# Agent (DynamoDB is mocked with moto)
pip install -r agent/requirements.txt -r agent/requirements-dev.txt
python -m pytest agent

# Frontend
cd frontend && npm ci && npm run build && npm test && cd ..

# CDK (synthesizes both stacks; needs the frontend build above)
pip install -r cdk/requirements.txt
python -m pytest cdk/tests
```

### Changing the protocol

Edit the models in `agent/protocol.py`, then regenerate the schema and the browser's types:

```bash
python -m agent.protocol                     # writes frontend/src/protocol/protocol.schema.json
cd frontend && npm run gen:protocol && cd .. # writes frontend/src/protocol/messages.ts
```

CI fails if either file is out of date.

The CDK tests include regression checks for problems that only appear after deploying: an invalid Content-Security-Policy, the frontend deploy deleting the menu images, CloudFront serving missing files as the app page, open sign-up, and the agent's model drifting from its IAM grant.

## Agent Tools

The menu is in the agent's instructions and on screen from the start, so there is no tool to load it. Only these tools change the screen, and only the server sets prices.

| Tool | Purpose |
|------|---------|
| `show_item` | Shows an item's details on screen and returns them |
| `show_category` | Scrolls the screen to a category and returns its items |
| `get_recommendations` | Returns featured items |
| `add_to_order` | Adds item with optional special instructions |
| `remove_from_order` | Removes item from order |
| `get_order_summary` | Returns current order |
| `place_order` | Persists order to DynamoDB |
| `cancel_order` | Clears the order |
| `update_custom_burger` | Starts or changes the build-your-own burger (patty, toppings, sauces), shown in the builder |
| `confirm_custom_burger` | Adds the build-your-own burger to the order |
| `cancel_custom_burger` | Throws the build-your-own burger away |
| `stop_conversation` | Built-in Strands tool that ends the conversation |

## Redeploying

```bash
./deploy.sh
```

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.