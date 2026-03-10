import { type Page, type Locator, expect } from '@playwright/test';

export class CartPage {
  readonly page: Page;
  readonly heading: Locator;
  readonly emptyMessage: Locator;
  readonly errorMessage: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.locator('h1', { hasText: 'Shopping Cart' });
    this.emptyMessage = page.locator('p', { hasText: 'Your cart is empty' });
    this.errorMessage = page.locator('.text-red-600');
  }

  async goto() {
    await this.page.goto('/cart');
    await expect(this.heading).toBeVisible();
  }

  /** Returns all cart item rows. */
  getItems(): Locator {
    return this.page.locator('.lg\\:col-span-2 > div');
  }

  /** Returns the quantity display for a specific SKU. */
  getQuantityFor(sku: string): Locator {
    return this.page
      .locator('div', { hasText: `SKU: ${sku}` })
      .locator('xpath=ancestor::div[contains(@class,"border")]')
      .locator('span.font-semibold');
  }

  async incrementItem(sku: string) {
    const row = this.page.locator('div', { hasText: `SKU: ${sku}` }).locator('xpath=ancestor::div[contains(@class,"border")]');
    await row.locator('button', { hasText: '+' }).click();
  }

  async decrementItem(sku: string) {
    const row = this.page.locator('div', { hasText: `SKU: ${sku}` }).locator('xpath=ancestor::div[contains(@class,"border")]');
    await row.locator('button', { hasText: '-' }).click();
  }

  async removeItem(sku: string) {
    const row = this.page.locator('div', { hasText: `SKU: ${sku}` }).locator('xpath=ancestor::div[contains(@class,"border")]');
    await row.locator('button', { hasText: 'Remove' }).click();
  }

  async expectEmpty() {
    await expect(this.emptyMessage).toBeVisible();
  }

  async expectItemCount(count: number) {
    await expect(this.getItems()).toHaveCount(count);
  }
}
