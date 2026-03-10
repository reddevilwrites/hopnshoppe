import { type Page, type Locator, expect } from '@playwright/test';

export interface SignupForm {
  email: string;
  firstName: string;
  lastName: string;
  phone?: string;
  password: string;
}

export class SignupPage {
  readonly page: Page;
  readonly errorMessage: Locator;
  readonly successMessage: Locator;
  readonly submitButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.errorMessage = page.locator('.text-red-600');
    this.successMessage = page.locator('.text-green-600');
    this.submitButton = page.locator('button[type="submit"]');
  }

  async goto() {
    await this.page.goto('/signup');
  }

  async signup(form: SignupForm) {
    await this.page.locator('input[name="email"]').fill(form.email);
    await this.page.locator('input[name="firstName"]').fill(form.firstName);
    await this.page.locator('input[name="lastName"]').fill(form.lastName);
    if (form.phone) {
      await this.page.locator('input[name="phone"]').fill(form.phone);
    }
    await this.page.locator('input[name="password"]').fill(form.password);
    await this.submitButton.click();
  }

  async expectSuccess() {
    await expect(this.successMessage).toBeVisible();
    await expect(this.successMessage).toContainText('Account created');
  }

  async expectError(text?: string) {
    await expect(this.errorMessage).toBeVisible();
    if (text) {
      await expect(this.errorMessage).toContainText(text);
    }
  }
}
