# Weight Manager Frontend Fixes (B-1, B-5)
Date: 2026-03-29 / Status: done
Status: done

## Scope
- `web/src/lib/admin-api.ts`
- `web/src/hooks/use-models-data.ts`
- `web/src/pages/models-page.tsx`
- `web/src/components/add-model-dialog.tsx`

## Tasks
- Ensure retry payload includes backend-required fields: `id`, `displayName`, `modelPath`, `weightSource`, `providerType`
- Add `providerType` mapping through admin raw record and pending item types
- Tighten HuggingFace repo validation to `^[^/\s]+\/[^/\s]+$`
- Run `cd web && npm run build` and ensure zero errors
