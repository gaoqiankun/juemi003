# Design System Strategy: The Precision Architect

This design system is a high-fidelity framework engineered for the Cubify 3D Admin Panel. It moves away from the "generic SaaS" aesthetic by prioritizing tonal depth, editorial-grade typography, and a refusal of traditional structural lines. We treat the interface not as a collection of boxes, but as a calibrated instrument of light and shadow.

## 1. Creative North Star: The Technical Atelier
The "Technical Atelier" vision combines the clinical precision of a 3D modeling environment with the sophisticated layout of a premium architectural journal. We avoid the "cluttered dashboard" look by using **intentional asymmetry** and **tonal nesting**. The goal is a workspace that feels expensive, quiet, and profoundly capable.

- **Asymmetry:** Group primary controls on one side of a container while leaving generous "negative air" on the other to guide the eye.
- **Micro-Interactions:** Transitions should be instantaneous yet soft (using `cubic-bezier(0.16, 1, 0.3, 1)`), mimicking the movement of precision hardware.

## 2. Color & Surface Architecture
The palette is rooted in deep obsidian tones and a surgical Teal accent (`#0891B2`). 

### The "No-Line" Rule
Standard 1px borders are forbidden for sectioning. Structural separation is achieved through background shifts.
*   **Method:** A `surface-container-low` section (e.g., the sidebar) sitting against a `surface` background provides all the definition needed.
*   **The Nesting Principle:** Hierarchy is a "stack." 
    *   Base: `surface` (`#131316`)
    *   Secondary Area: `surface-container-low` (`#1b1b1e`)
    *   Interactive Card: `surface-container-highest` (`#353438`)

### The Glass & Gradient Rule
To prevent the UI from feeling "flat," use Glassmorphism for floating overlays (Modals, Tooltips, Popovers).
*   **Token:** `surface-variant` at 60% opacity with a `20px` backdrop-blur.
*   **Signature Gradients:** For primary CTAs, do not use flat teal. Use a linear gradient: `primary` (`#6cd3f7`) to `primary-container` (`#269dbe`) at a 135° angle.

## 3. Typography: Editorial Precision
We utilize **Inter** for its neutral, high-readability character, but we style it with "Tight Spacing" (-0.02em letter spacing) to give it a modern, compressed technical feel.

*   **Tabular Numbers:** All numerical data (coordinates, dimensions, timestamps) must use `font-variant-numeric: tabular-nums`.
*   **ID Monospacing:** System IDs, Hash strings, and Hex codes must use Geist Mono to distinguish them from human-readable content.
*   **Scale Hierarchy:**
    *   **Display/Headline:** Use `headline-sm` (1.5rem) for page titles to keep the interface compact.
    *   **Labels:** Use `label-sm` (0.6875rem) in ALL CAPS with +0.05em tracking for category headers to create an authoritative "Blueprint" aesthetic.

## 4. Elevation & Depth
Depth is created through **Tonal Layering** rather than drop shadows.

*   **Layering Principle:** Place a `surface-container-lowest` card on a `surface-container-low` section. This "recessed" look creates a sophisticated, carved-out feel.
*   **Ambient Shadows:** For floating elements only, use: `0px 8px 24px rgba(0, 0, 0, 0.2), 0px 2px 4px rgba(8, 145, 178, 0.04)`. Note the subtle teal tint in the shadow to unify it with the brand.
*   **The Ghost Border:** If a boundary is required for accessibility, use `outline-variant` at 15% opacity. Never use a 100% opaque border.

## 5. Component Logic

### Buttons & Inputs
*   **Primary Button:** 6px radius. Gradient fill (Teal). High-contrast `on-primary` text.
*   **Secondary/Ghost:** No background. `outline` border (Ghost Border style). Transitions to a subtle `surface-container-high` on hover.
*   **Input Fields:** `surface-container-low` background. No border. On focus, a bottom-only 2px stroke of `primary` appears.

### Cards & Lists
*   **The "No-Divider" Rule:** Forbid horizontal lines between list items. Use vertical spacing (Scale `4` - 0.9rem) or alternating tonal shifts (zebra striping using `surface-container-low` vs `surface-container-lowest`).
*   **3D Preview Cards:** Aspect ratio should be strictly 16:9 or 1:1. Use a subtle inner-glow (`inset 0 1px 1px rgba(255,255,255,0.05)`) to make the 3D viewport pop.

### System-Specific Components
*   **Coordinate HUD:** Small, floating `label-sm` groups showing X/Y/Z data in `secondary` color tokens.
*   **Status Indicators:** Use `tertiary` (Gold/Orange) for "Processing" and `primary` (Teal) for "Live." Avoid standard traffic-light colors unless it's a critical `error`.

## 6. Do’s and Don’ts

| Do | Don't |
| :--- | :--- |
| Use negative space as a separator. | Use 1px grey lines to divide content. |
| Use `tabular-nums` for all 3D coordinates. | Use standard proportional spacing for data. |
| Use 6px (`DEFAULT`) radius for all containers. | Mix rounded and sharp corners. |
| Nest surfaces (darker inside lighter). | Use heavy drop shadows on every card. |
| Use Geist Mono for object UUIDs. | Use Inter for technical strings. |

## 7. Spacing & Rhythm
Strictly adhere to the 0.2rem increment scale. 
*   **Container Padding:** `5` (1.1rem) for standard cards.
*   **Page Margins:** `10` (2.25rem) to provide the "Editorial" breathing room required for high-end experiences.
*   **Component Gap:** `2` (0.4rem) for tightly coupled elements (Label + Input).