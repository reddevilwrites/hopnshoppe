import { test, expect } from '@playwright/test';
import { LoginPage } from '../pages/LoginPage';
import { SignupPage } from '../pages/SignupPage';
import { createTestEmail, registerForCleanup } from '../fixtures/testAccounts';

test.describe('Authentication flows', () => {
  test('signup happy path — success message shown', async ({ page }) => {
    const email = createTestEmail();
    registerForCleanup(email);

    const signup = new SignupPage(page);
    await signup.goto();
    await signup.signup({
      email,
      firstName: 'Test',
      lastName: 'User',
      password: 'Password123',
    });
    await signup.expectSuccess();
  });

  test('signup duplicate email — readable error (not blank page)', async ({ page }) => {
    const email = createTestEmail();
    registerForCleanup(email);

    const signup = new SignupPage(page);
    await signup.goto();

    // First signup succeeds
    await signup.signup({ email, firstName: 'Test', lastName: 'User', password: 'Password123' });
    await signup.expectSuccess();

    // Reload and try again with the same email
    await signup.goto();
    await signup.signup({ email, firstName: 'Test', lastName: 'User', password: 'Password123' });

    // Page must NOT be blank — error message visible
    await signup.expectError('already exists');
    await expect(page.locator('form')).toBeVisible({ message: 'Form should still be visible (no blank page)' });
  });

  test('signup invalid email format — client-side validation', async ({ page }) => {
    const signup = new SignupPage(page);
    await signup.goto();
    await signup.signup({
      email: 'not-an-email',
      firstName: 'Test',
      lastName: 'User',
      password: 'Password123',
    });
    await signup.expectError('valid Email');
  });

  test('login valid credentials — redirects to /products', async ({ page }) => {
    // Create account first
    const email = createTestEmail();
    registerForCleanup(email);
    const signup = new SignupPage(page);
    await signup.goto();
    await signup.signup({ email, firstName: 'Test', lastName: 'User', password: 'Password123' });
    await signup.expectSuccess();

    // Now login
    const login = new LoginPage(page);
    await login.goto();
    await login.login(email, 'Password123');
    await login.expectRedirectToProducts();
  });

  test('login invalid credentials — "Invalid Credentials" shown', async ({ page }) => {
    const login = new LoginPage(page);
    await login.goto();
    await login.login('nobody@hopnshoppe.test', 'wrongpassword');
    await login.expectError('Invalid Credentials');
  });

  test('navigate to /account without token — redirects to /login', async ({ page }) => {
    // Ensure no token
    await page.context().clearCookies();
    await page.evaluate(() => sessionStorage.clear());

    await page.goto('/account');
    await expect(page).toHaveURL(/\/login/);
  });

  test('navigate to /cart without token — redirects to /login', async ({ page }) => {
    await page.evaluate(() => sessionStorage.clear());
    await page.goto('/cart');
    await expect(page).toHaveURL(/\/login/);
  });

  test('logout — token cleared, redirects to /login', async ({ page }) => {
    // Create and login a test account
    const email = createTestEmail();
    registerForCleanup(email);
    const signup = new SignupPage(page);
    await signup.goto();
    await signup.signup({ email, firstName: 'Test', lastName: 'User', password: 'Password123' });
    await signup.expectSuccess();

    const login = new LoginPage(page);
    await login.goto();
    await login.login(email, 'Password123');
    await login.expectRedirectToProducts();

    // Click the user icon to open dropdown
    await page.locator('button').filter({ hasText: /Hi/ }).click();

    // Click Logout
    await page.locator('button', { hasText: 'Logout' }).click();
    await expect(page).toHaveURL(/\/login/);

    // Verify token removed
    const token = await page.evaluate(() => sessionStorage.getItem('token'));
    expect(token).toBeNull();
  });
});
