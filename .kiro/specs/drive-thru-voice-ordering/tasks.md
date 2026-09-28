# Implementation Plan: Drive-Thru Voice Ordering

## Overview

Incremental implementation of a drive-thru voice ordering system with a React/TypeScript frontend and Python Strands BidiAgent backend. Tasks are ordered to build foundational infrastructure first, then data layer, agent tools, frontend components, and finally integration wiring.

## Tasks

- [x] 1. Set up CDK infrastructure stack
  - [x] 1.1 Create the CDK app entry point and `DriveThruVoiceOrderingStack` class with DynamoDB menu table (`DriveThruMenu` with PK/SK schema), DynamoDB orders table (`DriveThruOrders` with orderId partition key), S3 buckets for food images and frontend hosting, and CloudFront distribution with OAI
    - Provision all DynamoDB tables, S3 buckets, and CloudFront distribution per the design
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.11_

  - [x] 1.2 Add Cognito User Pool, Identity Pool with authenticated role, and IAM policies
    - User Pool for customer auth, Identity Pool federated with User Pool
    - Authenticated role with read-only DynamoDB menu table access and S3 images read access
    - _Requirements: 7.6, 7.7, 7.10_

  - [x] 1.3 Add AgentCore Runtime endpoint configuration and agent IAM permissions
    - Grant agent permissions for Bedrock Nova Sonic invocation, DynamoDB orders/menu access, S3 images read
    - _Requirements: 7.8, 7.9_

  - [x] 1.4 Write CDK snapshot tests
    - Synthesize the stack and snapshot the CloudFormation template
    - Verify resource counts and types
    - _Requirements: 7.1–7.11_

- [x] 2. Checkpoint - Ensure CDK stack synthesizes cleanly
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Implement Python agent data models and order state
  - [x] 3.1 Create `OrderState` and `OrderLineItem` dataclasses and order state management logic
    - Implement in-memory order state with add, remove, cancel, summary, and place operations
    - Compute totals as sum of quantity × unit_price in fils
    - _Requirements: 3.2, 3.3, 3.5, 3.6, 4.2, 4.3, 4.4, 6.1_

  - [x] 3.2 Write property test: add_to_order correctly updates order state
    - **Property 5: add_to_order correctly updates order state**
    - **Validates: Requirements 3.2, 3.3**

  - [x] 3.3 Write property test: remove_from_order correctly reduces order state
    - **Property 6: remove_from_order correctly reduces order state**
    - **Validates: Requirements 3.5**

  - [x] 3.4 Write property test: cancel_order clears all items
    - **Property 7: cancel_order clears all items**
    - **Validates: Requirements 4.4**

  - [x] 3.5 Write property test: place_order produces a complete order record
    - **Property 9: place_order produces a complete order record**
    - **Validates: Requirements 6.1, 6.3**

- [x] 4. Implement Python agent Menu Tools
  - [x] 4.1 Implement `get_categories`, `get_items_by_category`, `get_item_details`, and `get_recommendations` tools with DynamoDB queries
    - Use `@tool` decorator from Strands SDK
    - Query DynamoDB menu table using PK/SK access patterns from the design
    - _Requirements: 5.2, 8.1, 8.2, 8.3, 8.7_

  - [x] 4.2 Write property test: get_categories returns all distinct categories
    - **Property 10: get_categories returns all distinct categories**
    - **Validates: Requirements 8.1**

  - [x] 4.3 Write property test: get_items_by_category returns only matching items
    - **Property 11: get_items_by_category returns only matching items**
    - **Validates: Requirements 8.2**

  - [x] 4.4 Write property test: get_item_details returns complete item data
    - **Property 12: get_item_details returns complete item data**
    - **Validates: Requirements 8.3**

  - [x] 4.5 Write property test: get_recommendations returns only featured items
    - **Property 13: get_recommendations returns only featured items**
    - **Validates: Requirements 8.7**

- [x] 5. Implement Python agent Order Tools with UI_Event emission
  - [x] 5.1 Implement `add_to_order`, `remove_from_order`, `get_order_summary`, `place_order`, and `cancel_order` tools
    - Each tool updates in-memory OrderState and returns updated order state
    - `place_order` persists to DynamoDB orders table and generates UUID order number
    - Validate item_id against menu table before adding; quantity must be ≥ 1
    - _Requirements: 3.2, 3.3, 3.5, 4.2, 4.3, 4.4, 6.1, 6.2, 6.3_

  - [x] 5.2 Add UI_Event emission to all order tools and menu tools
    - Order tools emit `order_update` UI_Events after each invocation
    - `place_order` emits `order_confirmed` UI_Event
    - Menu tools emit `highlight_category`, `browse_category`, `highlight_item` UI_Events as appropriate
    - _Requirements: 11.1, 11.3, 11.4, 11.5, 11.6, 11.7_

  - [x] 5.3 Write property test: Order tools emit order_update UI_Events
    - **Property 17: Order tools emit order_update UI_Events**
    - **Validates: Requirements 11.3**

- [x] 6. Set up BidiAgent with Nova Sonic and tool registration
  - [x] 6.1 Create the Strands BidiAgent entry point with BidiNovaSonicModel, register all menu and order tools, configure system prompt for drive-thru persona
    - Configure idle timeout prompts (30s and 60s)
    - Include UI_State parsing for deictic reference resolution
    - _Requirements: 2.3, 3.1, 3.4, 3.7, 8.6, 8.8, 9.2, 9.3, 11.13_

