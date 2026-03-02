import js from "@eslint/js";

export default [
  js.configs.recommended,
  {
    files: ["app/static/**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: {
        window: "readonly",
        document: "readonly",
        navigator: "readonly",
        localStorage: "readonly",
        fetch: "readonly",
        console: "readonly",
        Chart: "readonly",
        Notification: "readonly",
        FormData: "readonly",
        setTimeout: "readonly",
        setInterval: "readonly",
        clearInterval: "readonly",
        clearTimeout: "readonly",
        btoa: "readonly",
        Uint8Array: "readonly",
        EventSource: "readonly",
        alert: "readonly",
        prompt: "readonly",
        self: "readonly",
        caches: "readonly",
        clients: "readonly",
        registration: "readonly",
        URLSearchParams: "readonly",
      },
    },
    rules: {
      "no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],
      "no-undef": "warn",
      "no-console": "off",
      "prefer-const": "warn",
    },
  },
];
