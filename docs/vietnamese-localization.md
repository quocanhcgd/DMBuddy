# Vietnamese localization

Printbuddy now ships a Vietnamese locale at `frontend/src/i18n/locales/vi.ts`.
It contains the same 4,864 leaf keys as `en.ts` and is registered in
`frontend/src/i18n/index.ts` as `vi` / `Tiếng Việt`.

## Regenerate

From `frontend/`:

```text
node scripts/generate-vietnamese-locale.mjs
npm run check:i18n
npx tsc --noEmit
```

The generator reads the English catalog with the TypeScript AST, protects
`{{placeholder}}` interpolation tokens, translates unique strings, and writes
the Vietnamese catalog while preserving the source object shape and comments.
Translations are cached in `.vi-translation-cache.json` for incremental runs.

## Scope

The locale catalog covers frontend strings consumed through `i18next`. It does
not automatically translate hard-coded JSX text, backend/API error messages,
email or push notification templates, or date/number formatting rules. Those
surfaces need separate changes if full Vietnamese product coverage is required.

The generated text is machine translated and should receive a Vietnamese
language review before production release, especially printer terminology,
security/admin settings, and long explanatory descriptions.

## Verification

`npm run check:i18n` verifies key parity and interpolation placeholders against
English. The Vietnamese catalog currently passes this check and TypeScript
type-checking.
