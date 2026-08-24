import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    rules: {
      // Error yang bisa memutihkan layar tetap ERROR (diblokir di CI):
      // no-undef, no-unused-vars, react-hooks/rules-of-hooks, dsb.

      // catch (e) yang parameternya tak dipakai adalah pola normal di
      // handler async frontend -> jangan dilaporkan.
      // ignoreRestSiblings: pola destructure-untuk-membuang-field
      // (const { password, ...rest } = form) juga disengaja.
      'no-unused-vars': ['error', { caughtErrors: 'none', ignoreRestSiblings: true }],

      // Rules pedantic dari plugin react-hooks v6 — turun jadi warning
      // supaya CI ketat pada hal yang benar-benar merusak runtime.
      'react-hooks/set-state-in-effect': 'warn',
      'react-hooks/static-components': 'warn',
      'react-hooks/immutability': 'warn',
      'react-hooks/globals': 'warn',
      'react-hooks/refs': 'warn',
    },
  },
])
