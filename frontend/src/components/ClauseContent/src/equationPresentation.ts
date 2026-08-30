export const normalizedEquationSource = (value: string) =>
  String(value || '')
    .trim()
    .replace(/^\$\$\s*/u, '')
    .replace(/\s*\$\$$/u, '')
    .replace(/\\tag\s*\{[^{}]*\}\s*$/u, '')
    .trim()
