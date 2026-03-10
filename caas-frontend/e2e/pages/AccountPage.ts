import { type Page, type Locator, expect } from '@playwright/test';

export class AccountPage {
  readonly page: Page;
  readonly firstNameInput: Locator;
  readonly lastNameInput: Locator;
  readonly emailInput: Locator;
  readonly phoneInput: Locator;
  readonly saveButton: Locator;
  readonly message: Locator;

  constructor(page: Page) {
    this.page = page;
    this.firstNameInput = page.locator('input[name="firstName"]');
    this.lastNameInput = page.locator('input[name="lastName"]');
    this.emailInput = page.locator('input[name="email"]');
    this.phoneInput = page.locator('input[name="phone"]');
    this.saveButton = page.locator('button[type="submit"]', { hasText: 'Save Changes' });
    this.message = page.locator('.text-green-600');
  }

  async goto() {
    await this.page.goto('/account');
    await expect(this.page.locator('h2', { hasText: 'My Profile' })).toBeVisible();
  }

  async expectEmail(email: string) {
    await expect(this.emailInput).toHaveValue(email);
  }

  async updateProfile(data: { firstName?: string; lastName?: string; phone?: string }) {
    if (data.firstName !== undefined) await this.firstNameInput.fill(data.firstName);
    if (data.lastName !== undefined) await this.lastNameInput.fill(data.lastName);
    if (data.phone !== undefined) await this.phoneInput.fill(data.phone);
    await this.saveButton.click();
  }

  async expectSuccessMessage() {
    await expect(this.message).toBeVisible();
    await expect(this.message).toContainText('Profile updated');
  }
}
