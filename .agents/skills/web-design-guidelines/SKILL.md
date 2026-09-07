---
name: web-design-guidelines
description: "Review and enforce compliance with Vercel Web Interface Guidelines (accessibility, focus states, tabular numbers, typography, motion, forms)."
---

# Web Interface Guidelines (Vercel Labs Standard)

## Rules & Standards

### Accessibility
- Icon-only buttons need `aria-label` and `title`.
- Interactive elements need keyboard handlers or native semantic elements (`<button>`, `<a>`).
- Decorative icons need `aria-hidden="true"`.
- Async status updates (loading, toasts) need `aria-live="polite"`.
- Form controls must have accessible labels.

### Focus States
- Interactive elements need visible focus: `focus-visible:ring-1 focus-visible:ring-primary/40`.
- Never `outline-none` without explicit focus state replacement.
- Use `:focus-visible` over `:focus` to avoid awkward focus rings on click.

### Typography
- Tabular figures (`tabular-nums font-mono`) for all number columns, tables, currency, and date/time displays.
- Ellipsis `…` instead of `...`.
- Loading states end with `…`: `"Memuat…"`, `"Menyusun data…"`.
- Headings use `text-wrap: balance` or `text-pretty` to prevent orphan words.

### Animation & Motion
- Prefer `transform` and `opacity` for performance.
- Never use `transition: all` — list properties explicitly (`transition-colors`, `transition-transform`).
- Respect `prefers-reduced-motion`.
- Micro-interactions between 150ms–250ms.

### Layout & Spacing
- Flex children with text truncation must include `min-w-0`.
- Maintain intentional hierarchy, controlled density, and clear whitespace.
