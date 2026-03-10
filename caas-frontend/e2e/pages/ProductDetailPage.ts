import { type Page, type Locator, expect } from '@playwright/test';

export class ProductDetailPage {
  readonly page: Page;
  readonly addToCartButton: Locator;
  readonly statusMessage: Locator;
  readonly backLink: Locator;

  constructor(page: Page) {
    this.page = page;
    this.addToCartButton = page.locator('button', { hasText: 'Add to Cart' });
    this.statusMessage = page.locator('p.text-sm.text-gray-700');
    this.backLink = page.locator('a', { hasText: '← Back to Products' });
  }

  async goto(sku: string) {
    await this.page.goto(`/products/${sku}`);
    await this.waitForProduct();
  }

  async waitForProduct() {
    // Wait until the Loading... text disappears
    await expect(this.page.locator('p', { hasText: 'Loading...' })).toHaveCount(0, { timeout: 10_000 });
  }

  async addToCart() {
    await this.addToCartButton.click();
  }

  async expectStatus(text: string) {
    await expect(this.statusMessage).toBeVisible();
    await expect(this.statusMessage).toContainText(text);
  }

  async expectTitle(title: string) {
    await expect(this.page.locator('h2', { hasText: title })).toBeVisible();
  }
}
