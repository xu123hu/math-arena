/* Math Arena Web - ESLint 8 配置（.eslintrc 体系，非 flat config）
 * M0 脚手架阶段规则保持宽松；严格度随里程碑收紧。
 * 只使用 package.json 中已安装的插件：eslint-plugin-vue、@typescript-eslint/*。
 */
module.exports = {
  root: true,
  env: {
    browser: true,
    es2021: true,
    node: true,
  },
  globals: {
    // Vue 3 <script setup> 编译器宏
    defineProps: "readonly",
    defineEmits: "readonly",
    defineExpose: "readonly",
    defineOptions: "readonly",
    defineSlots: "readonly",
    withDefaults: "readonly",
  },
  extends: [
    "eslint:recommended",
    "plugin:vue/vue3-recommended",
    "plugin:@typescript-eslint/recommended",
  ],
  parser: "vue-eslint-parser",
  parserOptions: {
    parser: "@typescript-eslint/parser",
    ecmaVersion: "latest",
    sourceType: "module",
    extraFileExtensions: [".vue"],
  },
  plugins: ["@typescript-eslint"],
  rules: {
    // ---- 宽松区（脚手架阶段） ----
    // TS 类型检查由 vue-tsc 负责，关闭核心 no-undef 避免误报类型引用
    "no-undef": "off",
    // 页面组件多为单单词命名（login/chat/index 等）
    "vue/multi-word-component-names": "off",
    // 富文本渲染使用 DOMPurify 消毒后的 v-html
    "vue/no-v-html": "off",
    "@typescript-eslint/no-explicit-any": "off",
    "@typescript-eslint/no-unused-vars": [
      "warn",
      { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
    ],
    "@typescript-eslint/no-empty-function": "off",
    "no-console": "off",
    "no-debugger": "warn",
    "prefer-const": "warn",
  },
  ignorePatterns: ["dist", "node_modules", "*.d.ts"],
};
