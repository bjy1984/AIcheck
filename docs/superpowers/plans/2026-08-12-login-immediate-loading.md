# Login Immediate Loading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the login form enter a complete, duplicate-safe loading state immediately after click or Enter, then recover when validation or authentication fails.

**Architecture:** Keep `LoginForm.vue` as the owner of one `loading` submission lock. Set the lock before awaiting the form instance or validation, expose it reactively to every interactive control, and await all login navigation branches so successful submissions stay locked until the login page is left.

**Tech Stack:** Vue 3 Composition API with TSX, Element Plus, Playwright, TypeScript.

## Global Constraints

- Only adjust the frontend login submission state; do not change backend login performance.
- Disable username, password, remember-me, administrator-reset link, and login button while submitting.
- Ignore click and Enter submissions while one submission is already active.
- Restore interaction after validation failure, authentication failure, or an exception.
- Keep the form locked through successful navigation.
- Add no dependencies and do no unrelated refactoring.

---

### Task 1: Immediate, complete login submission state

**Files:**
- Modify: `frontend/e2e/aicheck-smoke.spec.ts`
- Modify: `frontend/src/views/Login/components/LoginForm.vue:40-324`

**Interfaces:**
- Consumes: the existing `loading: Ref<boolean>`, `signIn(): Promise<void>`, form schema, `loginApi`, `getRole`, and Vue Router `push`.
- Produces: one observable form contract: all interactive controls disable synchronously after submission, duplicate submissions are ignored, failures unlock the form, and successful navigation remains awaited.

- [ ] **Step 1: Write the failing browser test**

Add a Playwright test next to the current login error tests. Delay the intercepted login response until a manually controlled promise is released, synchronously dispatch two button clicks, then assert the two inputs, remember-me checkbox, reset link, and login button are disabled. Assert only one request was observed, release an error response, and assert all controls become enabled again.

```ts
test('login enters a complete loading state immediately and prevents duplicate submissions', async ({
  page
}) => {
  let releaseLogin!: () => void
  const loginPending = new Promise<void>((resolve) => {
    releaseLogin = resolve
  })
  let requestCount = 0

  await page.route('**/api/auth/login', async (route) => {
    requestCount += 1
    await loginPending
    await route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify(businessError(401, '账号或密码错误', 'AUTH_REQUIRED'))
    })
  })

  const loginInputs = await gotoLoginPage(page)
  const remember = page.getByRole('checkbox', { name: '记住我' })
  const resetLink = page.getByText('联系管理员重置', { exact: true })
  const loginButton = page.getByRole('button', { name: /^登录$/ })
  await loginInputs.nth(0).fill('invalid-user')
  await loginInputs.nth(1).fill('invalid-password')

  await loginButton.evaluate((button) => {
    ;(button as HTMLButtonElement).click()
    ;(button as HTMLButtonElement).click()
  })
  await expect(loginInputs.nth(0)).toBeDisabled()
  await expect(loginInputs.nth(1)).toBeDisabled()
  await expect(remember).toBeDisabled()
  await expect(resetLink).toHaveAttribute('aria-disabled', 'true')
  await expect(loginButton).toBeDisabled()

  await expect.poll(() => requestCount).toBe(1)

  releaseLogin()
  await expect(page.getByText(/账号或密码错误/).first()).toBeVisible()
  await expect(loginInputs.nth(0)).toBeEnabled()
  await expect(loginInputs.nth(1)).toBeEnabled()
  await expect(remember).toBeEnabled()
  await expect(resetLink).not.toHaveAttribute('aria-disabled', 'true')
  await expect(loginButton).toBeEnabled()
})
```

- [ ] **Step 2: Run the new test and verify RED**

Run:

```bash
cd frontend && pnpm playwright test e2e/aicheck-smoke.spec.ts --grep "login enters a complete loading state"
```

Expected: FAIL because the username/password inputs and tool controls are not disabled while the intercepted request is pending.

- [ ] **Step 3: Implement the minimal submission lock and bindings**

In `LoginForm.vue`, declare `loading` before constructing `schema`, bind it into component props, and disable every interactive control:

```tsx
const loading = ref(false)

componentProps: {
  // existing props
  disabled: loading
}

<ElCheckbox disabled={loading.value} ... />
<ElLink disabled={loading.value} ... />
<BaseButton loading={loading.value} disabled={loading.value} ... />
```

Replace callback validation with an awaited result and use the loading flag as an entry guard. Track navigation success so the lock is only released when the flow remains on the login page:

```ts
const signIn = async () => {
  if (loading.value) return
  loading.value = true
  errorMessage.value = ''
  let navigated = false

  try {
    const formRef = await getElFormExpose()
    if (!formRef || !(await formRef.validate().catch(() => false))) return
    const formData = await getFormData<UserLoginType>()
    const res = await loginApi(formData)
    if (!res) return

    // Preserve existing user/session setup.
    if (res.data.user.mustChangePassword) {
      await push('/change-password')
      navigated = true
      return
    }
    if (appStore.getDynamicRouter) {
      navigated = await getRole()
    } else {
      // Preserve route generation, await push({ path }), then set navigated = true.
    }
  } catch (error: unknown) {
    errorMessage.value = getAicheckErrorMessage(error, '登录失败，请检查用户名和密码')
  } finally {
    if (!navigated) loading.value = false
  }
}
```

Change `getRole` to `Promise<boolean>`: return `true` only after its existing `push` completes and return `false` when no role response is available. Add `await` to the static-router `push` branch and set `navigated = true` only after it completes.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run:

```bash
cd frontend && pnpm playwright test e2e/aicheck-smoke.spec.ts --grep "login enters a complete loading state"
```

Expected: PASS; exactly one intercepted request occurs and all controls unlock after the error response.

- [ ] **Step 5: Run login regression tests and static checks**

Run:

```bash
cd frontend && pnpm playwright test e2e/aicheck-smoke.spec.ts --grep "login"
cd frontend && pnpm test:unit
cd frontend && pnpm ts:check
```

Expected: all commands exit 0 with no new TypeScript errors.

- [ ] **Step 6: Commit the implementation**

```bash
git add frontend/e2e/aicheck-smoke.spec.ts frontend/src/views/Login/components/LoginForm.vue
git commit -m "fix: show login loading state immediately"
```
