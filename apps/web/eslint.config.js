import js from '@eslint/js';
import jsxA11y from 'eslint-plugin-jsx-a11y';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'src/momentum/lib/api/schema.d.ts'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended, jsxA11y.flatConfigs.recommended],
    languageOptions: { globals: { ...globals.browser }, ecmaVersion: 2022 },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      // Design-system guard: colors must come from tokens, never literals in components.
      'no-restricted-syntax': [
        'error',
        {
          selector: 'Literal[value=/(#[0-9a-fA-F]{3,8}\\b|oklch\\(|rgba?\\()/]',
          message: 'Use design tokens (Tailwind token classes or var(--token)), not raw colors.',
        },
      ],
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            { group: ['@/features/*/*'], message: "Import other features via their index ('@/features/x')." },
          ],
        },
      ],
    },
  },
  {
    files: ['src/momentum/components/ui/**'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            { group: ['@/features/*', '@/features/**'], message: 'UI primitives must not import features.' },
          ],
        },
      ],
    },
  },
);
