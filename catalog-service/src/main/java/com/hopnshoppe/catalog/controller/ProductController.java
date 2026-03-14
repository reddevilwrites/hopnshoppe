package com.hopnshoppe.catalog.controller;

import com.hopnshoppe.catalog.model.ProductDTO;
import com.hopnshoppe.catalog.service.CatalogOrchestrator;
import com.hopnshoppe.catalog.service.ProductService;
import com.hopnshoppe.common.dto.UnifiedProductDTO;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/products")
public class ProductController {

    private static final Logger logger = LoggerFactory.getLogger(ProductController.class);

    private final ProductService productService;
    private final CatalogOrchestrator catalogOrchestrator;

    public ProductController(ProductService productService, CatalogOrchestrator catalogOrchestrator) {
        this.productService = productService;
        this.catalogOrchestrator = catalogOrchestrator;
    }

    @GetMapping
    public List<ProductDTO> getProducts(
            @RequestParam(required = false) String category,
            @RequestParam(required = false) Boolean availability) {
        logger.info("GET /products category={} availability={}", category, availability);
        return productService.fetchFilteredProducts(category, availability);
    }

    @GetMapping("/{sku}")
    public ResponseEntity<ProductDTO> getProductBySku(@PathVariable String sku) {
        ProductDTO product = productService.fetchProductBySku(sku);
        if (product == null) {
            return ResponseEntity.notFound().build();
        }
        return ResponseEntity.ok(product);
    }

    /**
     * Aggregated product listing merging all catalog providers (AEM, PIM, Legacy SOAP).
     *
     * <p>All providers are executed in parallel by the {@link CatalogOrchestrator}.
     * A failing provider contributes an empty list — the endpoint never fails due to
     * a single source outage.
     *
     * <p>Accessible at: {@code GET /api/products/unified}
     */
    @GetMapping("/unified")
    public List<UnifiedProductDTO> getUnifiedProducts() {
        logger.info("GET /products/unified");
        return catalogOrchestrator.fetchAllProducts();
    }

    /**
     * Looks up a single product by ID from either AEM or MARKETPLACE.
     * Used by cart-service for product enrichment.
     *
     * <p>Accessible at: {@code GET /api/products/unified/{id}}
     */
    @GetMapping("/unified/{id}")
    public ResponseEntity<UnifiedProductDTO> getUnifiedProductById(@PathVariable String id) {
        logger.info("GET /products/unified/{}", id);
        UnifiedProductDTO product = productService.fetchUnifiedProductById(id);
        if (product == null) {
            return ResponseEntity.notFound().build();
        }
        return ResponseEntity.ok(product);
    }

    /**
     * Batch lookup for multiple product IDs from either AEM or MARKETPLACE.
     * Used by cart-service to enrich a full cart in a single call instead of N individual calls.
     *
     * <p>AEM products are resolved with a single GraphQL fetch; MARKETPLACE lookups run in parallel.
     * Missing IDs are silently omitted — the caller receives only the products that were found.
     *
     * <p>Accessible at: {@code GET /api/products/unified/batch?ids=sku1,sku2,3,4}
     */
    @GetMapping("/unified/batch")
    public List<UnifiedProductDTO> getUnifiedProductsByIds(@RequestParam List<String> ids) {
        logger.info("GET /products/unified/batch ids={}", ids);
        return productService.fetchUnifiedProductsByIds(ids);
    }
}
