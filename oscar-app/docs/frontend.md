# Frontend (UI)

React 18 + Vite + Tailwind CSS — policy browser and interactive criteria tree renderer.

## Layout

```
┌─────────────────────────────────────────────────────────────┐
│  Oscar Guidelines Explorer                                   │
├──────────────────┬──────────────────────────────────────────┤
│  [Pipeline Ctrls]│                                          │
│  [Discover]      │  Policy Title                            │
│  [Download]      │  ○──●──●──●  (state bar)                │
│  [Structure]     │  [Extract Now] [Re-extract]              │
│                  │                                          │
│  Filter: [All]   │  [Tree] [Text] [Metadata]  ← tabs       │
│  [Structured]    │                                          │
│  [Downloaded]    │  [AND] All of the following              │
│  [Failed]        │   ├── ● Informed consent                 │
│                  │   ├── [OR] BMI criteria                  │
│  ┌────────────┐  │   │   ├── ● BMI ≥ 40                    │
│  │ Policy 1 ✓ │  │   │   └── [OR] BMI ≥ 35 with...         │
│  │ Policy 2 ✓ │  │   └── ● Failed non-surgical             │
│  │ Policy 3   │  │                                          │
│  │ Policy 4   │  │  [Expand All] [Collapse All]  v1 of 1   │
│  └────────────┘  │                                          │
│  Stats: 207/193/3│                                          │
└──────────────────┴──────────────────────────────────────────┘
```

## Components

| Component | Purpose |
|-----------|---------|
| `Layout.tsx` | Two-panel layout with header |
| `PipelineControls.tsx` | Source URL input + Discover/Download/Structure buttons |
| `PolicyList.tsx` | Filterable, sorted policy list (structured first) |
| `PolicyCard.tsx` | Single policy with status badge (8 states, color-coded) |
| `PolicyDetail.tsx` | Detail view with state bar, tabs, action buttons |
| `StateBar.tsx` | Visual state progression (DISC → DOWN → EXTR → VALID) |
| `CriteriaTree.tsx` | Tree wrapper with Expand All / Collapse All |
| `TreeNode.tsx` | Recursive node: AND (blue), OR (amber), leaf (green dot) |
| `OperatorBadge.tsx` | AND/OR badge component |
| `StatusBar.tsx` | Bottom bar with policy/download/structured counts |

## Status Badges

| Status | Color | Animation |
|--------|-------|-----------|
| Discovered | Gray | — |
| Downloading | Blue | Pulse |
| Downloaded | Blue | — |
| Download Failed | Red | — |
| Extracting | Purple | Pulse |
| Extracted | Purple | — |
| Validated | Green | — |
| Extraction Failed | Red | — |

## Key Files

- `src/api/client.ts` — API client with all endpoints
- `src/types/index.ts` — TypeScript interfaces
- `src/hooks/` — `usePolicies`, `useTree`, `useText`, `useVersions`
