import js from "@eslint/js";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import security from "eslint-plugin-security";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "playwright-report", "test-results", "*.config.js"] },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  security.configs.recommended,
  {
    languageOptions: { parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname } },
    plugins: { react, "react-hooks": reactHooks },
    settings: { react: { version: "18" } },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // XSS defence: message text is only ever rendered as React text nodes.
      "react/no-danger": "error",
      "react/no-danger-with-children": "error",
      "react/jsx-no-target-blank": "error",
      "react/jsx-no-script-url": "error",
      "no-restricted-syntax": [
        "error",
        { selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']", message: "Never render HTML." },
        { selector: "MemberExpression[property.name='innerHTML']", message: "Never write innerHTML." },
        { selector: "MemberExpression[property.name='outerHTML']", message: "Never write outerHTML." },
        { selector: "CallExpression[callee.property.name='insertAdjacentHTML']", message: "Never write HTML." },
      ],
      "no-eval": "error",
      "no-implied-eval": "error",
      "@typescript-eslint/no-confusing-void-expression": ["error", { ignoreArrowShorthand: true }],
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-unsafe-assignment": "error",
      "@typescript-eslint/no-unsafe-member-access": "error",
      "@typescript-eslint/restrict-template-expressions": ["error", { allowNumber: true }],
      "@typescript-eslint/no-non-null-assertion": "error",
      "@typescript-eslint/no-misused-promises": ["error", { checksVoidReturn: { attributes: false } }],
    },
  },
  {
    files: ["**/*.test.ts", "**/*.test.tsx", "e2e/**", "src/test/**"],
    rules: {
      "security/detect-object-injection": "off",
      "security/detect-non-literal-fs-filename": "off",
      "@typescript-eslint/no-non-null-assertion": "off",
      "@typescript-eslint/no-unsafe-assignment": "off",
      "@typescript-eslint/no-unsafe-member-access": "off",
      "@typescript-eslint/no-unsafe-call": "off",
      "@typescript-eslint/unbound-method": "off",
      "@typescript-eslint/no-confusing-void-expression": "off",
    },
  },
);
