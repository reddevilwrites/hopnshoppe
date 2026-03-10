import { test, expect } from '@playwright/test';
import { AccountPage } from '../pages/AccountPage';
import { LoginPage } from '../pages/LoginPage';
import { SignupPage } from '../pages/SignupPage';
import { createTestEmail, registerForCleanup } from '../fixtures/testAccounts';

async function signupAndLogin(page: import('@playwright/test').Page, email: string) {
  const signup = new SignupPage(page);
  await signup.goto();
  await signup.signup({
    email,
    firstName: 'Original',
    lastName: 'Name',
    password: 'Password123',
  });
  await signup.expectSuccess();

  const login = new LoginPage(page);
  await login.goto();
  await login.login(email, 'Password123');
  await login.expectRedirectToProducts();
}

test.describe('User profile (Account page)', () => {
  test('profile page loads — email shown and disabled', async ({ page }) => {
    const email = createTestEmail();
    registerForCleanup(email);
    await signupAndLogin(page, email);

    const account = new AccountPage(page);
    await account.goto();
    await account.expectEmail(email);

    // Email field must be disabled (read-only)
    await expect(account.emailInput).toBeDisabled();
  });

  test('update firstName and lastName — "Profile updated!" shown', async ({ page }) => {
    const email = createTestEmail();
    registerForCleanup(email);
    await signupAndLogin(page, email);

    const account = new AccountPage(page);
    await account.goto();
    await account.updateProfile({ firstName: 'Updated', lastName: 'Profile' });
    await account.expectSuccessMessage();
  });

  test('updated values persist after page reload', async ({ page }) => {
    const email = createTestEmail();
    registerForCleanup(email);
    await signupAndLogin(page, email);

    const account = new AccountPage(page);
    await account.goto();
    await account.updateProfile({ firstName: 'Persisted', lastName: 'Values' });
    await account.expectSuccessMessage();

    // Reload and verify
    await page.reload();
    await expect(account.page.locator('h2', { hasText: 'My Profile' })).toBeVisible();
    await expect(account.firstNameInput).toHaveValue('Persisted');
    await expect(account.lastNameInput).toHaveValue('Values');
  });
});
