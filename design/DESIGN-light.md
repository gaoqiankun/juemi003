# Design System Strategy: Engineering Precision & Layered Calm

## 1. Overview & Creative North Star
**Creative North Star: "The Tactile Blueprint"**

This design system moves beyond the "standard SaaS dashboard" to create an environment that feels like a high-end engineering tool—precise, authoritative, and impossibly clean. Inspired by the editorial clarity of Apple and the functional density of Linear, the system prioritizes **Tonal Layering** over structural lines. 

To break the "template" look, we utilize **Intentional Asymmetry**. Primary actions and data visualizations are anchored to a rigid 4px baseline, while secondary information "floats" in semi-transparent layers. The result is a UI that feels like a physical stack of technical drawings: thin, legible, and deeply organized.

---

## 2. Colors & Surface Logic

The palette is rooted in cool greys and "Paper White" surfaces, punctuated by a surgical application of **Teal #0891B2**.

### The "No-Line" Rule
Traditional 1px solid borders are strictly forbidden for sectioning. Use background color shifts to define boundaries.
*   **Sidebar:** `surface-container` (#eeeef0)
*   **Main Workspace:** `background` (#f9f9fb)
*   **Floating Panels:** `surface-container-lowest` (#ffffff)

### Surface Hierarchy & Nesting
Treat the UI as a physical stack. Higher importance items must sit "closer" to the user:
1.  **Level 0 (Base):** `surface` (#f9f9fb) – The desk surface.
2.  **Level 1 (Sections):** `surface-container-low` (#f3f3f5) – Inset zones or secondary sidebars.
3.  **Level 2 (Active Cards):** `surface-container-lowest` (#ffffff) – Primary content focus.
4.  **Level 3 (Modals/Popovers):** Glassmorphic `surface-bright` with `backdrop-blur: 12px`.

### The "Glass & Gradient" Rule
To elevate CTAs, move away from flat Teal. Use a **Signature Texture**:
*   **Primary Action Gradient:** Linear (135°) from `primary` (#00647c) to `primary-container` (#007f9d). This adds a subtle "machined" depth that flat hex codes cannot replicate.

---

## 3. Typography: Editorial Authority

We use a dual-typeface system to balance human readability with technical precision.

*   **Headlines & Titles (Inter):** Tight tracking (-0.02em) and Semi-bold weights. The hierarchy uses a "High-Contrast" jump—Display sizes are significantly larger than body text to create an editorial, magazine-like feel.
*   **Labels & Metadata (Space Grotesk):** Used for "Engineering-grade" data. The wider apertures of Space Grotesk provide an industrial aesthetic.
*   **System IDs (Monospace):** All ID strings, coordinates, and 3D data points must use a monospace font to signify "Raw Data."

**Scale Highlight:**
*   `display-md`: 2.75rem / Leading 1.1 (Inter) - Use for hero metrics.
*   `label-sm`: 0.6875rem / Leading 1.0 (Space Grotesk) - Use for status caps and technical tags.

---

## 4. Elevation & Depth

### The Layering Principle
Depth is achieved through the **Tonal Step**:
*   Place a `surface-container-lowest` card (White) on top of a `surface-container-low` (#f3f3f5) background. The 2-point delta in hex value creates a "soft edge" that feels more premium than a high-contrast shadow.

### Ambient Shadows
Shadows are never "Grey." They are tinted.
*   **Value:** `0px 4px 24px rgba(0, 31, 40, 0.06)`
*   This uses the `on-primary-fixed` tint, making the shadow feel like a natural occlusion of the Teal-accented environment rather than a "drop shadow" effect.

### The "Ghost Border" Fallback
Where containment is required for accessibility:
*   Use `outline-variant` (#bdc8ce) at **20% opacity**. It should be felt, not seen.

---

## 5. Components

### Buttons: The Precision Tool
*   **Primary:** Gradient fill (Teal), `6px` radius. Internal padding: `1.5` (0.375rem) vertical, `4` (1rem) horizontal.
*   **Secondary:** `surface-container-highest` background with `on-surface` text. No border.
*   **State:** On hover, primary buttons should increase in saturation, not darkness.

### Input Fields: The Blueprint Slot
*   **Base:** `surface-container-low` (#f3f3f5).
*   **Active:** A 1px "Ghost Border" of `primary` (#00647c) appears. 
*   **Typography:** All input text uses `body-md`. Labels use `label-sm` in all-caps with 0.05em letter spacing.

### Cards & Lists: Separation by Space
*   **Rule:** Forbid divider lines. 
*   **Execution:** Use `spacing-6` (1.5rem) of vertical white space to separate list items, or alternate the background color of list items between `surface` and `surface-container-low`.

### Status Dots: Minimalist Signals
*   Use 6px circles. No glow, no ring.
*   **Active:** `primary` (#00647c)
*   **Error:** `error` (#ba1a1a)
*   **Idle:** `outline-variant` (#bdc8ce)

---

## 6. Do’s and Don'ts

### Do
*   **Do** use asymmetrical layouts. For example, a wide left column for 3D viewing and a narrow, dense right column for technical metadata.
*   **Do** use monospace for any string that looks like "code" or "coordinates."
*   **Do** use Glassmorphism for hovering toolbars over the 3D viewport.

### Don’t
*   **Don’t** use black (#000000). Use `on-surface` (#1a1c1d) for text to maintain the "calm" aesthetic.
*   **Don’t** use 100% opaque borders to separate the sidebar from the main content. Use the transition from `surface-container` to `background`.
*   **Don’t** use standard "Drop Shadows" on cards. Rely on the surface color scale first.