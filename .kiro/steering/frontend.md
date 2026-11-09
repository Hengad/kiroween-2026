---
inclusion: fileMatch
fileMatchPattern: '**/frontend/**'
---

# Svelte frontend conventions

## Split between core and apps

- `@siloless/ui` (`core/frontend`) provides the engine UI: app shell and navigation, the Chat view (communication channel with engine replies), the Tracked questions view (outcome, owner, status, claim, accept or decline, conflict resolution), the Work Item board for incidents and actions, the Process builder, notifications, a memory explorer, and the API and WebSocket clients.
- App frontends (`siloless-factory/frontend`, `siloless-festival/frontend`) compose the demo layout, provide branding and theme tokens, and register app panels (the live simulation view) through the shell's panel registry.
- If an app needs something generic, add it to `@siloless/ui` with a test instead of copying it.
- A view for a disabled component is not shown. The shell builds its navigation from the components the backend reports as enabled.

## Demo layout

- Split screen: the app's simulation panel on the left, the engine UI on the right, with a resizable divider.
- Both halves stay live at the same time; the engine UI updates as the simulation emits data.
- The user is a single persona shown as "You". Simulated workers appear as the other people in the chat and as assignees.

## Process builder

- Built with Svelte Flow (`@xyflow/svelte`, Svelte 5 version).
- The node palette and each node's configuration form are generated from the backend's node type registry. Do not hard-code node types in the frontend.
- Saving sends the graph to the backend, which validates it. Show validation errors on the affected nodes.
- A Process can be opened to show which path a recent Process Run took.

## Svelte 5

- Use runes (`$state`, `$derived`, `$effect`, `$props`) and snippets. Do not use legacy `export let`, `$:` or slots in new code.
- Keep components small and presentational. Data fetching and WebSocket handling live in `.svelte.ts` modules or SvelteKit `load` functions, not inside deeply nested components.
- Prefer `$derived` over `$effect`. Use `$effect` only for real side effects (subscriptions, DOM integration, canvas drawing).

## Data and API

- Use the generated OpenAPI types for every request and response.
- The UI never decides what a user is allowed to see. It renders what the backend returns; hiding something in the UI is not access control.
- Every answer, incident and Suggested Action shows its evidence and links to the cited Records.
- Live data (chat messages, Work Item changes, Signals, notifications, simulation state) arrives over WebSocket. Handle reconnects and show connection state.

## Quality

- Accessible by default: semantic HTML, labelled controls, keyboard navigation, visible focus, sufficient contrast. Do not convey severity or status by color alone.
- Simulation views draw with SVG or Canvas and must stay smooth with the expected number of agents; throttle rendering rather than reactive updates per agent.
- Component tests with Testing Library query by role and label, not by CSS class.
