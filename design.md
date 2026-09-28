# JAAL — Design System

**Vibe:** dark, serious, "command-center" for investigators. Data-dense but calm; color is reserved for meaning (roles, risk).

## 5.1 Colors (Dark Theme)

| Token | Hex | Use |
|---|---|---|
| --bg | #0B0F1A | App background |
| --surface | #121826 | Cards, panels |
| --surface-2 | #1B2436 | Hover, table rows |
| --border | #2A3550 | Dividers |
| --text | #E6EAF2 | Primary text |
| --text-muted | #8B97B1 | Secondary text |
| --primary | #22D3EE | Actions, links, focus, selected |
| --kingpin | #EF4444 | Kingpin nodes/badges |
| --handler | #A78BFA | Handler |
| --mule | #F59E0B | Mule accounts |
| --operator | #F472B6 | Callers/operators |
| --victim | #60A5FA | Victims |
| --unknown | #64748B | Unclassified |
| --success | #22C55E | Verified/complete |
| --warning | #FACC15 | Low confidence |

Rules: role colors used consistently in graph, table chips, hierarchy and brief. Contrast >= 4.5:1 for text.

## 5.2 Typography

| Use | Font | Weight | Size |
|---|---|---|---|
| Headings | Space Grotesk | 600-700 | H1 28 / H2 22 / H3 18 |
| Body/UI | Inter | 400-500 | 14-16 |
| IDs, numbers, amounts, code | JetBrains Mono | 400-500 | 13 |
| Brief PDF body | Inter | 400 | 11pt |

Line-height 1.5 body, 1.25 headings. Mask sensitive numbers in mono (XXXXXX1234).

## 5.3 Layout & Components

- 12-col grid, 8px spacing scale (4/8/12/16/24/32). Radius 12px cards, 8px inputs. Subtle 1px borders, minimal shadows.
- **Dashboard:** left sidebar (case list, filters), center graph (60%), right entity/evidence panel (25%), top bar with PatternBadge + confidence.
- **Tabs:** Graph | Hierarchy | Timeline | Suspects | Brief
- **Graph nodes:** shape by type (circle=person, rounded-square=account, diamond=phone/SIM, hexagon=device); size = risk score; color = role; edge thickness = amount; arrows show money direction; dashed = calls.
- **Hierarchy view:** top-down tree (dagre): Kingpin → Handlers → Mules/Operators → Victims.
- **Pattern badge:** pill with icon, label, confidence bar; click shows reasons.
- **Buttons:** primary = cyan fill/dark text; secondary = outline; danger = red outline.
- **States:** skeleton loaders, stepwise processing (Parsing → Extracting → Building graph → Analyzing → Writing brief), friendly empty/error states.
- **Motion:** 150-250ms ease-out; graph layout animate on load; no decorative animation.
- **Disclaimer strip** in Brief page: "AI-assisted analysis. Verify before legal action."

## 5.4 Tailwind Config Tokens

```js
// tailwind.config.js -> theme.extend.colors
{
  bg: '#0B0F1A',
  surface: '#121826',
  'surface-2': '#1B2436',
  border: '#2A3550',
  primary: '#22D3EE',
  kingpin: '#EF4444',
  handler: '#A78BFA',
  mule: '#F59E0B',
  operator: '#F472B6',
  victim: '#60A5FA',
  unknown: '#64748B',
  success: '#22C55E',
  warning: '#FACC15',
}
```

## 5.5 Google Fonts Import
```
Space Grotesk: weights 600, 700
Inter: weights 400, 500
JetBrains Mono: weights 400, 500
```
