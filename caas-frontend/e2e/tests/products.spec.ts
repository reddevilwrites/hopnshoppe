import { test, expect } from '@playwright/test';
import { ProductListPage } from '../pages/ProductListPage';
import { ProductDetailPage } from '../pages/ProductDetailPage';

/** Mock products returned by page.route() for catalog-service calls. */
const MOCK_PRODUCTS = [
  { sku: 'SKU-001', title: 'Ceramic Mug', description: 'A nice mug', price: 12.99, availability: true, category: 'Kitchenware', imagePath: '' },
  { sku: 'SKU-002', title: 'Wooden Spoon', description: 'Handcrafted', price: 5.49, availability: true, category: 'Kitchenware', imagePath: '' },
  { sku: 'SKU-003', title: 'Canvas Tote', description: 'Eco bag', price: 19.99, availability: false, category: 'Accessories', imagePath: '' },
  { sku: 'SKU-004', title: 'Steel Bottle', description: 'Insulated', price: 24.99, availability: true, category: 'Kitchenware', imagePath: '' },
  { sku: 'SKU-005', title: 'Bamboo Cutting Board', description: 'Sustainable', price: 34.99, availability: true, category: 'Kitchenware', imagePath: '' },
  { sku: 'SKU-006', title: 'Linen Napkins', description: 'Set of 4', price: 16.99, availability: true, category: 'Textiles', imagePath: '' },
  { sku: 'SKU-007', title: 'Glass Jar', description: 'Mason jar', price: 8.99, availability: true, category: 'Storage', imagePath: '' },
];

test.describe('Product catalog (mocked)', () => {
  test.beforeEach(async ({ page }) => {
    // Mock the catalog-service product list endpoint
    await page.route('/api/products', (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_PRODUCTS) });
    });
    // Mock individual product lookups
    await page.route('/api/products/**', (route) => {
      const url = route.request().url();
      const sku = url.split('/api/products/')[1];
      const product = MOCK_PRODUCTS.find((p) => p.sku === sku);
      if (product) {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(product) });
      } else {
        route.fulfill({ status: 404 });
      }
    });
  });

  test('product list renders mocked products', async ({ page }) => {
    const productList = new ProductListPage(page);
    await productList.goto();

    // 6 products per page — page 1 shows first 6
    await expect(productList.getProductCards()).toHaveCount(6);
  });

  test('search filters products by title (client-side)', async ({ page }) => {
    const productList = new ProductListPage(page);
    await productList.goto();

    await productList.search('Mug');
    await expect(productList.getProductCards()).toHaveCount(1);
    await expect(page.locator('h2', { hasText: 'Ceramic Mug' })).toBeVisible();
  });

  test('pagination — page 2 shows remaining products', async ({ page }) => {
    const productList = new ProductListPage(page);
    await productList.goto();

    // 7 products total → page 1 has 6, page 2 has 1
    await expect(productList.getPageButtons()).toHaveCount(2);
    await productList.clickPageButton(2);
    await expect(productList.getProductCards()).toHaveCount(1);
    await expect(page.locator('h2', { hasText: 'Glass Jar' })).toBeVisible();
  });

  test('click product card — navigates to /products/:sku', async ({ page }) => {
    const productList = new ProductListPage(page);
    await productList.goto();

    await productList.clickProduct('Ceramic Mug');
    await expect(page).toHaveURL(/\/products\/SKU-001/);
  });

  test('product detail shows title, price, availability', async ({ page }) => {
    const detail = new ProductDetailPage(page);
    await detail.goto('SKU-001');

    await detail.expectTitle('Ceramic Mug');
    await expect(page.locator('text=₹12.99')).toBeVisible();
    await expect(page.locator('text=In Stock')).toBeVisible();
  });
});
