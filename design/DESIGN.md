# Spindrift design guide (8-bit theme)

Use this for all UI work. Tokens live in `design/tokens.json` and `spindrift/static/theme.css`. Always use the tokens. Never hard-code hex values, fonts or spacing.

## Look
The app should look like an old phosphor-green monitor. The display is dark with bright green and amber, the edges are hard, and everything is pixel-crisp. Only the logo, `h1` and `h2` use the pixel font. Everything else stays easy to read.

## Colour
- Background `--sd-bg`. Panels use `--sd-surface`, and nested or hovered panels use `--sd-surface-raised`.
- `--sd-primary` (green) is for primary actions, links, headings and the active nav item.
- `--sd-accent` (amber) is for numbers, stats, focus rings and highlights. Use it sparingly.
- Game status always maps like this: playing = green, backlog = amber, completed = cyan, dropped = red. Use the `.sd-badge--*` classes, and always pair the colour with a text label.
- Text on a green fill uses `--sd-on-primary`.
- Each platform has a tint, `--sd-platform-*`. They're grouped by family: a blue ramp for PlayStation, a green ramp for Xbox, and a grey-blue ramp for the PC storefronts. Text on a tint uses `--sd-platform-ink`. Every tint is at least 4.5:1 against that ink.

## Type
- `--sd-font-display` (Press Start 2P) is for the logo, `h1`, `h2` and button labels only. Never use it for body text, and never go below 12px.
- `--sd-font-body` (Chakra Petch) is for all body text, form fields and `h3`/`h4`.
- `--sd-font-stat` (VT323) is for numbers: hours played, completion %, counts, badges.
- Use sentence case in body copy. Upper case is only for the display font.

## Shape and depth
- `border-radius: 0` everywhere.
- Borders are 2px solid `--sd-border`, or 4px for emphasis.
- For depth, use only the hard offset shadow `--sd-shadow`. Don't use blur shadows, gradients or glassmorphism. The one exception is the segmented fill in `.sd-progress`.
- Pressed buttons shift 3px down and right and use `--sd-shadow-pressed`.
- Spacing follows an 8px grid via `--sd-space-*`.

## Motion
- Use stepped timing only (`--sd-step`, `--sd-step-fast`), never smooth easing.
- Animate only in response to a user action.
- Respect `prefers-reduced-motion` (already handled in `theme.css`).

## Components (in `spindrift/static/theme.css`)
`.sd-panel`, `.sd-button`, `.sd-button--ghost`, `.sd-input`, `.sd-stat`, `.sd-badge--{playing|backlog|completed|dropped}`, `.sd-progress > span`.
Extend these rather than inventing new styles. New components follow the same rules above.

## Accessibility
- Every control has a visible `:focus-visible` amber outline and a touch target of at least 44px.
- Use real `<button>`, `<a>`, `<label>` and `<input>` elements.
- Text contrast is at least 4.5:1. Check this before adding new colours.

## Logo
- `spindrift/static/spindrift-mark.svg` is the app icon, favicon and small-space version.
- `spindrift/static/spindrift-logo.svg` is the full lockup for the header or splash screen.
- Keep clear space around the logo of at least one pixel-block (12px at default size).

## Tailwind (if used)
Map tokens in the Tailwind config / `@theme`, e.g. `--color-primary: var(--sd-primary)`, `--font-display: var(--sd-font-display)`, `--radius-*: 0`. Don't use Tailwind's default palette or rounded utilities.