- [x] 7. Checkpoint - Ensure all agent tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Set up frontend project and auth module
  - [x] 8.1 Initialize Vite + React + TypeScript project with Vitest, React Testing Library, and fast-check
    - Configure jsdom test environment
    - Define TypeScript interfaces: `Category`, `MenuItem`, `OrderItem`, `UIEvent`, `UIState`, `AppState`
    - _Requirements: 1.1, 11.1, 11.9_

  - [x] 8.2 Implement `AuthProvider` with Cognito sign-in, sign-out, JWT token management, identity pool credential retrieval, and silent token refresh
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

- [x] 9. Implement frontend state store and UI_Event/UI_State protocol
  - [x] 9.1 Create state store (Zustand or React Context) implementing `AppState` interface with reducers for each UI_Event type
    - Handle `order_update`, `browse_category`, `highlight_item`, `highlight_category`, `order_confirmed` events
    - _Requirements: 4.1, 4.5, 8.4, 8.5, 11.8_

  - [x] 9.2 Write property test: UI_Event processing updates state store correctly
    - **Property 8: UI_Event processing updates state store correctly**
    - **Validates: Requirements 4.1, 4.5, 8.4, 8.5**

  - [x] 9.3 Write property test: Protocol message serialization round-trip
    - **Property 15: Protocol message serialization round-trip**
    - **Validates: Requirements 11.1, 11.9**

  - [x] 9.4 Write property test: Session end preserves order items
    - **Property 14: Session end preserves order items**
    - **Validates: Requirements 9.4**

- [x] 10. Implement frontend MenuService and menu display components
  - [x] 10.1 Implement `MenuService` that reads menu data from DynamoDB using Cognito identity pool credentials via AWS SDK
    - Parse DynamoDB items into `MenuItem` and `Category` types
    - Handle DynamoDB unreachable error with error banner
    - _Requirements: 1.1, 1.4, 5.1, 5.3_

  - [x] 10.2 Build menu display components: category list, menu item cards with name, description, formatted price, and food image from S3/CloudFront
    - Organize items into categories with consistent image sizing
    - Support highlighting categories and items from state store
    - _Requirements: 1.2, 1.3, 1.5, 8.4, 8.5_

  - [x] 10.3 Write property test: Menu data parsing produces complete MenuItems
    - **Property 1: Menu data parsing produces complete MenuItems**
    - **Validates: Requirements 1.1, 5.3**

  - [x] 10.4 Write property test: Menu item rendering includes all required information
    - **Property 2: Menu item rendering includes all required information**
    - **Validates: Requirements 1.2**

  - [x] 10.5 Write property test: Category grouping correctness
    - **Property 3: Category grouping correctness**
    - **Validates: Requirements 1.3**

- [x] 11. Implement WebSocket client and voice session manager
  - [x] 11.1 Implement `WebSocketClient` with connection to AgentCore Runtime using JWT, binary/text frame demultiplexing, auto-reconnect within 5 seconds with exponential backoff (max 3 retries)
    - _Requirements: 2.3, 9.1, 11.2_

  - [x] 11.2 Implement `VoiceSessionManager` with microphone access (MediaStream API), audio encoding/sending, audio playback from received binary frames, start/stop session controls
    - Show listening indicator when session is active
    - Handle mic permission denied with user message
    - _Requirements: 2.1, 2.2, 2.4, 2.5, 9.4_

  - [x] 11.3 Implement UI_State sending: initial state on WebSocket connect, category scroll events, item tap/click events
    - _Requirements: 11.9, 11.10, 11.11, 11.12_

  - [x] 11.4 Write property test: WebSocket message demultiplexing
    - **Property 16: WebSocket message demultiplexing**
    - **Validates: Requirements 11.2**

  - [x] 11.5 Write property test: Active voice session shows listening indicator
    - **Property 4: Active voice session shows listening indicator**
    - **Validates: Requirements 2.5**

  - [x] 11.6 Write property test: User interaction sends UI_State with current context
    - **Property 18: User interaction sends UI_State with current context**
    - **Validates: Requirements 11.11, 11.12**

- [x] 12. Implement order summary panel and confirmation screen
  - [x] 12.1 Build order summary panel that reactively renders from state store showing item names, quantities, individual prices, and total
    - Build order confirmation screen triggered by `order_confirmed` UI_Event showing order number and details
    - _Requirements: 4.1, 4.5_

- [x] 13. Wire all frontend components together
  - [x] 13.1 Compose the full application: AuthProvider wrapping app, menu display with voice session controls, order summary panel, WebSocket integration, and state store connecting all components
    - Ensure session end returns to menu browsing state while preserving order items
    - _Requirements: 9.4, 10.1, 10.3, 11.8_

- [x] 14. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Frontend uses TypeScript with Vitest + fast-check for property tests
- Agent tools use Python with pytest + Hypothesis for property tests
- CDK stack uses Python with pytest for snapshot tests
- Each property test references a specific correctness property from the design document
- Checkpoints ensure incremental validation at infrastructure, agent, and integration boundaries
