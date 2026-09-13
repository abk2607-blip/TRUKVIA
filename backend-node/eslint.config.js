// TRUKVIA backend-node — ESLint flat config (ESLint 9 + typescript-eslint 8).
// Scope: this directory only. Never lints Python or the React frontend.
import js from '@eslint/js';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    ignores: ['dist/**', 'coverage/**', 'node_modules/**', '.vitest-cache/**'],
  },
  // JS-only files (this config file, etc.) — plain recommended, no typed rules.
  {
    files: ['**/*.js', '**/*.cjs', '**/*.mjs'],
    ...js.configs.recommended,
  },
  // TypeScript files — typed linting.
  ...tseslint.configs.recommendedTypeChecked.map((cfg) => ({
    ...cfg,
    files: ['src/**/*.ts', 'test/**/*.ts', 'scripts/**/*.ts', 'scripts/**/*.mts'],
  })),
  {
    files: ['src/**/*.ts', 'test/**/*.ts', 'scripts/**/*.ts', 'scripts/**/*.mts'],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.eslint.json'],
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      // ---- security / correctness ----
      '@typescript-eslint/no-floating-promises': 'error',
      '@typescript-eslint/no-misused-promises': 'error',
      '@typescript-eslint/await-thenable': 'error',
      '@typescript-eslint/no-unsafe-argument': 'error',
      '@typescript-eslint/no-unsafe-assignment': 'error',
      '@typescript-eslint/no-unsafe-call': 'error',
      '@typescript-eslint/no-unsafe-member-access': 'error',
      '@typescript-eslint/no-unsafe-return': 'error',
      // `require-await` is disabled because Fastify's hook + handler API
      // expects async functions even when their body has no awaits — this
      // is Fastify's idiomatic contract for a promise-returning handler.
      '@typescript-eslint/require-await': 'off',
      'no-eval': 'error',
      'no-implied-eval': 'error',
      'no-new-func': 'error',
      // ---- unsafe any ----
      '@typescript-eslint/no-explicit-any': ['error', { ignoreRestArgs: false }],
      // ---- unused vars ----
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
          ignoreRestSiblings: true,
        },
      ],
      // ---- style-lite (kept minimal for foundation) ----
      'eqeqeq': ['error', 'always', { null: 'ignore' }],
      'no-console': 'off',
    },
  },
  {
    // Tests / smoke scripts may need occasional casts to build mock objects.
    files: ['test/**/*.ts', 'scripts/**/*.mts', 'scripts/**/*.ts'],
    rules: {
      '@typescript-eslint/no-unsafe-assignment': 'off',
      '@typescript-eslint/no-unsafe-member-access': 'off',
      '@typescript-eslint/no-unsafe-argument': 'off',
      '@typescript-eslint/no-unsafe-call': 'off',
      '@typescript-eslint/no-unsafe-return': 'off',
      '@typescript-eslint/no-non-null-assertion': 'off',
    },
  },
);
